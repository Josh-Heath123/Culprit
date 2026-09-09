"""`ValueShape` — what a config value *is*, with no way to say what it *says*.

docs/DIAGNOSTIC_PLAN.md §2.2, and the Phase 26.1 remediation the Phase 27
handoff scheduled into Phase 28 (docs/HANDOFF.md §3, Q5).

The problem this exists to close, stated plainly. Phase 26.1 added a
CHECK constraint making `configured_facts.value` unable to hold a literal
without an explicit `grant_ref`. That constraint guards the column
extractors are told *not* to use. The column they are steered *towards*,
`value_shape`, was free-form JSONB, so

    {"type": "url", "sample": "postgresql://u:hunter2@db/orders"}

inserted happily with no grant at all. Worse, `Fact` carried neither
field, so Postgres was the *only* enforcement point — and the artefact
the promise in §5 is actually about is a capture bundle serialised to
JSON and attached to a bug report, which never touches Postgres.

So the guarantee moves into the type. A `ValueShape` has exactly four
fields and every one of them is a closed enum or a bool. There is no
field a string can be put in. Not "no field a string *should* be put
in" — no field one *can* be put in, which is why the promise survives
`model_dump_json()` on a bundle that never reaches a database.

    ValueShape.of("postgresql://u:hunter2@db/orders")
    # ValueShape(type=STRING, length_class=MEDIUM, format=DSN, present=True)

That is the whole API for turning a real value into a shape: `of()` looks
at a value and returns a classification, and the value it looked at is
not reachable from what it returns.

**What is deliberately lost.** §2.2's older illustrative example was
`{"type": "url", "scheme": "postgresql", "host_resolves": true}`. There
is no `scheme` here. The decision register (2026-09-09, resolving Q5)
fixes the field set at `type`, `length_class`, `format`, `present`, and
widening it is an architecture decision, not an implementation one. The
cost is real and is recorded in `docs/LIMITS.md`: a `DATABASE_URL`
pointing at `postgresql://` in staging and `mysql://` in production has
the same shape, so that divergence is invisible to shape comparison.

Deterministic and dependency-free — see `.claude/rules/determinism.md`.
"""

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class ValueType(StrEnum):
    """The JSON-ish type of a config value.

    `UNKNOWN` is honest rather than a fallback nobody meant: an extractor
    that found a key it could not read the type of says so, and a
    comparison against `UNKNOWN` is not a divergence.
    """

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    LIST = "list"
    MAPPING = "mapping"
    NULL = "null"
    UNKNOWN = "unknown"


class LengthClass(StrEnum):
    """A coarse bucket, never a length.

    Buckets, not the integer, on purpose. A length is a small leak — it
    distinguishes a 32-character key from a 64-character one and narrows
    a brute-force search — and it is not information any comparison in
    this plan needs. "The staging value is EMPTY and production's is
    MEDIUM" is the finding; "31 versus 44" adds nothing to it.

    `NOT_APPLICABLE` is for values with no meaningful length (a bool, a
    number), as distinct from `EMPTY`, which means a present-but-blank
    string — a genuinely common misconfiguration and one worth seeing.
    """

    NOT_APPLICABLE = "not_applicable"
    EMPTY = "empty"
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class ValueFormat(StrEnum):
    """The format class a value appears to be in.

    A closed vocabulary, and the only place any judgement about a value's
    content is recorded. `OPAQUE` means "a string that matched nothing
    below", which is the common case and carries no information about the
    string beyond that.
    """

    OPAQUE = "opaque"
    URL = "url"
    #: A URL carrying inline credentials (`scheme://user:pass@host/db`).
    #: Distinguished from URL precisely because "this key's value has a
    #: password baked into it" is a finding, and one that can be reported
    #: without reporting the password.
    DSN = "dsn"
    EMAIL = "email"
    HOSTNAME = "hostname"
    IP_ADDRESS = "ip_address"
    PORT = "port"
    PATH = "path"
    DURATION = "duration"
    BOOLEANISH = "booleanish"
    NUMERIC = "numeric"
    UUID = "uuid"
    JSON = "json"
    #: Credential-shaped: a PEM block, a JWT, a recognised provider key
    #: prefix. The presence of one of these in a place a capture can see
    #: is itself worth surfacing.
    SECRET = "secret"
    LIST = "list"
    NOT_APPLICABLE = "not_applicable"


#: Ordered: the first match wins, so the more specific patterns come
#: first. `DSN` before `URL` because every DSN is also a URL, and
#: `SECRET` before everything because a JWT is also `OPAQUE`-shaped and
#: the more alarming classification is the one worth keeping.
_FORMAT_PATTERNS: tuple[tuple[ValueFormat, re.Pattern[str]], ...] = (
    (
        ValueFormat.SECRET,
        re.compile(
            r"^-----BEGIN [A-Z ]*PRIVATE KEY-----"
            r"|^eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
            r"|^AKIA[0-9A-Z]{16}$"
            r"|^gh[pousr]_[A-Za-z0-9]{20,}$"
            r"|^sk-[A-Za-z0-9]{20,}$"
            r"|^xox[baprs]-[A-Za-z0-9-]{10,}$"
        ),
    ),
    (ValueFormat.DSN, re.compile(r"^[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]*@", re.IGNORECASE)),
    (ValueFormat.URL, re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)),
    (
        ValueFormat.UUID,
        re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I),
    ),
    (ValueFormat.EMAIL, re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")),
    (ValueFormat.BOOLEANISH, re.compile(r"^(true|false|yes|no|on|off|1|0)$", re.IGNORECASE)),
    (ValueFormat.PORT, re.compile(r"^(?:[1-9]\d{0,3}|[1-5]\d{4}|6[0-4]\d{3}|65[0-4]\d{2})$")),
    (ValueFormat.DURATION, re.compile(r"^\d+(?:\.\d+)?\s*(?:ms|s|m|h|d)$", re.IGNORECASE)),
    (ValueFormat.NUMERIC, re.compile(r"^-?\d+(?:\.\d+)?$")),
    (
        ValueFormat.IP_ADDRESS,
        re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?$|^\[?[0-9a-f:]{3,}\]?(?::\d+)?$", re.I),
    ),
    (ValueFormat.PATH, re.compile(r"^(?:/|\./|\.\./|[A-Za-z]:[\\/])")),
    (ValueFormat.JSON, re.compile(r"^\s*[\[{]")),
    (
        ValueFormat.HOSTNAME,
        re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+"
                   r"(?::\d{1,5})?$", re.IGNORECASE),
    ),
)

#: Length bucket boundaries, in characters. Chosen so the buckets mean
#: something to a reader rather than being evenly spaced: SHORT is a
#: flag or a port, MEDIUM is a hostname or a URL, LONG is a key, a
#: certificate or a serialised blob.
_SHORT_MAX = 16
_MEDIUM_MAX = 128


class ValueShape(BaseModel):
    """What a value is, with no room for what it says.

    Four fields, every one closed. `extra="forbid"` and `frozen=True`
    together mean neither a caller nor a deserialiser can add a fifth —
    `ValueShape(**{"type": "url", "sample": "postgres://..."})` raises,
    which is the specific attack the Phase 27 audit demonstrated against
    the free-JSONB version. `shared/tests/test_shape.py` proves that by
    attempting it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: **All four are required, with no defaults.** Defaults looked
    #: harmless and were not: a shape arriving over the wire without
    #: `present` was silently completed to `present=True` and stored as
    #: though the extractor had said so. `present` is the field that says
    #: whether the key was actually set, so the default manufactured the
    #: *more assertive* answer — a fact invented rather than read, which
    #: is the one thing D8 forbids outright. The database cannot catch it
    #: either, because pydantic fills the key in before the insert.
    #: (Found by the Phase 28 invariant audit.)
    #:
    #: Construct one through `of()`, `absent()` or `unknown()` rather than
    #: by hand; those name every field.
    type: ValueType
    length_class: LengthClass
    format: ValueFormat
    #: Whether the key was set at all in the environment being described.
    #: `present=False` is the single most common real finding ("the key
    #: exists in .env.example and is unset in staging") and needs to be
    #: expressible without inventing a fake value to describe.
    present: bool

    @classmethod
    def absent(cls) -> "ValueShape":
        """The shape of a config key that is not set."""
        return cls(
            type=ValueType.NULL,
            length_class=LengthClass.NOT_APPLICABLE,
            format=ValueFormat.NOT_APPLICABLE,
            present=False,
        )

    @classmethod
    def unknown(cls) -> "ValueShape":
        """A key known to exist whose value the extractor could not read.

        Distinct from `absent()`: "declared in .env.example, and I have
        no access to this environment's value" is not the same claim as
        "unset", and collapsing them would manufacture divergences.
        """
        return cls(
            type=ValueType.UNKNOWN,
            length_class=LengthClass.NOT_APPLICABLE,
            format=ValueFormat.NOT_APPLICABLE,
            present=True,
        )

    @classmethod
    def of(cls, value: Any) -> "ValueShape":
        """Classifies a real value, returning something that cannot leak it.

        The one sanctioned way to get a shape from a value. Callers hold
        the value; what they hand on is this.
        """
        if value is None:
            return cls.absent()
        if isinstance(value, bool):
            return cls(
                type=ValueType.BOOLEAN,
                length_class=LengthClass.NOT_APPLICABLE,
                format=ValueFormat.BOOLEANISH,
                present=True,
            )
        if isinstance(value, int):
            return cls(
                type=ValueType.INTEGER,
                length_class=LengthClass.NOT_APPLICABLE,
                format=ValueFormat.NUMERIC,
                present=True,
            )
        if isinstance(value, float):
            return cls(
                type=ValueType.NUMBER,
                length_class=LengthClass.NOT_APPLICABLE,
                format=ValueFormat.NUMERIC,
                present=True,
            )
        if isinstance(value, (list, tuple, set, frozenset)):
            return cls(
                type=ValueType.LIST,
                length_class=_length_class(len(value)),
                format=ValueFormat.LIST,
                present=True,
            )
        if isinstance(value, dict):
            return cls(
                type=ValueType.MAPPING,
                length_class=_length_class(len(value)),
                format=ValueFormat.JSON,
                present=True,
            )
        text = str(value)
        return cls(
            type=ValueType.STRING,
            length_class=_length_class(len(text)),
            format=classify_format(text),
            present=True,
        )


def classify_format(text: str) -> ValueFormat:
    """The format class of a string. Pure, total, and never echoes input."""
    candidate = text.strip()
    if not candidate:
        return ValueFormat.NOT_APPLICABLE
    for value_format, pattern in _FORMAT_PATTERNS:
        if pattern.search(candidate):
            return value_format
    return ValueFormat.OPAQUE


def _length_class(length: int) -> LengthClass:
    if length == 0:
        return LengthClass.EMPTY
    if length <= _SHORT_MAX:
        return LengthClass.SHORT
    if length <= _MEDIUM_MAX:
        return LengthClass.MEDIUM
    return LengthClass.LONG
