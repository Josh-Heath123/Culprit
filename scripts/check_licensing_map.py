# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""LICENSING.md's map and REUSE's agree, file by file (Phase 42, D8).

LICENSING.md says in a table which licence each path is under. REUSE
(`reuse lint --json`) says which licence each file carries, from its own
header or from REUSE.toml. This reads both and fails unless they agree:

- REUSE reports the project compliant;
- every file REUSE covers falls under a row of the table, and carries
  exactly that row's SPDX identifier (the most specific row wins: a file
  named outright before its directory, a directory before "everything
  else");
- every path the table names holds at least one file, so a row cannot go
  stale and still pass.

Standard library only. The REUSE report comes from a file or stdin:

    uvx --from 'reuse[charset-normalizer]==6.3.0' reuse lint --json \\
        | python3 scripts/check_licensing_map.py -

Exit 0 when they agree, 1 when they do not, 2 when either cannot be read.
"""

from __future__ import annotations

import fnmatch
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LICENSING = ROOT / "LICENSING.md"

#: The phrase in a row that means the files at the repository's root.
ROOT_FILES = "the files at the root"


@dataclass
class Row:
    patterns: list[str]
    spdx: str
    root_files: bool = False
    matched: dict[str, int] = field(default_factory=dict)

    def specificity(self, path: str) -> int:
        """How specifically this row names `path`: 0 when it does not."""
        best = 0
        for pattern in self.patterns:
            if pattern.endswith("/"):
                if fnmatch.fnmatchcase(path, pattern + "*"):
                    best = max(best, 1 + len(pattern))
            elif fnmatch.fnmatchcase(path, pattern):
                best = max(best, 1000 + len(pattern))
        if self.root_files and "/" not in path:
            best = max(best, 1)
        return best


def parse_licensing(text: str) -> list[Row]:
    """The table's rows: the backticked paths of each, and its SPDX identifier."""
    rows: list[Row] = []
    header_seen = False
    for line in text.splitlines():
        if not line.startswith("|"):
            if header_seen and rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0] == "Path":
            header_seen = True
            continue
        if not header_seen or set(line) <= set("|-: "):
            continue
        if len(cells) < 3:
            raise ValueError(f"a row of LICENSING.md's table has {len(cells)} cells: {line}")
        spdx = re.fullmatch(r"`([A-Za-z0-9.+-]+)`", cells[2])
        if not spdx:
            raise ValueError(f"a row of LICENSING.md's table names no SPDX identifier: {line}")
        patterns = re.findall(r"`([^`]+)`", cells[0])
        root = ROOT_FILES in cells[0]
        if not patterns and not root:
            raise ValueError(f"a row of LICENSING.md's table names no path: {line}")
        rows.append(Row(patterns=patterns, spdx=spdx.group(1), root_files=root))
    if not rows:
        raise ValueError("LICENSING.md has no licence table")
    return rows


def check(report: dict, rows: list[Row]) -> list[str]:
    problems: list[str] = []
    summary = report.get("summary", {})
    if not summary.get("compliant", False):
        missing = [
            item["path"]
            for item in report.get("files", [])
            if not item.get("spdx_expressions") or not item.get("copyrights")
        ]
        problems.append(
            "REUSE reports the project not compliant"
            + (
                f"; without copyright or licence: {', '.join(sorted(missing)[:20])}"
                if missing
                else ""
            )
        )
    files = report.get("files", [])
    if not files:
        problems.append("REUSE reported no files")
    for item in files:
        path = item["path"]
        ranked = sorted(
            ((row.specificity(path), index) for index, row in enumerate(rows)), reverse=True
        )
        if not ranked or ranked[0][0] == 0:
            problems.append(f"{path}: under no row of LICENSING.md's table")
            continue
        row = rows[ranked[0][1]]
        for pattern in row.patterns:
            if row.specificity(path) and (
                fnmatch.fnmatchcase(path, pattern + "*")
                if pattern.endswith("/")
                else fnmatch.fnmatchcase(path, pattern)
            ):
                row.matched[pattern] = row.matched.get(pattern, 0) + 1
        if row.root_files and "/" not in path:
            row.matched[ROOT_FILES] = row.matched.get(ROOT_FILES, 0) + 1
        carried = sorted({expr["value"] for expr in item.get("spdx_expressions", [])})
        if carried != [row.spdx]:
            says = " + ".join(carried) or "nothing"
            problems.append(f"{path}: REUSE says {says}, LICENSING.md says {row.spdx}")
    for row in rows:
        for pattern in row.patterns + ([ROOT_FILES] if row.root_files else []):
            if not row.matched.get(pattern):
                problems.append(
                    f"LICENSING.md names {pattern!r} ({row.spdx}), which holds no file REUSE covers"
                )
    return problems


def main(argv: list[str]) -> int:
    source = argv[1] if len(argv) > 1 else "-"
    try:
        raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
        report = json.loads(raw)
        rows = parse_licensing(LICENSING.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"check_licensing_map: {error}", file=sys.stderr)
        return 2
    problems = check(report, rows)
    for problem in problems:
        print(problem, file=sys.stderr)
    counts = {}
    for item in report.get("files", []):
        for expr in item.get("spdx_expressions", []):
            counts[expr["value"]] = counts.get(expr["value"], 0) + 1
    tally = ", ".join(f"{n} {spdx}" for spdx, n in sorted(counts.items()))
    print(
        f"check_licensing_map: {len(report.get('files', []))} files ({tally}); "
        f"{len(rows)} rows of LICENSING.md: {'agree' if not problems else 'DISAGREE'}."
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
