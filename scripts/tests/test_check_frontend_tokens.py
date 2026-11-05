"""Tests for scripts/check_frontend_tokens.py (Phase 32.1).

A gate that cannot fail is not a gate (standing invariant 10), so each
rule is shown red on a file that breaks it — and the real scope is shown
green, and shown red again by inserting a raw colour into a real screen.
"""

import shutil
from pathlib import Path

import check_frontend_tokens as gate
import pytest


def _page(tmp_path: Path, body: str) -> Path:
    page = tmp_path / "Page.tsx"
    page.write_text(f"export function Page() {{\n  return {body};\n}}\n", encoding="utf-8")
    return page


@pytest.mark.parametrize(
    ("body", "rule"),
    [
        ('<div className="text-fg" style={{ color: "red" }} />', "inline style"),
        ("<div style={{ backgroundColor: x }} />", "inline style"),
        ('<div style={{ outlineColor: "blue" }} />', "inline style"),
        ("<div style={styles} />", "inline style"),
        ('<div style={{ ...a, nested: { color: "red" } }} />', "inline style"),
        ('<XIcon color="red" />', "colour prop"),
        ("<path fill={accent} />", "colour prop"),
        ('<div className="bg-(--surface-0)" />', "CSS variable shorthand"),
        ('<div className="text-(color:--brand)" />', "CSS variable shorthand"),
        ('<div className="text-fg/[0.7]" />', "colour opacity modifier"),
        ('<div className="data-[state=open]:bg-[#fff]" />', "arbitrary value"),
        ('<div className="bg-[#0a0b0f]" />', "raw hex colour"),
        ('<div className="text-blue-500" />', "Tailwind palette colour"),
        ('<div className="border-slate-800" />', "Tailwind palette colour"),
        ('<div className="bg-white" />', "Tailwind palette colour"),
        ('<div className="text-[11px]" />', "arbitrary value"),
        ('<div className="w-[13px]" />', "arbitrary value"),
        ('<div className="[mask-type:luminance]" />', "arbitrary property"),
        ('<div className="text-fg-muted/70" />', "colour opacity modifier"),
        ('<div className="bg-brand/10" />', "colour opacity modifier"),
        ('const c = "rgba(0, 0, 0, 0.5)"', "raw colour function"),
        ('const c = "color-mix(in oklab, red, blue)"', "raw colour function"),
        ('const c = "#fff"', "raw hex colour"),
    ],
)
def test_each_rule_fails_on_what_it_names(tmp_path: Path, body: str, rule: str) -> None:
    violations = gate.check_file(_page(tmp_path, body))
    assert rule in {v.rule for v in violations}, violations


@pytest.mark.parametrize(
    "body",
    [
        '<div className="bg-surface-1 text-fg-muted border-line rounded-lg" />',
        '<div className="text-2xs text-pass bg-pass-tint ring-brand" />',
        '<div className="grid grid-cols-2 gap-3 sm:grid-cols-4 hover:bg-surface-2" />',
        '<div className="size-4 w-full max-w-3xl -translate-y-px" />',
        '<a href="#symptom">jump</a>',
        '<div className="data-[state=open]:animate-in aria-[expanded=true]:bg-surface-2" />',
        '<div className="fill-current" />',
    ],
)
def test_token_utilities_pass(tmp_path: Path, body: str) -> None:
    assert gate.check_file(_page(tmp_path, body)) == []


def test_the_scope_is_clean() -> None:
    assert gate.check() == []


def test_a_raw_colour_in_a_real_screen_turns_it_red(tmp_path: Path) -> None:
    """The mutation the acceptance criterion names: one deliberate raw
    colour in InvestigationView.tsx, and the gate fails on that line."""
    root = tmp_path / "repo"
    for entry in gate.SCOPE:
        source = gate.ROOT / entry
        target = root / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    view = root / "frontend/src/routes/InvestigationView.tsx"
    view.write_text(
        view.read_text(encoding="utf-8").replace('className="', 'className="text-rose-400 ', 1),
        encoding="utf-8",
    )
    violations = gate.check(root)
    assert [v.rule for v in violations] == ["Tailwind palette colour"]
    assert violations[0].path == view


def test_a_scope_entry_that_does_not_exist_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        gate.check(tmp_path, ("frontend/src/routes/Gone.tsx",))


def test_an_empty_scope_directory_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "frontend/src/components/gone").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        gate.check(tmp_path, ("frontend/src/components/gone",))


def test_the_scope_is_all_of_frontend_src() -> None:
    """Phase 32.1 part 2 widened the gate from the investigation screens to
    every page, components/ui included."""
    assert gate.SCOPE == ("frontend/src",)
    gitignore = (gate.ROOT / ".gitignore").read_text(encoding="utf-8")
    for excluded, reason in gate.EXCLUDED.items():
        # A generated file exists only after `just generate-types`, which a
        # fresh CI checkout running this test never does; it must then be
        # gitignored, so it can never be committed with styling in it.
        if excluded.endswith(".generated.ts"):
            assert excluded in gitignore, f"{excluded} is generated but not gitignored"
        else:
            assert (gate.ROOT / excluded).is_file(), (
                f"EXCLUDED names a file that does not exist: {excluded}"
            )
        assert len(reason) > 40, f"EXCLUDED[{excluded!r}] has no real reason"


def test_dates_are_formatted_in_one_place(tmp_path: Path) -> None:
    """Malcolm's review of part 1: one date format, from lib/datetime.ts.
    A page that calls toLocaleString() itself is refused; the formatter
    is the one file allowed to."""
    page = _page(tmp_path, "<span>{new Date(when).toLocaleString()}</span>")
    assert "locale formatting outside lib/datetime.ts" in {v.rule for v in gate.check_file(page)}
    formatter = tmp_path / "frontend" / "src" / "lib" / "datetime.ts"
    formatter.parent.mkdir(parents=True)
    formatter.write_text(
        "export const f = (d: Date) => d.toLocaleDateString();\n", encoding="utf-8"
    )
    assert gate.check_file(formatter) == []
