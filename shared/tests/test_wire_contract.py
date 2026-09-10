"""The Go binary's output is a valid Python `CaptureBundle`.

This is the contract that makes the whole architecture work, and until
now nothing asserted it. `culprit intent` is written in Go; the facts it
produces are read by `POST /facts/captures`, by Phase 29's comparator and
by everything after, all of which are Python. If the two sides disagree
about a field name, a date format or an enum spelling, the failure is a
422 in production or — worse — a field silently dropped.

Asserted against the **committed golden files**, which are real output
from the real binary over the real fixture corpus
(`cli/internal/extract/golden_test.go` regenerates them with
`just cli-golden-update`). That is deliberate: this test needs no Go
toolchain, so it runs in the `pytest (api)` CI job alongside everything
else, and it fails the moment a golden file is regenerated from a Go
struct that has drifted from the pydantic model.

The alternative — running the binary from a Python test — would make
this suite depend on a Go install and would test the build rather than
the contract.
"""

import json
from pathlib import Path

import pytest
from culprit_model.planes import Plane
from culprit_model.protocol import CaptureBundle
from culprit_model.shape import ValueScheme
from culprit_model.subjects import SubjectError, SubjectKind, parse

GOLDEN = (
    Path(__file__).resolve().parents[2] / "cli" / "testdata" / "fixtures" / "golden"
)


def _golden_files() -> list[Path]:
    return sorted(GOLDEN.rglob("*.json"))


def test_the_golden_directory_is_not_empty() -> None:
    """A parametrised test over an empty list passes vacuously.

    Without this, deleting the golden files would turn every assertion
    below into a green no-op — the same "gate that cannot fail" the
    scan-coverage invariant exists to catch, in miniature.
    """
    assert _golden_files(), (
        f"no golden files under {GOLDEN}. They are real `culprit intent` output "
        "and are what pins the Go/Python wire contract; regenerate with "
        "`just cli-golden-update`."
    )


@pytest.mark.parametrize("path", _golden_files(), ids=lambda p: p.stem)
def test_go_output_validates_as_a_capture_bundle(path: Path) -> None:
    """Every field the Go side emits is one the Python side understands."""
    bundle = CaptureBundle.model_validate_json(path.read_text(encoding="utf-8"))

    assert bundle.protocol == 1
    assert bundle.plane is Plane.INTENT
    # INTENT is environment-independent by definition (§0.2), and
    # `Fact`'s own validator refuses an environment on an INTENT fact —
    # so a Go side that started emitting one would fail here rather than
    # at the API boundary.
    assert bundle.environment is None
    assert bundle.extractor.startswith("culprit@")
    assert bundle.capture_id is not None


@pytest.mark.parametrize("path", _golden_files(), ids=lambda p: p.stem)
def test_no_golden_bundle_carries_a_config_value(path: Path) -> None:
    """Acceptance criterion 3, against real recorded output.

    `model_validate_json` above has already applied the rule — a bundle
    containing an ungranted config literal would not have parsed. This
    asserts the same thing from the other direction, over the parsed
    facts, so the guarantee is visible rather than implied by an absence
    of exceptions.
    """
    bundle = CaptureBundle.model_validate_json(path.read_text(encoding="utf-8"))
    for fact in bundle.facts:
        # `parse`, not a string prefix: inspecting a subject goes through
        # the same module that builds one, so a change to the scheme
        # cannot leave this test quietly matching nothing.
        try:
            kind, _ = parse(fact.subject)
        except SubjectError:  # pragma: no cover - a malformed golden file
            pytest.fail(f"{path.name}: {fact.subject!r} is not a valid subject URI")
        if kind is not SubjectKind.CONFIG:
            continue
        if fact.value is None or isinstance(fact.value, bool):
            continue
        pytest.fail(
            f"{path.name}: {fact.subject} carries a literal "
            f"{type(fact.value).__name__} with grant_ref={fact.grant_ref!r}"
        )


@pytest.mark.parametrize("path", _golden_files(), ids=lambda p: p.stem)
def test_every_value_shape_is_the_closed_five_field_form(path: Path) -> None:
    """The Go `ValueShape` marshals to exactly what the Python one accepts.

    Checked against the raw JSON rather than the parsed model: pydantic
    would already have rejected an extra key, so parsing alone cannot
    distinguish "the Go side emits four fields" from "the Go side emits
    three and pydantic filled a default in".
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    for fact in raw["facts"]:
        shape = fact.get("value_shape")
        if shape is None:
            continue
        # Phase 30 (Q7) added a fifth field, `scheme`. It is optional on the
        # wire — a protocol-1 extractor from before it existed omits it —
        # but the Go CLI's constructors always set it, so a Go-emitted
        # shape must carry exactly the five, with `scheme` from the closed
        # set. Stricter than the four-field version, not looser.
        assert set(shape) == {"type", "length_class", "format", "present", "scheme"}, (
            f"{path.name}: {fact['subject']} has a value_shape with keys "
            f"{sorted(shape)}"
        )
        assert shape["scheme"] in {member.value for member in ValueScheme}, (
            f"{path.name}: {fact['subject']} has a scheme outside the closed set"
        )
