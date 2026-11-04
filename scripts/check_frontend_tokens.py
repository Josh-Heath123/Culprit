#!/usr/bin/env python3
"""Fails if a page component styles itself with anything but the design
tokens (DIAGNOSTIC_PLAN.md Phase 32.1, field 13).

Every colour lives once, in frontend/src/index.css's :root, where
scripts/tests/test_design_tokens.py measures its contrast. A page that
writes `#3b82f6`, `text-blue-500`, `bg-[#111]`, `text-[11px]`,
`text-fg/70` or `style={{ color: ... }}` has stepped outside both: its
colour was never measured, and the next change to the palette will not
reach it. So this refuses, in the files in scope:

- raw colour literals: hex, rgb()/rgba(), hsl(), oklch(), color-mix();
- Tailwind's built-in palette (`slate-500`, `blue-400`, `black`, `white`);
- arbitrary values and properties (`w-[13px]`, `[mask:...]`);
- opacity modifiers on a colour (`text-fg-muted/70`, `text-fg/[0.7]`), which make a
  colour no token declares;
- Tailwind v4's CSS-variable shorthand (`bg-(--x)`);
- any inline `style=` and any colour prop (`color=`, `fill=`, `stroke=`).

**Scope.** All of frontend/src since Phase 32.1 part 2 (part 1 covered
the investigation screens only), every .tsx and .ts file, components/ui
included. A path in SCOPE that does not exist is an
error, not a skip — a gate whose files moved away is green for nothing.

Exit codes: 0 clean, 1 a violation, 2 could not run.

Run with `just check-frontend-tokens`; CI runs it beside the other checks.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Files and directories the gate reads, relative to the repository.
SCOPE: tuple[str, ...] = ("frontend/src",)

#: Files in SCOPE the gate does not read, each with its reason. The bar is
#: the one scripts/check_scan_coverage.py sets for its own exclusions: an
#: exclusion nobody wrote a reason for is indistinguishable from an
#: oversight.
EXCLUDED: dict[str, str] = {
    "frontend/src/index.css": "the one place colours are declared; its contrast is measured by "
    "scripts/tests/test_design_tokens.py",
    "frontend/src/lib/api-types.generated.ts": "generated from the API's OpenAPI schema, never "
    "hand-edited, and holds no styling",
}

_PALETTE = (
    "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|"
    "blue|indigo|violet|purple|fuchsia|pink|rose"
)
_COLOUR_UTILITIES = (
    "bg|text|border|border-[trblxyse]|ring|ring-offset|outline|fill|stroke|from|via|to|"
    "decoration|shadow|accent|caret|divide|placeholder"
)

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("raw hex colour", re.compile(r"#[0-9a-fA-F]{3,8}\b")),
    ("raw colour function", re.compile(r"\b(?:rgba?|hsla?|oklch|oklab|lab|lch|color-mix)\(")),
    (
        "Tailwind palette colour",
        re.compile(
            rf"(?<![\w-])(?:{_COLOUR_UTILITIES})-(?:(?:{_PALETTE})-\d{{2,3}}|black|white)(?![\w-])"
        ),
    ),
    # Variants such as Radix's `data-[state=open]:` or `aria-[...]:` are
    # selectors, not values, and are allowed; what they select is still
    # checked (`data-[state=open]:bg-[#fff]` fails on the `bg-[`).
    (
        "arbitrary value",
        re.compile(
            r"(?<![\w\[])(?!(?:data|aria|supports|group|peer|has|not|in|nth)-\[)"
            r"[a-z][a-z0-9-]*-\[[^\]\s]+\]"
        ),
    ),
    ("arbitrary property", re.compile(r"(?<![\w&])\[[a-z-]+:[^\]\s]+\]")),
    # Tailwind v4's shorthand for an arbitrary CSS variable: `bg-(--x)`,
    # `text-(color:--x)` — a value no token declares.
    ("CSS variable shorthand", re.compile(r"(?<![\w-])[a-z][a-z0-9-]*-\((?:[a-z-]+:)?--[\w-]+\)")),
    (
        "colour opacity modifier",
        re.compile(
            rf"(?<![\w-])(?:{_COLOUR_UTILITIES})-[a-z][a-z0-9-]*/(?:\d{{1,3}}|\[[^\]]+\])(?![\w-])"
        ),
    ),
    # Any inline style at all: a style object can carry a colour through a
    # variable or nested braces that no pattern could follow, and nothing in
    # these screens needs one.
    ("inline style", re.compile(r"\bstyle=\{")),
    # A colour handed to an element or icon as a prop (`<XIcon color="red" />`).
    ("colour prop", re.compile(r"(?<![\w-])(?:color|fill|stroke|stopColor)=[\"'{]")),
)


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    rule: str
    text: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.text}"


def _files(root: Path, scope: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for entry in scope:
        path = root / entry
        if path.is_dir():
            found = sorted(
                p
                for p in path.rglob("*")
                if p.is_file()
                and p.suffix in {".tsx", ".ts"}
                and p.relative_to(root).as_posix() not in EXCLUDED
            )
            if not found:
                raise FileNotFoundError(f"{entry} is in SCOPE and holds no .tsx or .ts file")
            files.extend(found)
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(f"{entry} is in SCOPE and does not exist")
    return files


#: Phase 32.1 review: one date format everywhere,
#: from one formatter. A locale-dependent toLocale*String is how "4/11"
#: ended up meaning two different days.
DATE_FORMATTER = "frontend/src/lib/datetime.ts"
LOCALE_FORMATTING = re.compile(r"\.toLocale(?:Date|Time)?String\(|\bIntl\.DateTimeFormat\b")


def check_file(path: Path) -> list[Violation]:
    source = path.read_text(encoding="utf-8")
    found: list[Violation] = []
    if not path.as_posix().endswith(DATE_FORMATTER):
        for match in LOCALE_FORMATTING.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            rule = "locale formatting outside lib/datetime.ts"
            found.append(Violation(path, line, rule, match.group(0)))
    for rule, pattern in RULES:
        for match in pattern.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            found.append(Violation(path, line, rule, match.group(0)))
    return sorted(found, key=lambda v: (v.line, v.rule))


def check(root: Path = ROOT, scope: tuple[str, ...] = SCOPE) -> list[Violation]:
    violations: list[Violation] = []
    for path in _files(root, scope):
        violations.extend(check_file(path))
    return violations


def main(argv: list[str] | None = None) -> int:
    del argv
    try:
        files = _files(ROOT, SCOPE)
        violations = check()
    except (FileNotFoundError, OSError, UnicodeDecodeError) as error:
        print(f"check_frontend_tokens: could not run: {error}", file=sys.stderr)
        return 2
    for violation in violations:
        print(violation.__str__().replace(str(ROOT) + "\\", "").replace(str(ROOT) + "/", ""))
    if violations:
        print(
            f"\n{len(violations)} styling value(s) bypass the design tokens in "
            "frontend/src/index.css. "
            "Use a token utility (bg-surface-1, text-fg-muted, text-2xs, ...), or add a token "
            "there, where its contrast is measured.",
            file=sys.stderr,
        )
        return 1
    print(f"check_frontend_tokens: {len(files)} file(s), tokens only.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
