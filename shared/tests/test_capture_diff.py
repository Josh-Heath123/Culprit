# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: Apache-2.0

"""The snapshot diff and never-render-a-value, held to Go (F44-064 a, b).

`cli/internal/verify/capture_diff_test.go` and
`cli/internal/report/render_test.go` read the same two files.
"""

import json
from pathlib import Path

import pytest
from culprit_model.capture_diff import StoredFact, diff_captures, render_value

HERE = Path(__file__).parent
DIFF = json.loads((HERE / "capture_diff_conformance.json").read_text(encoding="utf-8"))
RENDER = json.loads((HERE / "render_value_conformance.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", DIFF["cases"], ids=lambda c: c["name"])
def test_the_snapshot_diff_matches_the_shared_fixture(case: dict) -> None:
    a = [StoredFact.model_validate(fact) for fact in case["a"]]
    b = [StoredFact.model_validate(fact) for fact in case["b"]]
    got = [{"subject": e.subject, "predicate": e.predicate} for e in diff_captures(a, b)]
    assert got == case["differs"]


@pytest.mark.parametrize("case", RENDER["cases"], ids=lambda c: c["rendered"])
def test_a_value_renders_as_the_shared_fixture_says(case: dict) -> None:
    assert render_value(StoredFact.model_validate(case["fact"])) == case["rendered"]
