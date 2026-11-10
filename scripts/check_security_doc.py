"""Every "cannot" in docs/SECURITY.md names a test that exists (Phase 33 part 3).

The threat model says what each compromise cannot do. A "cannot" nobody
tests is a hope, so the file names, beside each one, the test that enforces
it, as `path::TestName`. This check fails if:

- a paragraph or list item says "cannot" (or "can't", "can not") and names
  no test;
- a named test's file does not exist, or does not define that test — a Go
  `func TestName(` or a Python `def test_name(` / `async def test_name(`.

Usage: python scripts/check_security_doc.py [path-to-SECURITY.md]
Deterministic, offline, and reads nothing but the document and the files it
names (.claude/rules/determinism.md).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "docs" / "SECURITY.md"

CANNOT = re.compile(r"\b(cannot|can't|can not)\b", re.IGNORECASE)
REFERENCE = re.compile(r"`([\w./-]+\.(?:go|py))::(\w+)`")


@dataclass(frozen=True)
class Problem:
    line: int
    message: str


def blocks(text: str) -> list[tuple[int, str]]:
    """Paragraphs and list items, each with the line it starts on. A list
    item runs until the next item, a blank line or a heading; fenced code is
    skipped."""
    found: list[tuple[int, str]] = []
    current: list[str] = []
    start = 0
    fenced = False

    def flush() -> None:
        if current:
            found.append((start, " ".join(current)))
            current.clear()

    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            fenced = not fenced
            continue
        if fenced:
            continue
        if not stripped or stripped.startswith("#"):
            flush()
            continue
        if re.match(r"^\s*[-*]\s+", line) or re.match(r"^\s*\d+\.\s+", line):
            flush()
        if not current:
            start = number
        current.append(stripped)
    flush()
    return found


def defines(path: Path, name: str) -> bool:
    source = path.read_text(encoding="utf-8")
    if path.suffix == ".go":
        return re.search(rf"^func {re.escape(name)}\(", source, re.MULTILINE) is not None
    return re.search(rf"^(async )?def {re.escape(name)}\(", source, re.MULTILINE) is not None


def check(document: Path, root: Path = ROOT) -> list[Problem]:
    problems: list[Problem] = []
    for line, block in blocks(document.read_text(encoding="utf-8")):
        references = REFERENCE.findall(block)
        if CANNOT.search(block) and not references:
            problems.append(Problem(line, f'says "cannot" and names no test: {block[:100]}…'))
        for relative, name in references:
            path = root / relative
            if not path.is_file():
                problems.append(
                    Problem(line, f"names {relative}::{name}, but {relative} does not exist")
                )
            elif not defines(path, name):
                problems.append(
                    Problem(line, f"names {relative}::{name}, but {relative} defines no {name}")
                )
    return problems


def main(argv: list[str]) -> int:
    document = Path(argv[1]) if len(argv) > 1 else DEFAULT
    problems = check(document)
    for problem in problems:
        print(f"{document.name}:{problem.line}: {problem.message}")
    if problems:
        print(f"\n{len(problems)} problem(s).")
        print(f'Every "cannot" in {document.name} must name a test that exists.')
        return 1
    count = len(REFERENCE.findall(document.read_text(encoding="utf-8")))
    print(f'check_security_doc: every "cannot" names a test; {count} reference(s), all found.')
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
