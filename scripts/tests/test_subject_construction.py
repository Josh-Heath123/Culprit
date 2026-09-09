"""Field 7 of Phase 26: subject URIs are built in exactly one place.

`culprit_model.subjects.build()` is the only sanctioned constructor
(docs/DIAGNOSTIC_PLAN.md §2.3). "Direct string formatting of subjects
anywhere else is a lint failure from this phase forward" — this is that
lint.

Enforced by scanning source text for a string literal that begins with
one of the subject schemes followed by `:`, which is what a hand-rolled
`f"component:{name}"` looks like. It is a coarse check on purpose: the
precise version (an AST walk resolving every f-string's provenance)
would be far more code for a rule whose whole value is that it fires
early and obviously.

The point is not the string. Two sources describing the same route only
ever get compared if they produce byte-identical subjects, and a second
place that formats them is a second place that can disagree about
trailing slashes, case or parameter spelling — producing not an error
but a silent "no divergence found".
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent

SCHEMES = ("component", "connection", "http", "config", "schema", "dep", "image", "auth")

#: A string literal opening with `<scheme>:` — `"http:` or `f"component:`.
#: `(?!//)` excludes `"http://..."`, which is a URL and not a subject.
_SUBJECT_LITERAL = re.compile(rf"""f?["'](?:{"|".join(SCHEMES)}):(?!//)""")

#: Never scanned. `.venv` is thousands of third-party files that
#: naturally contain `"http:` and say nothing about this repo's own code.
_SKIPPED_PARTS = {"__pycache__", ".venv", "node_modules", "site-packages"}

#: Directories scanned. Deliberately not the whole repo: `frontend/`,
#: `docs/` and `demo-services/` have no business building subjects, and
#: scanning them would only produce false positives from URLs and prose.
SCANNED = ("api/app", "worker/app", "mcp_server", "scripts", "shared")

#: The implementation itself, and the fixture it is tested against.
ALLOWED = {
    "shared/culprit_model/subjects.py",
    "shared/tests/subject_conformance.json",
    "shared/tests/test_subjects.py",
    "scripts/tests/test_subject_construction.py",
}


def _python_files() -> list[Path]:
    files: list[Path] = []
    for directory in SCANNED:
        files.extend(
            path
            for path in (ROOT / directory).rglob("*.py")
            if _SKIPPED_PARTS.isdisjoint(path.parts)
        )
    return sorted(files)


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: p.name)
def test_no_module_hand_formats_a_subject_uri(path: Path) -> None:
    relative = path.relative_to(ROOT).as_posix()
    if relative in ALLOWED:
        pytest.skip("the sanctioned implementation")

    offending = [
        f"{relative}:{number}: {line.strip()}"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if _SUBJECT_LITERAL.search(line)
    ]
    assert not offending, (
        "build subject URIs with culprit_model.subjects.build(), not by string "
        "formatting — see docs/DIAGNOSTIC_PLAN.md §2.3:\n  " + "\n  ".join(offending)
    )


def test_the_scan_actually_matches_a_hand_rolled_subject() -> None:
    """A check that cannot fire is not a check."""
    assert _SUBJECT_LITERAL.search('subject = f"component:{name}"')
    assert _SUBJECT_LITERAL.search("subject = 'http:orders-svc/GET /orders'")
    assert not _SUBJECT_LITERAL.search('url = "http://localhost:8000"')
    assert not _SUBJECT_LITERAL.search('note = "the component: see above"')
