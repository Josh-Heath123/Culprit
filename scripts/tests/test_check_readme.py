"""scripts/check_readme.py (docs/DELIVERY_PLAN.md S4; Phase 40 part 2,
decision 4): the tree passes, and each check fails on the mutation it exists
for."""

from pathlib import Path

import check_readme as gate
import pytest

SELF_CHECK = """\
No divergences. 1753 fact(s) compared across 631 subject(s).

Not checked (9) — these are gaps, not clean results
  culprit-api        client_calls     does not extract client_calls

Unverifiable surface (535)
  Subjects only one source describes, so nothing could ever contradict them.
"""


def _doc(tmp_path: Path, text: str, name: str = "README.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_the_tree_passes() -> None:
    assert gate.main([]) == 0


def test_the_readme_quotes_the_catalogues_count_and_a_self_check_figure() -> None:
    """Without a quotation the checks would pass on nothing."""
    readme = gate.README.read_text(encoding="utf-8")
    assert gate.PROBE_COUNT.search(readme)
    assert any(quoted.search(readme) for _name, _produced, quoted in gate.FIGURES)


# --- links ----------------------------------------------------------------


def test_a_link_that_does_not_resolve_is_red(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "LIMITS.md").write_text("x", encoding="utf-8")
    doc = _doc(
        tmp_path,
        "[limits](docs/LIMITS.md) and [gone](docs/GONE.md#anchor)\n"
        '<img src="docs/missing.png" alt="">\n'
        '<source srcset="docs/LIMITS.md 1x, docs/nope.png 2x">\n'
        "[site](https://example.com) [here](#here) `[code](not/a/link.md)`\n"
        "```\n[fenced](not/a/link.md)\n```\n",
    )
    failures = gate.check_links([doc], root=tmp_path)
    assert [f.split(": ", 1)[1] for f in failures] == [
        "link to docs/GONE.md#anchor does not resolve",
        "link to docs/missing.png does not resolve",
        "link to docs/nope.png does not resolve",
    ]


def test_a_link_resolves_from_its_own_document(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    guide = _doc(tmp_path / "docs", "[back](../README.md) [wrong](README.md)\n", "GUIDE.md")
    failures = gate.check_links([guide], root=tmp_path)
    assert len(failures) == 1 and "link to README.md does not resolve" in failures[0]


# --- length ---------------------------------------------------------------


def test_a_readme_of_300_lines_is_red(tmp_path: Path) -> None:
    assert gate.check_length(_doc(tmp_path, "line\n" * 299)) == []
    assert gate.check_length(_doc(tmp_path, "line\n" * 300))


# --- probe count ----------------------------------------------------------


@pytest.mark.parametrize(
    "said",
    ["Thirteen read-only probes", "all seventeen probes", "17 probes", "19 read-only probes"],
)
def test_a_probe_count_the_catalogue_does_not_hold_is_red(tmp_path: Path, said: str) -> None:
    doc = _doc(tmp_path, f"It runs {said}, each read-only.\n")
    assert gate.check_probe_count([doc], 18, root=tmp_path)


@pytest.mark.parametrize("said", ["18 read-only probes", "all eighteen probes", "Eighteen probes"])
def test_the_catalogues_count_passes(tmp_path: Path, said: str) -> None:
    assert gate.check_probe_count([_doc(tmp_path, f"{said}.\n")], 18, root=tmp_path) == []


def test_the_catalogue_is_counted() -> None:
    assert gate.catalogue_count() >= 1


# --- diagram colours ------------------------------------------------------


def test_a_diagram_colour_that_is_no_token_is_red(tmp_path: Path) -> None:
    tokens = gate.token_colours()
    assert "#d6fa4a" in tokens
    doc = _doc(
        tmp_path,
        "Prose may say #123456.\n```mermaid\nflowchart TD\n"
        "  classDef answer fill:#d6fa4a,color:#221331\n"
        "  classDef wrong fill:#ffeb3b\n```\n",
    )
    failures = gate.check_diagram_colours([doc], tokens, root=tmp_path)
    assert len(failures) == 1 and "#ffeb3b" in failures[0]


# --- self-check figures ---------------------------------------------------


def test_the_self_checks_figures_are_read() -> None:
    assert gate.self_check_figures(SELF_CHECK) == {
        "facts": 1753,
        "subjects": 631,
        "gaps": 9,
        "unverifiable": 535,
    }


def test_a_figure_the_self_check_did_not_produce_is_red(tmp_path: Path) -> None:
    doc = _doc(
        tmp_path,
        "**no divergences, 1,753 facts across 631 subjects**, 9 gaps listed\n"
        "| `just self-check-coverage` | the 368 subjects only one source describes |\n",
    )
    failures = gate.check_figures([doc], SELF_CHECK, root=tmp_path)
    assert (
        len(failures) == 1 and "quotes 368 unverifiable; the self-check produced 535" in failures[0]
    )


def test_the_figures_the_self_check_produced_pass(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "1,753 facts across 631 subjects, 9 gaps listed\n")
    assert gate.check_figures([doc], SELF_CHECK, root=tmp_path) == []


def test_a_document_that_quotes_no_figure_is_red(tmp_path: Path) -> None:
    assert gate.check_figures([_doc(tmp_path, "nothing\n")], SELF_CHECK, root=tmp_path)


def test_output_that_is_not_the_self_check_cannot_run(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="holds no"):
        gate.check_figures([_doc(tmp_path, "x\n")], "Error: no culprit.yaml", root=tmp_path)
