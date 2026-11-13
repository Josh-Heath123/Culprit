package main

import (
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// TestTheDatabasePassIsPlacedWithTheRealCatalogue holds the binary to what
// internal/isolate's database tests assume of their hand-built manifests
// (Phase 37 part 3): in the real catalogue, the statement probe and the plan
// probe each discriminate their hypothesis, and the real placement places
// each from inside the entry, on its connection to the database, and refuses
// it from anywhere else.
func TestTheDatabasePassIsPlacedWithTheRealCatalogue(t *testing.T) {
	want := map[string]string{
		model.HypothesisStatementBudgetExceeded: model.StatementProbeID,
		model.HypothesisMissingIndex:            model.PlanProbeID,
	}
	manifests := map[string]model.ProbeManifest{}
	for _, manifest := range catalogue().Manifests() {
		manifests[manifest.ID] = manifest
	}
	connection := model.MustBuildSubject(model.KindConnection, model.Parts{
		"from_component": "shop-service", "to_component": "shop-db"})
	inside := newPlacement(nil, extract.EnvironmentSpec{}, "shop-service", nil)
	outside := newPlacement(nil, extract.EnvironmentSpec{}, "", nil)

	for kind, probeID := range want {
		manifest, ok := manifests[probeID]
		if !ok {
			t.Fatalf("%s is not in the catalogue", probeID)
		}
		declared := false
		for _, discriminated := range manifest.Discriminates {
			declared = declared || discriminated == kind
		}
		if !declared {
			t.Errorf("%s does not declare that it discriminates %s: the walk would find no probe for it", probeID, kind)
		}
		h := model.Hypothesis{Kind: kind, Subject: connection}
		if inputs, reason := inside.Inputs(manifest, h); reason != "" || len(inputs) != 0 {
			t.Errorf("%s from inside shop-service: inputs %v, reason %q; want no input and no reason", kind, inputs, reason)
		}
		if _, reason := outside.Inputs(manifest, h); !strings.Contains(reason, "--from shop-service") {
			t.Errorf("%s from outside every component: reason %q, want the vantage rule", kind, reason)
		}
	}
	// Each kind is placed only for its own probe.
	h := model.Hypothesis{Kind: model.HypothesisMissingIndex, Subject: connection}
	if _, reason := inside.Inputs(manifests[model.StatementProbeID], h); reason == "" {
		t.Error("missing_index was placed for the statement probe")
	}
}
