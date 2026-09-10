"""The extractor plugin protocol, and the capture bundle it rolls up into.

docs/DIAGNOSTIC_PLAN.md Phase 28 fields 7, 8 and 9; the prose contract is
`docs/EXTRACTOR_PROTOCOL.md`, which third parties read and this module
enforces.

An extractor is any executable that reads one JSON object on stdin and
writes one JSON object on stdout (D3). That is the whole interface. It
exists in this deliberately dull form because introspecting a FastAPI app
means *importing* it, which means running inside that project's own
virtualenv — no external process can do it correctly, so the boundary has
to be a subprocess rather than a library call.

**The honesty rule, which is the part that matters.** An extractor that
cannot answer part of a request puts an entry in `skipped` with a reason
and exits zero. It never guesses and it never fails the run. A non-zero
exit or unparseable stdout is turned into a `skipped` entry by the
orchestrator for the same reason (`Skip.from_failure`): a missing
extractor must degrade the report, not break it, and the user must be
told precisely which facts are missing and why. "I could not check X" is
a finding.

Definitions here are mirrored in `cli/internal/model/protocol.go` and the
two are held together by `cli/internal/model/testdata/protocol_conformance.json`.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from culprit_model.capabilities import ALLOWLISTED, Capability
from culprit_model.facts import Fact
from culprit_model.planes import Plane
from culprit_model.redaction import looks_like_credential

#: Bumped only for a breaking change to the request/response shape. An
#: extractor that does not understand the protocol version it is handed
#: must skip everything and say so, rather than answer a question it may
#: be misreading.
EXTRACTOR_PROTOCOL_VERSION = 1


class Want(StrEnum):
    """The classes of fact an orchestrator can ask for.

    Field 7 of the plan names the first five. `DEPENDENCIES` is a sixth,
    added here because acceptance criterion 1 requires dependency
    versions and the five had no home for them — recorded as a plan
    correction in docs/HANDOFF.md §5 rather than quietly folded into
    `db_schema`.

    An extractor answers the ones it can and skips the rest. Asking for
    something an extractor has never heard of is not an error: it skips
    it with `unsupported want`, which is exactly what a newer
    orchestrator talking to an older extractor should produce.
    """

    HTTP_ROUTES = "http_routes"
    DB_SCHEMA = "db_schema"
    CONFIG_KEYS = "config_keys"
    CLIENT_CALLS = "client_calls"
    TEST_ASSERTIONS = "test_assertions"
    DEPENDENCIES = "dependencies"


class Predicate(StrEnum):
    """The predicates this phase's extractors emit.

    `Fact.predicate` is deliberately a plain `str` and not this enum: D7
    says the comparator knows nothing about HTTP, SQL or auth, and
    closing the predicate vocabulary in the core model would make adding
    a fault class an engine change — the exact thing D7 exists to
    prevent. These are the named constants for the ones we emit, so the
    Go side and the Python side agree without either hard-coding a
    string literal.
    """

    EXISTS = "exists"
    REQUEST_SCHEMA = "request_schema"
    RESPONSE_SCHEMA = "response_schema"
    STATUS_CODES = "status_codes"
    #: A `schema:` subject's column list, or one column's type/nullability.
    COLUMNS = "columns"
    COLUMN_TYPE = "column_type"
    NULLABLE = "nullable"
    #: The Alembic/Django/Prisma revision the repository's migrations
    #: currently head at — an INTENT claim about what schema the code
    #: expects, not a reading of any database.
    MIGRATION_HEAD = "migration_head"
    #: A `dep:` subject's declared version specifier.
    VERSION = "version"
    #: A `config:` subject: the key is read somewhere in the code.
    READ_BY = "read_by"
    #: Kept as a name a third-party extractor may use; nothing in this
    #: repository emits it any more. It was one predicate carrying two
    #: different claims, and Phase 29 found the false positive that
    #: results: `.env.example` reporting a long opaque placeholder and
    #: the code reporting an empty default is not a disagreement, it is
    #: two different facts. Comparison is by (subject, predicate), so
    #: claims that are not the same claim may not share a predicate.
    VALUE_SHAPE = "value_shape"
    #: The shape of the placeholder committed in a `.env.example`.
    EXAMPLE_SHAPE = "example_shape"
    #: The shape of the default a piece of code falls back to.
    DEFAULT_SHAPE = "default_shape"
    REQUIRED = "required"
    #: A client call site — "this component calls that path".
    CALLS = "calls"
    #: A test exercises this route. Deliberately not the status code the
    #: test asserts: a route answering 201 to an admin and 403 to a
    #: member is one route behaving correctly, not two sources
    #: disagreeing. See `extract_test_assertions`.
    EXERCISED_BY_TEST = "exercised_by_test"


class Skip(BaseModel):
    """One thing an extractor was asked for and could not provide.

    `reason` is required and free text, because the reader of a report is
    a human deciding whether the gap matters. A machine-readable code
    would be less useful and would go stale faster than the situations
    it names.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    want: str
    reason: str
    #: Which component the gap is in. Filled in by the orchestrator,
    #: because only it knows — a report listing "no .env.example found"
    #: three times with no way to tell which of three services each line
    #: is about is a report nobody can act on.
    component: str | None = None
    #: The extractor that skipped, filled in by the orchestrator when it
    #: synthesises a skip on a failed extractor's behalf.
    extractor: str | None = None

    @classmethod
    def from_failure(cls, extractor: str, wants: "list[str]", reason: str) -> "list[Skip]":
        """Turns one extractor failure into a skip per requested want.

        Per want, not one aggregate: the report says what is missing, and
        "http_routes and config_keys are missing because the extractor is
        not installed" is a different sentence from "something went
        wrong".
        """
        return [cls(want=want, reason=reason, extractor=extractor) for want in wants]


class ExtractorRequest(BaseModel):
    """What the orchestrator writes to an extractor's stdin (field 7)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol: int = EXTRACTOR_PROTOCOL_VERSION
    #: Absolute path to the source root the extractor should look at.
    root: str
    want: tuple[Want, ...] = ()
    #: NULL for an INTENT extraction. Present only once environment
    #: capture exists (Phase 30) — extractors in this phase are handed
    #: null and must not go looking for a live system.
    environment: str | None = None
    #: The component these facts are about. Not in field 7's literal
    #: shape, and required in practice: every subject URI this phase
    #: builds needs a component name, and an extractor cannot invent one
    #: that will match the system model. Recorded as a plan correction.
    component: str | None = None


class ExtractorResponse(BaseModel):
    """What an extractor writes to stdout (field 7). Exactly one object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol: int = EXTRACTOR_PROTOCOL_VERSION
    #: `name@version`, e.g. `culprit-extract-python@0.1.0`. Ends up in
    #: every fact's `provenance.extractor`, which is what makes a wrong
    #: fact traceable to the thing that got it wrong.
    extractor: str
    facts: tuple[Fact, ...] = ()
    skipped: tuple[Skip, ...] = ()


class Grant(BaseModel):
    """One capability a CONFIGURED capture ran under (Phase 30, §2.7).

    Recorded whether or not it was used: a reader of a capture attached
    to a bug report is asking what the tool was *allowed* to look at, and
    a grant never exercised is part of that answer. The Go mirror is
    `model.Grant` in `cli/internal/model/protocol.go`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: A §2.7 name from the closed set — a grant list naming
    #: `db.schema.write` is refused, not stored and served back.
    capability: Capability
    allow: tuple[str, ...] = ()
    used: bool

    @model_validator(mode="after")
    def _allowlist_matches_the_capability(self) -> "Grant":
        """A per-item capability names its items; any other names none."""
        if self.capability in ALLOWLISTED and not self.allow:
            raise ValueError(f"{self.capability} is granted per item and names none")
        if self.capability not in ALLOWLISTED and self.allow:
            raise ValueError(f"{self.capability} is not granted per item")
        return self


class Refusal(BaseModel):
    """One check a capture did not perform because its capability was not
    granted — §2.6's `refused`, for a capture.

    A refusal is never an omission: "I could not check X because you have
    not granted Y" is part of what a capture says. Built by the CLI from
    closed vocabulary and manifest names only (standing invariant 11).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: Capability
    component: str | None = None
    check: str
    reason: str


class CaptureBundle(BaseModel):
    """One extraction run, whole: what was asked, what came back, what did not.

    This is the artefact §5 of the plan promises is safe to attach to a
    bug report, and the body `POST /facts/captures` accepts. Its safety
    is not a review convention — every `Fact` inside it has already
    refused to be constructed carrying an ungranted config value, so
    serialising the bundle cannot produce one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol: int = EXTRACTOR_PROTOCOL_VERSION
    plane: Plane = Plane.INTENT
    environment: str | None = None
    #: The orchestrator, not the plugins — `culprit@0.1.0`. Each fact
    #: carries the plugin that produced it in its own provenance.
    extractor: str
    capture_id: UUID
    started_at: datetime
    finished_at: datetime | None = None
    facts: tuple[Fact, ...] = ()
    skipped: tuple[Skip, ...] = ()
    #: Free-form, non-secret run context — the source root, the component
    #: names looked at, the CLI version. Never config values.
    meta: dict[str, str] = Field(default_factory=dict)
    #: Phase 30 field 7: the grant set a CONFIGURED capture ran under and
    #: the checks it was refused, "so a reader can tell what was *not*
    #: looked at". Empty for an INTENT capture, which reads no environment.
    grants: tuple[Grant, ...] = ()
    refused: tuple[Refusal, ...] = ()

    @model_validator(mode="after")
    def _free_text_carries_no_credential(self) -> "CaptureBundle":
        """Skip reasons, refusal reasons and `meta` values are free text,
        and a capture file is something anyone can edit and re-hash. The
        CLI builds all three from closed vocabulary; a credential-shaped
        one was written by hand, and storing it would put it in front of
        every reader of `GET /captures/{id}`. Refused by field and index,
        never by content (invariant 11). The CLI refuses the same envelope
        when it opens one (`capture.Open`)."""
        for index, skip in enumerate(self.skipped):
            if looks_like_credential(skip.reason):
                raise ValueError(f"skipped.{index}.reason carries credential-shaped text")
        for index, refusal in enumerate(self.refused):
            if looks_like_credential(refusal.reason):
                raise ValueError(f"refused.{index}.reason carries credential-shaped text")
        for name, value in self.meta.items():
            if looks_like_credential(value):
                raise ValueError(f"meta.{name} carries credential-shaped text")
        return self

    @model_validator(mode="after")
    def _facts_are_on_the_bundles_plane(self) -> "CaptureBundle":
        """Every fact must be on the plane the bundle declares.

        Without this the planes leak into each other at the one place
        they are written down. A bundle declaring `INTENT` whose facts
        say `CONFIGURED` was accepted and stored in `intent_facts` — a
        table with no `environment` and no `plane` column, because the
        plane *is* the table — so a reading of production landed as a
        claim about what the system is supposed to do, with its
        environment silently dropped. Phase 29's comparator would then
        compare production against itself and call the result intent.

        That is precisely the plane confusion `.claude/rules/model.md`
        names as the mistake this architecture exists to fix, so it is
        refused here rather than in the storage layer: this model is the
        request body, so the refusal is FastAPI's own validation and no
        code path can route around it.

        The environment is checked with it, for the same reason. A
        CONFIGURED bundle for `staging` carrying a fact stamped
        `production` is two captures spliced together, and storing either
        answer would be a guess.
        """
        for fact in self.facts:
            if fact.plane is not self.plane:
                raise ValueError(
                    f"fact {fact.subject!r} is on plane {fact.plane}, but this "
                    f"capture declares {self.plane}. A capture is one plane's "
                    "worth of claims; splitting it across planes is how a reading "
                    "of an environment becomes a claim about intent."
                )
            if fact.environment != self.environment:
                raise ValueError(
                    f"fact {fact.subject!r} carries environment "
                    f"{fact.environment!r}, but this capture is for "
                    f"{self.environment!r}"
                )
        return self
