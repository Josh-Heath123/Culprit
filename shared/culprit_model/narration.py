"""The narrator's input, and the check its prose must pass — Phase 35 part 2.

The narrator is the one LLM call in the system (D8). It is given a settled
investigation as a numbered list of evidence and writes plain prose — what
failed, why, and what to change — citing evidence by number, `[3]`. This
module is the deterministic half on either side of that call:

- `evidence(investigation)` — the numbered list, built from the
  investigation record alone. Nothing else reaches the narrator.
- `check(investigation, prose)` — whether the prose stays inside its
  input. The worker runs it before writing a narration and the API runs it
  again before serving one, as Phase 34 re-judges a verification, so a row
  put into the table by any other route is not served as prose.
- `segments(investigation, prose)` — the prose as it is shown: each
  citation replaced by its item's own text, taken from the record, never
  from the model.

**What the check holds.** A narration passes only when every citation
names an item in the list; when the prose outside citations names no
subject, reading id, probe id, capability, component or code-form verdict
that is absent from the investigation; and when it contains no URL. Each of
those is one function in `RULES`, so a test can disable each and watch the
fixture turn red (standing invariant 10).

**What the check cannot hold.** It holds identifiers, not meaning. Prose
can still describe cited evidence wrongly in plain words, and a component
named as a plain word ("payments") is not distinguishable from English.
That is why the evidence is shown beside the prose, the prose is labelled
as derived, and docs/LIMITS.md says so.

Deterministic and dependency-free (`.claude/rules/determinism.md`): this
module is the check *on* a model, and imports none.
"""

import re
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from culprit_model.capabilities import Capability
from culprit_model.investigations import Investigation, Relation
from culprit_model.redaction import redact_credentials
from culprit_model.subjects import SubjectError, SubjectKind
from culprit_model.subjects import parse as parse_subject

#: The longest prose a narration may hold. A reply longer than this is a
#: failure of the attempt, not prose to check.
MAX_PROSE = 4000


@dataclass(frozen=True)
class EvidenceItem:
    number: int
    text: str


def _readings_text(ids: tuple[str, ...]) -> str:
    return ", ".join(ids) if ids else "no reading"


def evidence(investigation: Investigation) -> list[EvidenceItem]:
    """The numbered evidence the narrator is given, from the record alone.

    In a fixed order: the symptom and how it is attested, the diagnosis
    (its statement, root, remediation and rubric), every fault edge with
    the readings that established it, every reading, and every hypothesis.
    The text is the record's own words and identifiers; nothing is
    summarised, ranked or inferred here.
    """
    texts: list[str] = []
    symptom = investigation.symptom
    attested = (
        f"reproduced by reading {symptom.attestation.reading}"
        if symptom.attestation.reading
        else f"reported by {symptom.attestation.reported_by}"
    )
    texts.append(
        f"Symptom: {symptom.subject}"
        + (f" — {symptom.description}" if symptom.description else "")
        + f" ({attested}) in environment {investigation.environment}."
    )
    diagnosis = investigation.diagnosis
    if diagnosis is None:
        texts.append("Diagnosis: none was reached.")
    else:
        texts.append(
            f"Diagnosis ({'complete' if diagnosis.complete else 'partial'}): "
            f"{diagnosis.statement} Root: {diagnosis.root_subject}."
        )
        if diagnosis.remediation:
            texts.append(f"Recommended change: {diagnosis.remediation}")
        rubric = diagnosis.confidence
        for name in ("reproduced", "discriminated", "counterfactual", "verified"):
            criterion = getattr(rubric, name)
            texts.append(
                f"Confidence, {name}: {'holds' if criterion.holds else 'does not hold'} — "
                f"{criterion.reason}"
            )
    for edge in investigation.fault_tree:
        relation = {
            Relation.SYMPTOM_OF: "is a symptom of",
            Relation.PROPAGATES_TO: "propagates to",
            Relation.CAUSED_BY: "is caused by",
        }[edge.relation]
        texts.append(
            f"{edge.from_subject} {relation} {edge.to_subject}, established by "
            f"{_readings_text(edge.established_by)}."
        )
    for held in investigation.readings:
        reading = held.reading
        texts.append(
            f"Reading {held.id}: {reading.probe_id} on {reading.target} — "
            f"{reading.verdict.value}" + (f": {reading.reason}" if reading.reason else ".")
        )
    for hypothesis in investigation.hypotheses:
        status = "untested" if hypothesis.status.value == "open" else hypothesis.status.value
        texts.append(
            f"Hypothesis {hypothesis.id} ({hypothesis.kind}) on {hypothesis.subject}: "
            f"{status.replace('_', ' ')}"
            + (f", by {_readings_text(hypothesis.readings)}" if hypothesis.readings else "")
            + (f" — {hypothesis.reason}" if hypothesis.reason else ".")
        )
    return [EvidenceItem(number=index, text=text) for index, text in enumerate(texts, start=1)]


# ---- the check -------------------------------------------------------------

_CITATION = re.compile(r"\[(\d{1,4})\]")
#: Any scheme://, a protocol-relative //host, www., a data: URI, or a
#: dotted host with a path and no scheme (`evil.example/collect?d=...`) —
#: what a link or an image would need to carry data out.
_URL = re.compile(
    r"\b[a-z][a-z0-9+.-]*://\S*|(?<![\w/])//[a-z0-9-]+\.\S*|\bwww\.\S+|\bdata:[a-z]+/\S*"
    r"|\b[a-z0-9-]+(?:\.[a-z0-9-]+)+(?::\d+)?[/?\\]\S*"
    r"|\b[a-z0-9-]+(?:\.[a-z0-9-]+)+:\d+\b|\bmailto:\S+",
    re.IGNORECASE,
)
#: An identifier-shaped run: what a subject, a probe id, a reading id or a
#: code-form verdict looks like in text. Ends on a letter or digit, so a
#: sentence's full stop is not part of it.
_TOKEN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.:/>@\-]*[A-Za-z0-9])?")
_BACKTICKED = re.compile(r"`([^`\n]{1,200})`")
_SUBJECT_PREFIX = re.compile(
    r"^(?:" + "|".join(kind.value for kind in SubjectKind) + r"):", re.IGNORECASE
)
_READING_ID = re.compile(r"^[a-z]{1,3}\d+$", re.IGNORECASE)
#: What may be stored and shown as "what it named": one identifier-shaped
#: token, never a phrase — so a refusal cannot carry the model's sentence
#: to the page.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,39}$")
_MAX_NAMED = 80
_CAPABILITIES = frozenset(capability.value for capability in Capability)
#: Words that, as part of a hyphenated name, make it a component's name:
#: `inventory-service`, `orders-db`. A component named as one plain word is
#: not distinguishable from English (module docstring).
_COMPONENT_WORDS = frozenset(
    {
        "service", "svc", "api", "db", "database", "gateway", "worker", "server",
        "proxy", "cache", "queue", "broker", "store", "app", "web", "backend", "frontend",
    }
)  # fmt: skip


@dataclass(frozen=True)
class Context:
    """What the investigation names, for the rules to compare against."""

    items: int
    subjects: tuple[str, ...]
    tokens: frozenset[str]


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _strings(item)


def _is_subject(text: str) -> bool:
    try:
        parse_subject(text)
    except SubjectError:
        return False
    return True


def context(investigation: Investigation) -> Context:
    record = investigation.model_dump(mode="json")
    subjects = {investigation.symptom.subject}
    subjects.update(h.subject for h in investigation.hypotheses)
    subjects.update(held.reading.target for held in investigation.readings)
    for edge in investigation.fault_tree:
        subjects.update((edge.from_subject, edge.to_subject))
    if investigation.diagnosis is not None:
        subjects.add(investigation.diagnosis.root_subject)
    tokens: set[str] = set()
    for text in _strings(record):
        for token in _TOKEN.findall(text):
            if _SUBJECT_PREFIX.match(token):
                # A subject is known only whole (`_masked`): a token cut
                # from one, `http:a/POST` out of `http:a/POST /orders`, is
                # not. One named whole in free text — a reason — is.
                if _is_subject(token):
                    subjects.add(token)
                continue
            tokens.add(token.lower())
    return Context(
        items=len(evidence(investigation)),
        # Longest first, so a subject that is a prefix of another is masked
        # after it.
        subjects=tuple(sorted(subjects, key=len, reverse=True)),
        tokens=frozenset(tokens),
    )


_IDENTIFIER = r"A-Za-z0-9_\-/>:@"


def _masked(prose: str, ctx: Context) -> str:
    """The prose outside citations, with every subject the investigation
    holds masked out whole — so a subject is accepted only as written in
    the record, never as a prefix of one (`http:a/POST /orders` does not
    let `http:a/POST /anything` through)."""
    text = _CITATION.sub(" ", prose)
    for subject in ctx.subjects:
        pattern = (
            rf"(?<![{_IDENTIFIER}.]){re.escape(subject)}"
            rf"(?![{_IDENTIFIER}])(?!\.[A-Za-z0-9])"
        )
        text = re.sub(pattern, " ", text)
    return text


def _unknown_tokens(prose: str, ctx: Context) -> Iterator[str]:
    for token in _TOKEN.findall(_masked(prose, ctx)):
        if token.lower() not in ctx.tokens:
            yield token


Rule = Callable[[str, Context], list[str]]


#: Characters that render as nothing but are not format characters: the
#: Hangul and halfwidth fillers and the blank Braille pattern.
_BLANKS = frozenset("\u115f\u1160\u3164\uffa0\u2800")


def no_invisible_characters(prose: str, ctx: Context) -> list[str]:
    """No zero-width or other format character: one can split a name the
    other rules would see (`not` + U+200B + `_resolved`), or reorder what is shown."""
    return [
        "an invisible character"
        for ch in prose
        if unicodedata.category(ch) in ("Cf", "Mn", "Me") or ch in _BLANKS
    ][:1]


def citations_name_items(prose: str, ctx: Context) -> list[str]:
    """Every citation names an item in the list."""
    return [
        f"[{number}]" for number in _CITATION.findall(prose) if not 1 <= int(number) <= ctx.items
    ]


def no_url(prose: str, ctx: Context) -> list[str]:
    """No URL, anywhere — a link or an image is a way out for data."""
    return ["a URL" for _ in _URL.findall(prose)]


def subjects_are_the_investigations(prose: str, ctx: Context) -> list[str]:
    return [t for t in _unknown_tokens(prose, ctx) if _SUBJECT_PREFIX.match(t)]


def probes_are_the_investigations(prose: str, ctx: Context) -> list[str]:
    return [t for t in _unknown_tokens(prose, ctx) if t.lower().startswith("probe.")]


def capabilities_are_the_investigations(prose: str, ctx: Context) -> list[str]:
    return [t for t in _unknown_tokens(prose, ctx) if t.lower() in _CAPABILITIES]


def reading_ids_are_the_investigations(prose: str, ctx: Context) -> list[str]:
    return [t for t in _unknown_tokens(prose, ctx) if _READING_ID.match(t)]


def code_forms_are_the_investigations(prose: str, ctx: Context) -> list[str]:
    """A code-form verdict (`not_resolved`, `breaks_request_path`) or any
    other identifier written with an underscore."""
    return [
        t
        for t in _unknown_tokens(prose, ctx)
        if "_" in t and not _SUBJECT_PREFIX.match(t) and not t.lower().startswith("probe.")
    ]


def components_are_the_investigations(prose: str, ctx: Context) -> list[str]:
    """A component's name: written in code form (backticks), or hyphenated
    with a component word or a digit (`inventory-service`, `db-2`)."""
    named: list[str] = []
    for span in _BACKTICKED.findall(_CITATION.sub(" ", prose)):
        unknown = [t for t in _TOKEN.findall(_masked(span, ctx)) if t.lower() not in ctx.tokens]
        if unknown:
            # The first unknown name, never the span: a span can hold a
            # sentence, and what was named is stored and shown.
            first = unknown[0]
            named.append(f"`{first}`" if _SAFE_NAME.match(first) else "a name in code form")
    for token in _unknown_tokens(prose, ctx):
        if "-" not in token or "_" in token or ":" in token or "." in token:
            continue
        parts = token.lower().split("-")
        if any(part in _COMPONENT_WORDS or any(ch.isdigit() for ch in part) for part in parts):
            named.append(token)
    return named


#: Every rule a narration must pass. A test removes each in turn and shows
#: the fixture turning red without it.
RULES: tuple[Rule, ...] = (
    citations_name_items,
    no_url,
    no_invisible_characters,
    subjects_are_the_investigations,
    probes_are_the_investigations,
    capabilities_are_the_investigations,
    reading_ids_are_the_investigations,
    code_forms_are_the_investigations,
    components_are_the_investigations,
)


def _shown(name: str) -> str:
    """What was named, made safe to store and show: never a URL, never a
    credential, never longer than _MAX_NAMED characters."""
    if _URL.search(name):
        return "a URL"
    name = redact_credentials(name)
    return name if len(name) <= _MAX_NAMED else name[: _MAX_NAMED - 1] + "…"


@dataclass(frozen=True)
class Check:
    passed: bool
    #: What the prose named that the investigation does not hold, in the
    #: order found, each once.
    named: tuple[str, ...]


def check(investigation: Investigation, prose: str, rules: tuple[Rule, ...] = RULES) -> Check:
    """Whether `prose` stays inside `investigation`. Pure: the same prose
    and investigation always give the same answer."""
    ctx = context(investigation)
    named: list[str] = []
    for rule in rules:
        for found in rule(prose, ctx):
            name = _shown(found)
            if name not in named:
                named.append(name)
    if not prose.strip():
        named.append("no prose")
    return Check(passed=not named, named=tuple(named))


@dataclass(frozen=True)
class Segment:
    """One run of the prose as shown: plain text, or a citation replaced by
    its evidence item's own text."""

    text: str
    evidence: int | None = None


def segments(investigation: Investigation, prose: str) -> list[Segment]:
    """The prose split at its citations, each citation carrying its item's
    text from the record. Call only on prose that passed `check`."""
    items = {item.number: item.text for item in evidence(investigation)}
    out: list[Segment] = []
    position = 0
    for match in _CITATION.finditer(prose):
        if match.start() > position:
            out.append(Segment(text=prose[position : match.start()]))
        number = int(match.group(1))
        out.append(Segment(text=items[number], evidence=number))
        position = match.end()
    if position < len(prose):
        out.append(Segment(text=prose[position:]))
    return out
