"""The differential corpus (Q28, ruled 2026-11-12, PERFORMANCE_PLAN.md end of
Phase 37): the API's manifest loader and the binary's read one schema.

shared/tests/manifest_corpus.json crosses every field of its base manifest
with every YAML 1.2 scalar form, and adds structural variants and the
close-out phase-auditor's 85 manifests. For each case it records what the
API's loader makes of it: refused, or the hash of the typed document's
canonical JSON. This test holds the API to that record and
cli/internal/extract/corpus_test.go holds the binary to the same one, so on
every case the two give equal JSON or both refuse. Loosening either reader
changes its outcomes and turns its test red.

After a deliberate change to either reader:

    cd api && uv run python tests/test_manifest_corpus.py --write
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

CORPUS = Path(__file__).resolve().parents[2] / "shared" / "tests" / "manifest_corpus.json"


def corpus_cases(spec: dict) -> dict[str, str]:
    """Every case's id and text. A field case replaces one placeholder with
    the form and every other with its default."""
    cases: dict[str, str] = {}
    for field in spec["defaults"]:
        for form in spec["forms"]:
            text = spec["base"]
            for name, default in spec["defaults"].items():
                text = text.replace(f"<<{name}>>", form if name == field else default)
            cases[f"field {field} = {form}"] = text
    for name, text in spec["structural"].items():
        cases[f"structural {name}"] = text
    for name, text in spec["seeds"].items():
        cases[f"seed {name}"] = text
    return cases


def _string(text: str) -> str:
    out = ['"']
    for char in text:
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif ord(char) < 0x20:
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def canonical(value: object) -> str:
    """The corpus's canonical JSON; cli/internal/extract/corpus_test.go
    writes the same bytes."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _string("!!float " + repr(value))
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ",".join(canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(f"{_string(k)}:{canonical(value[k])}" for k in sorted(value)) + "}"
    raise TypeError(f"not plain data: {type(value).__name__}")


def outcome(text: str) -> str:
    from app.model.manifest import ManifestError, load_manifest, typed_document

    try:
        load_manifest(text)
    except ManifestError:
        return "refused"
    digest = hashlib.sha256(canonical(typed_document(text)).encode("utf-8")).hexdigest()
    return digest[:16]


def _spec() -> dict:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def test_the_corpus_covers_every_case_it_generates() -> None:
    """No case can be dropped from the record without this failing."""
    spec = _spec()
    assert sorted(spec["expect"]) == sorted(corpus_cases(spec))


def test_the_api_schema_is_the_shared_schema() -> None:
    """shared/tests/manifest_schema.json: one type per field, held equal to
    the Go loader's derivation by cli/internal/extract/corpus_test.go."""
    from app.model.manifest import manifest_schema

    shared = json.loads((CORPUS.parent / "manifest_schema.json").read_text(encoding="utf-8"))
    assert manifest_schema() == shared["fields"]


def test_every_schema_field_is_in_the_corpus() -> None:
    """Every field of the manifest is crossed with every form."""
    from app.model.manifest import manifest_schema

    assert sorted(_spec()["defaults"]) == sorted(manifest_schema())


def test_the_api_reads_every_corpus_case_as_recorded() -> None:
    spec = _spec()
    wrong = [
        f"{case}: recorded {spec['expect'][case]}, read {got}"
        for case, text in corpus_cases(spec).items()
        if (got := outcome(text)) != spec["expect"].get(case)
    ]
    assert wrong == [], f"{len(wrong)} case(s) differ, first: {wrong[:10]}"


def test_the_auditors_splits_are_in_the_corpus() -> None:
    """The close-out phase-auditor's 85 manifests are cases of their own."""
    assert len(_spec()["seeds"]) == 85


@pytest.mark.parametrize("name", sorted(_spec()["closeout_splits"]))
def test_each_auditor_split_is_read_as_recorded(name: str) -> None:
    """A2 (2026-11-13): each split the close-out phase-auditor found is a
    seed labelled with what each reader did at d37542e, and the API now
    gives the recorded outcome for it. Checked by label, not by a count."""
    spec = _spec()
    label = spec["closeout_splits"][name]
    assert label.startswith("at d37542e "), label
    assert outcome(spec["seeds"][name]) == spec["expect"][f"seed {name}"], label


if __name__ == "__main__" and "--write" in sys.argv:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    corpus = _spec()
    corpus["expect"] = {case: outcome(text) for case, text in corpus_cases(corpus).items()}
    CORPUS.write_bytes((json.dumps(corpus, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    refused = sum(1 for value in corpus["expect"].values() if value == "refused")
    print(f"{len(corpus['expect'])} cases, {refused} refused")
