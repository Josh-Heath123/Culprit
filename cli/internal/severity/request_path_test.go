// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package severity_test

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/severity"
)

// The Go half of shared/tests/request_path_conformance.json (F44-063,
// F44-064 c). The Python half is shared/tests/test_graph.py, which walks
// SystemGraph.upstream_connections over the same cases.

type requestPathCase struct {
	Name       string `json:"name"`
	Components []struct {
		Name string `json:"name"`
		Kind string `json:"kind"`
	} `json:"components"`
	Connections []struct {
		From        string `json:"from"`
		To          string `json:"to"`
		Criticality string `json:"criticality"`
	} `json:"connections"`
	Reach map[string]struct {
		State string `json:"state"`
		Via   *struct {
			From string `json:"from"`
			To   string `json:"to"`
		} `json:"via"`
	} `json:"reach"`
}

func TestTheRequestPathMatchesTheSharedFixture(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "shared", "tests", "request_path_conformance.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Cases []requestPathCase `json:"cases"`
	}
	if err := json.Unmarshal(raw, &fixture); err != nil {
		t.Fatal(err)
	}
	if len(fixture.Cases) == 0 {
		t.Fatal("the fixture has no cases")
	}
	for _, testCase := range fixture.Cases {
		t.Run(testCase.Name, func(t *testing.T) {
			manifest := &extract.Manifest{}
			for _, component := range testCase.Components {
				entry := extract.ManifestComponent{Name: component.Name, Kind: component.Kind}
				for _, connection := range testCase.Connections {
					if connection.From == component.Name {
						entry.Connections = append(entry.Connections, extract.ManifestConnection{
							To: connection.To, Kind: "http", Criticality: connection.Criticality})
					}
				}
				manifest.Components = append(manifest.Components, entry)
			}
			classifier := severity.NewClassifier(manifest, model.CaptureBundle{})
			for name, want := range testCase.Reach {
				for _, divergence := range []model.Divergence{
					{Subject: model.MustBuildSubject(model.KindHTTP,
						model.Parts{"component": name, "method": "GET", "path": "/orders"}),
						Predicate: model.PredicateExists},
					{Subject: model.MustBuildSubject(model.KindComponent, model.Parts{"name": name}),
						Predicate: model.PredicateMigrationHead},
				} {
					level, reason := classifier.Classify(divergence)
					switch want.State {
					case "on_request_path":
						if level != model.SeverityBreaksRequestPath {
							t.Errorf("%s (%s): %s, %q; want breaks_request_path", name, divergence.Subject, level, reason)
						}
					case "not_on_path":
						if level != model.SeverityDegrades {
							t.Errorf("%s (%s): %s, %q; want degrades", name, divergence.Subject, level, reason)
						}
					case "unknown":
						edge := want.Via.From + " -> " + want.Via.To
						if level != model.SeverityUnknown || !strings.Contains(reason, edge) {
							t.Errorf("%s (%s): %s, %q; want unknown, naming %s", name, divergence.Subject, level, reason, edge)
						}
					default:
						t.Fatalf("unknown state %q in the fixture", want.State)
					}
				}
			}
		})
	}
}
