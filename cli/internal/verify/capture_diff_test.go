// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package verify

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The Go half of shared/tests/capture_diff_conformance.json (F44-064 a).
// The Python half, capture_diff.diff_captures, is read by
// shared/tests/test_capture_diff.py.

type diffFact struct {
	Subject    string            `json:"subject"`
	Predicate  string            `json:"predicate"`
	Value      any               `json:"value"`
	ValueShape *model.ValueShape `json:"value_shape"`
	Artefact   string            `json:"artefact"`
}

type diffKey struct {
	Subject   string `json:"subject"`
	Predicate string `json:"predicate"`
}

func bundleOf(id string, facts []diffFact) model.CaptureBundle {
	name := env
	bundle := model.CaptureBundle{Plane: model.PlaneConfigured, Environment: &name, CaptureID: id, StartedAt: clock}
	for _, fact := range facts {
		bundle.Facts = append(bundle.Facts, model.Fact{Plane: model.PlaneConfigured, Subject: fact.Subject,
			Predicate: fact.Predicate, Value: fact.Value, ValueShape: fact.ValueShape, Environment: env,
			Provenance: model.Provenance{SourceKind: model.SourceIntrospection, Extractor: "culprit@test",
				Artefact: fact.Artefact, ConfidenceRank: model.RankRuntimeIntrospection},
			CapturedAt: clock, CaptureID: id})
	}
	return bundle
}

func TestTheSnapshotDiffMatchesTheSharedFixture(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "shared", "tests", "capture_diff_conformance.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Cases []struct {
			Name    string     `json:"name"`
			A       []diffFact `json:"a"`
			B       []diffFact `json:"b"`
			Differs []diffKey  `json:"differs"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(raw, &fixture); err != nil {
		t.Fatal(err)
	}
	if len(fixture.Cases) == 0 {
		t.Fatal("the fixture has no cases")
	}
	for _, testCase := range fixture.Cases {
		t.Run(testCase.Name, func(t *testing.T) {
			got := []diffKey{}
			for _, difference := range Differences(bundleOf("cap-a", testCase.A), bundleOf("cap-b", testCase.B)) {
				got = append(got, diffKey{difference.Subject, difference.Predicate})
			}
			want := testCase.Differs
			if want == nil {
				want = []diffKey{}
			}
			gotJSON, _ := json.Marshal(got)
			wantJSON, _ := json.Marshal(want)
			if string(gotJSON) != string(wantJSON) {
				t.Errorf("differences %s, fixture says %s", gotJSON, wantJSON)
			}
		})
	}
}
