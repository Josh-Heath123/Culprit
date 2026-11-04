package probe

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/report"
)

// grantedSecret stands for a config value a `config.read.values` grant let
// a capture record. It must never reach a reading, however it got there.
const grantedSecret = "granted-config-value-9f3a71c2"

func configuredFact(value string, rank int, artefact string) model.Fact {
	return model.Fact{
		Plane:       model.PlaneConfigured,
		Subject:     "config:billing-api/WEBHOOK_SIGNING_KEY",
		Predicate:   "value",
		Value:       value,
		GrantRef:    "config.read.values:WEBHOOK_SIGNING_KEY",
		Environment: "staging",
		Provenance: model.Provenance{
			SourceKind: model.SourceObservation, Artefact: artefact, ConfidenceRank: rank,
		},
	}
}

// TestEvidenceNeverRendersAConfiguredValue is Phase 32's first carried-in
// item: conflict evidence once wrote every fact's value with CanonicalJSON,
// so a CONFIGURED expectation with a granted value would have printed it.
// Text and JSON, pass and fail.
func TestEvidenceNeverRendersAConfiguredValue(t *testing.T) {
	chosen := configuredFact(grantedSecret, 80, "capture:staging")
	other := configuredFact(grantedSecret+"-other", 60, "capture:staging-replica")
	evidence := conflictEvidence(&chosen, []model.Fact{other})

	if len(evidence) != 1 {
		t.Fatalf("got %d conflict evidence items, want 1", len(evidence))
	}
	if !strings.Contains(evidence[0].Value, "shape") {
		t.Errorf("evidence does not describe the values by shape: %q", evidence[0].Value)
	}

	for _, verdict := range []model.Verdict{model.VerdictPass, model.VerdictFail} {
		reading := model.Reading{
			ProbeID: "probe.config.present", ProbeVersion: 2,
			Target: "component:billing-api", Environment: "staging",
			Verdict: verdict, Evidence: evidence, TakenAt: time.Unix(0, 0).UTC(),
			AgentID: "test",
		}
		var text bytes.Buffer
		if err := report.RenderReadings(&text, []model.Reading{reading}); err != nil {
			t.Fatal(err)
		}
		encoded, err := json.Marshal(reading)
		if err != nil {
			t.Fatal(err)
		}
		for format, output := range map[string]string{"text": text.String(), "json": string(encoded)} {
			if strings.Contains(output, grantedSecret) {
				t.Errorf("%s reading, %s output contains the granted config value", verdict, format)
			}
		}
	}
}

// An INTENT fact's value is a declaration in the repository, not a
// secret, and stays readable: the rule is about the CONFIGURED plane.
func TestDisplayValueStillRendersIntentValues(t *testing.T) {
	fact := intentFact("http:orders/GET /orders", model.PredicateExists,
		map[string]any{"method": "GET"}, "openapi.json", 80)
	if got := model.DisplayValue(fact); !strings.Contains(got, "GET") {
		t.Errorf("DisplayValue(intent) = %q, want the declared value", got)
	}
}
