"""The §2.7 capability set, held to the Go one by a shared fixture.

`cli/internal/capability/capability_test.go` reads the same file. A
capability the CLI grants and the API refuses — or, as before Phase 30's
invariant audit, one the API accepted as free text — is a permission
model that means two different things.
"""

import json
from pathlib import Path

import pytest
from culprit_model.capabilities import ALLOWLISTED, Capability
from culprit_model.protocol import Grant
from pydantic import ValidationError

FIXTURE = json.loads(
    (Path(__file__).parent / "capability_conformance.json").read_text(encoding="utf-8")
)


def test_the_set_matches_the_shared_fixture() -> None:
    assert {c["name"] for c in FIXTURE["capabilities"]} == {c.value for c in Capability}
    assert {c["name"] for c in FIXTURE["capabilities"] if c["allowlist"]} == {
        c.value for c in ALLOWLISTED
    }


def test_no_write_capability_exists() -> None:
    assert not [c for c in Capability if c.value.endswith(".write")]


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"capability": "db.schema.write", "used": True}, id="a write capability"),
        pytest.param({"capability": "config.read.name", "used": True}, id="a typo"),
        pytest.param(
            {"capability": "config.read.values", "used": True}, id="a blanket value grant"
        ),
        pytest.param(
            {"capability": "db.metadata.read", "allow": ["x"], "used": True},
            id="an allowlist on a capability that takes none",
        ),
    ],
)
def test_a_grant_outside_the_rules_is_refused(payload: dict) -> None:
    with pytest.raises(ValidationError):
        Grant(**payload)
