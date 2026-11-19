#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""Holds what the README says to what the repository holds (docs/DELIVERY_PLAN.md
S4; Phase 40 part 2, decision 4). Standard library only.

Without arguments, the checks a checkout can answer, run in `lint`:

  links    every relative link and image in README.md and docs/*.md resolves
           to a file or directory in this tree (fenced code is skipped; an
           external URL or a bare #anchor is not a relative link);
  probes   every probe count README.md and docs/GUIDE.md state ("18 read-only
           probes", "all eighteen probes") equals the catalogue's,
           api/app/readings/catalogue.json, which the binary generates;
  length   README.md is under 300 lines (S3: the overview; depth lives in
           docs/GUIDE.md);
  colours  every colour in a Mermaid block of README.md and docs/GUIDE.md is
           a token's value in frontend/src/index.css, so the diagrams wear
           the dashboard's identity and type no colour of their own.

With `--self-check FILE`, also the figures `culprit check` produced on this
repository, where they are produced: the self-check job writes the human
output of `culprit check --unverifiable` to FILE and hands it here. Every
figure README.md or docs/GUIDE.md quotes (facts, subjects, gaps, the
unverifiable surface) must equal it.

    python3 scripts/check_readme.py
    python3 scripts/check_readme.py --self-check self-check.txt

Exit codes: 0 every check passed · 1 a check failed · 2 could not run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
GUIDE = ROOT / "docs" / "GUIDE.md"
CATALOGUE = ROOT / "api" / "app" / "readings" / "catalogue.json"
INDEX_CSS = ROOT / "frontend" / "src" / "index.css"

#: S3: the README is the overview, under this many lines.
MAX_README_LINES = 300

#: The documents the probe count, the diagrams' colours and the self-check's
#: figures are checked in: the README and the guide its tutorial moved to.
QUOTING = (README, GUIDE)

FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"(`+)[^`]*?\1")
#: [text](target) and ![alt](target); the target ends at whitespace or ")".
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
#: src="..", href="..", srcset=".." in the README's inline HTML.
HTML_LINK = re.compile(r"\b(?:src|href|srcset)=\"([^\"]+)\"")
#: [label]: target reference definitions.
REFERENCE = re.compile(r"^\s*\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)")
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", re.I)

_WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty"
)
NUMBER_WORDS = {word: value for value, word in enumerate(_WORDS.split())}
#: "18 read-only probes", "Thirteen read-only probes", "all seventeen probes".
PROBE_COUNT = re.compile(
    r"\b(\d+|" + "|".join(NUMBER_WORDS) + r")\s+(?:read-only\s+)?probes\b", re.I
)

HEX = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")

#: What `culprit check --unverifiable` prints, and how the documents quote it.
#: Each: the figure's name, the pattern in the self-check's output, the
#: pattern in a document. A document need not quote every figure; every one
#: it does quote must match.
FIGURES: tuple[tuple[str, re.Pattern[str], re.Pattern[str]], ...] = (
    (
        "facts",
        re.compile(r"(\d+) fact\(s\) compared across \d+ subject\(s\)"),
        re.compile(r"\b([\d,]+)\s+facts\s+across\s+[\d,]+\s+subjects\b"),
    ),
    (
        "subjects",
        re.compile(r"\d+ fact\(s\) compared across (\d+) subject\(s\)"),
        re.compile(r"\b[\d,]+\s+facts\s+across\s+([\d,]+)\s+subjects\b"),
    ),
    (
        "gaps",
        re.compile(r"^Not checked \((\d+)\)", re.M),
        re.compile(r"\b([\d,]+)\s+gaps\s+listed\b"),
    ),
    (
        "unverifiable",
        re.compile(r"^Unverifiable surface \((\d+)\)", re.M),
        re.compile(r"\b([\d,]+)\s+subjects\s+only\s+one\s+source\s+describes\b"),
    ),
)


def _prose_lines(text: str) -> list[tuple[int, str]]:
    """Lines outside fenced code, numbered from 1."""
    out: list[tuple[int, str]] = []
    fenced = False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            # Inline code is quoted text, not a link: `<img src="x">`.
            out.append((number, INLINE_CODE.sub("", line)))
    return out


def _mermaid_blocks(text: str) -> list[tuple[int, str]]:
    """Lines inside ```mermaid fences, numbered from 1."""
    out: list[tuple[int, str]] = []
    inside = False
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not inside and stripped.startswith("```mermaid"):
            inside = True
            continue
        if inside and stripped.startswith("```"):
            inside = False
            continue
        if inside:
            out.append((number, line))
    return out


def _targets(line: str) -> list[str]:
    targets = MARKDOWN_LINK.findall(line) + REFERENCE.findall(line)
    for value in HTML_LINK.findall(line):
        # srcset is "url 1x, url 2x"; src and href are one URL.
        targets += [part.strip().split()[0] for part in value.split(",") if part.strip()]
    return targets


def check_links(paths: list[Path], root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    for path in paths:
        for number, line in _prose_lines(path.read_text(encoding="utf-8")):
            for target in _targets(line):
                if EXTERNAL.match(target):
                    continue
                relative = unquote(target.split("#", 1)[0].split("?", 1)[0])
                if not relative:
                    continue
                resolved = (path.parent / relative).resolve()
                if not resolved.exists():
                    where = path.relative_to(root).as_posix()
                    failures.append(f"{where}:{number}: link to {target} does not resolve")
    return failures


def check_length(readme: Path = README, limit: int = MAX_README_LINES) -> list[str]:
    lines = len(readme.read_text(encoding="utf-8").splitlines())
    if lines >= limit:
        return [
            f"README.md is {lines} lines; S3 keeps it under {limit} (depth goes in docs/GUIDE.md)"
        ]
    return []


def catalogue_count(catalogue: Path = CATALOGUE) -> int:
    document = json.loads(catalogue.read_text(encoding="utf-8"))
    probes = document["probes"] if isinstance(document, dict) else document
    return len(probes)


def _prose(text: str) -> tuple[str, list[int]]:
    """The prose outside fenced code as one string, so a phrase that wraps
    across lines is still read, and each of its lines' starting offsets."""
    starts: list[int] = []
    parts: list[str] = []
    offset = 0
    for _number, line in _prose_lines(text):
        starts.append(offset)
        parts.append(line)
        offset += len(line) + 1
    return "\n".join(parts), starts


def _line_at(text: str, offset: int) -> int:
    """The source line number of an offset into _prose(text)'s string."""
    numbers = [number for number, _line in _prose_lines(text)]
    _joined, starts = _prose(text)
    index = max(i for i, start in enumerate(starts) if start <= offset) if starts else 0
    return numbers[index] if numbers else 0


def check_probe_count(paths: list[Path], count: int, root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        prose, _starts = _prose(text)
        for match in PROBE_COUNT.finditer(prose):
            said = match.group(1)
            value = int(said) if said.isdigit() else NUMBER_WORDS[said.lower()]
            if value != count:
                where = f"{path.relative_to(root).as_posix()}:{_line_at(text, match.start())}"
                failures.append(f"{where}: says {said} probes; the catalogue holds {count}")
    return failures


def token_colours(index_css: Path = INDEX_CSS) -> set[str]:
    css = index_css.read_text(encoding="utf-8")
    block = re.search(r":root\s*\{(.*?)\n\}", css, re.S)
    if block is None:
        raise ValueError("frontend/src/index.css has no :root block")
    body = re.sub(r"/\*.*?\*/", "", block.group(1), flags=re.S)
    return {value.lower() for value in HEX.findall(body)}


def check_diagram_colours(paths: list[Path], tokens: set[str], root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    for path in paths:
        for number, line in _mermaid_blocks(path.read_text(encoding="utf-8")):
            for colour in HEX.findall(line):
                if colour.lower() not in tokens:
                    where = path.relative_to(root).as_posix()
                    failures.append(
                        f"{where}:{number}: diagram colour {colour} is not a token in "
                        "frontend/src/index.css"
                    )
    return failures


def self_check_figures(output: str) -> dict[str, int]:
    figures: dict[str, int] = {}
    for name, produced, _quoted in FIGURES:
        match = produced.search(output)
        if match:
            figures[name] = int(match.group(1))
    return figures


def check_figures(paths: list[Path], output: str, root: Path = ROOT) -> list[str]:
    figures = self_check_figures(output)
    missing = [name for name, _produced, _quoted in FIGURES if name not in figures]
    if missing:
        raise ValueError(
            "the self-check output holds no "
            + ", ".join(missing)
            + ": was it `culprit check --unverifiable`, in text?"
        )
    failures: list[str] = []
    quoted_any = False
    for path in paths:
        text = path.read_text(encoding="utf-8")
        prose, _starts = _prose(text)
        for name, _produced, quoted in FIGURES:
            for match in quoted.finditer(prose):
                quoted_any = True
                said = match.group(1)
                if int(said.replace(",", "")) != figures[name]:
                    where = f"{path.relative_to(root).as_posix()}:{_line_at(text, match.start())}"
                    failures.append(
                        f"{where}: quotes {said} {name}; the self-check produced {figures[name]}"
                    )
    if not quoted_any:
        failures.append("neither README.md nor docs/GUIDE.md quotes a self-check figure")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--self-check",
        type=Path,
        metavar="FILE",
        help="the text output of `culprit check --unverifiable` on this repository",
    )
    args = parser.parse_args(argv)
    try:
        documents = [README, *sorted((ROOT / "docs").glob("*.md"))]
        quoting = [path for path in QUOTING if path.exists()]
        failures = check_links(documents)
        failures += check_length()
        failures += check_probe_count(quoting, catalogue_count())
        failures += check_diagram_colours(quoting, token_colours())
        if args.self_check is not None:
            output = args.self_check.read_text(encoding="utf-8")
            failures += check_figures(quoting, output)
    except (OSError, ValueError, KeyError) as error:
        print(f"check_readme: could not run: {error}", file=sys.stderr)
        return 2
    for failure in failures:
        print(failure, file=sys.stderr)
    if failures:
        print(
            f"\ncheck_readme: {len(failures)} statement(s) not true of this tree", file=sys.stderr
        )
        return 1
    checked = "links, length, probe counts, diagram colours"
    if args.self_check is not None:
        checked += ", self-check figures"
    print(f"check_readme: {len(documents)} document(s); {checked}: true.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
