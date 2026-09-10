"""Diffing two stored CONFIGURED captures, and rendering a fact safely.

Phase 30 field 9: `GET /captures/diff?a=&b=`. Deterministic and pure —
no database, no clock, no LLM (`.claude/rules/determinism.md`); the API
reads the rows and hands them here.

**This is a snapshot diff, not the divergence engine.** The comparator
with confidence ranks, severity from the system model, suppressions and
absence judged against an enumerating source is the CLI's
(`cli/internal/diverge/`, D7), and it runs where the repository and its
INTENT are. What the control plane can honestly answer about two stored
captures is narrower: which (subject, predicate) answers differ, and
which exist in one and not the other. That is what this returns, and it
is labelled as such in the API so nobody mistakes one for the other.

Two rules it shares with the CLI, because a diff that disagreed with
`culprit diff` about the same two captures would be worse than none:

- **Shapes compare by `ValueShape.equivalent`**, the rule held by
  `shared/tests/shape_conformance.json` — length class only as
  empty-or-not, an unknown type on presence alone.
- **A config value is never rendered** (`render_value`), granted or not —
  the same rule as `renderValue` in `cli/internal/report/report.go`. This
  is the single serialiser every API response about a stored fact goes
  through; see `app/model/captures.py`.
"""

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from culprit_model.canonical import canonical_json
from culprit_model.shape import ValueScheme, ValueShape
from culprit_model.subjects import SubjectError, SubjectKind, parse


class StoredFact(BaseModel):
    """The four fields of a stored fact a diff and a rendering need."""

    model_config = ConfigDict(frozen=True)

    subject: str
    predicate: str
    value: Any = None
    value_shape: ValueShape | None = None


class DiffStatus(StrEnum):
    DIFFERS = "differs"
    ONLY_IN_A = "only_in_a"
    ONLY_IN_B = "only_in_b"


class DiffEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    subject: str
    predicate: str
    status: DiffStatus
    #: Rendered through `render_value` — a config key's shape, never its
    #: value. None when that side has no answer.
    a: str | None
    b: str | None


def _is_config(subject: str) -> bool:
    try:
        kind, _ = parse(subject)
    except SubjectError:
        # An unparseable subject is treated as a config one: the safe
        # direction for a renderer whose one job is not to print a value.
        return True
    return kind is SubjectKind.CONFIG


def render_value(fact: StoredFact) -> str:
    """A fact's value for a human or a response body — never a config value.

    Mirrors `renderValue` in `cli/internal/report/report.go` exactly.
    The config branch is decided by the *subject*, not by whether the fact
    happens to carry a shape: a granted literal is stored in `value`, and
    this function is the reason it is never returned by the API.
    """
    if fact.value_shape is not None:
        shape = fact.value_shape
        if not shape.present:
            return "absent"
        form = str(shape.format)
        if shape.scheme not in (None, ValueScheme.NOT_APPLICABLE):
            form += f"({shape.scheme})"
        return f"{shape.type}/{form}/{shape.length_class}"
    if _is_config(fact.subject):
        if isinstance(fact.value, bool):
            return "true" if fact.value else "false"
        if fact.value is None:
            return "(declared)"
        return "(a value, not shown)"
    if fact.value is None:
        return "(exists)"
    return canonical_json(fact.value)


def _same(left: StoredFact, right: StoredFact) -> bool:
    if (left.value_shape is None) != (right.value_shape is None):
        return False
    if (
        left.value_shape is not None
        and right.value_shape is not None
        and not left.value_shape.equivalent(right.value_shape)
    ):
        return False
    return canonical_json(left.value) == canonical_json(right.value)


def diff_captures(a: Iterable[StoredFact], b: Iterable[StoredFact]) -> list[DiffEntry]:
    """Every (subject, predicate) the two captures answer differently.

    Sorted by subject then predicate, so the same two captures always
    produce the same list. Where one capture holds two facts for one
    question — which a single capture should not — the first in sorted
    order is taken, deterministically.
    """

    def index(facts: Iterable[StoredFact]) -> dict[tuple[str, str], StoredFact]:
        indexed: dict[tuple[str, str], StoredFact] = {}
        for fact in sorted(facts, key=lambda f: (f.subject, f.predicate, canonical_json(f.value))):
            indexed.setdefault((fact.subject, fact.predicate), fact)
        return indexed

    left, right = index(a), index(b)
    entries: list[DiffEntry] = []
    for key in sorted(set(left) | set(right)):
        subject, predicate = key
        if key not in right:
            entries.append(DiffEntry(subject=subject, predicate=predicate,
                                     status=DiffStatus.ONLY_IN_A,
                                     a=render_value(left[key]), b=None))
        elif key not in left:
            entries.append(DiffEntry(subject=subject, predicate=predicate,
                                     status=DiffStatus.ONLY_IN_B,
                                     a=None, b=render_value(right[key])))
        elif not _same(left[key], right[key]):
            entries.append(DiffEntry(subject=subject, predicate=predicate,
                                     status=DiffStatus.DIFFERS,
                                     a=render_value(left[key]), b=render_value(right[key])))
    return entries
