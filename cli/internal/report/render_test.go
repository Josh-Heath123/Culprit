// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package report

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The Go half of shared/tests/render_value_conformance.json (F44-064 b).
// The Python half, capture_diff.render_value, is read by
// shared/tests/test_capture_diff.py.
func TestAValueRendersAsTheSharedFixtureSays(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "shared", "tests", "render_value_conformance.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Cases []struct {
			Fact struct {
				Subject    string            `json:"subject"`
				Predicate  string            `json:"predicate"`
				Value      any               `json:"value"`
				ValueShape *model.ValueShape `json:"value_shape"`
			} `json:"fact"`
			Rendered string `json:"rendered"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(raw, &fixture); err != nil {
		t.Fatal(err)
	}
	if len(fixture.Cases) == 0 {
		t.Fatal("the fixture has no cases")
	}
	for _, testCase := range fixture.Cases {
		fact := model.Fact{Subject: testCase.Fact.Subject, Predicate: testCase.Fact.Predicate,
			Value: testCase.Fact.Value, ValueShape: testCase.Fact.ValueShape}
		if got := renderValue(fact); got != testCase.Rendered {
			t.Errorf("%s %s: rendered %q, fixture says %q", fact.Subject, fact.Predicate, got, testCase.Rendered)
		}
	}
}
