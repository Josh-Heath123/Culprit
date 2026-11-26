// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package diverge

import (
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Q47: a key one Deployment's template lists and the other does not is
// said as a change to the template, since the other capture may have it
// from a source Culprit cannot read; and against INTENT, an incomplete
// capture still never proves a key absent.

func kubeBundle(environment string, keys map[string]string, skipped bool) model.CaptureBundle {
	name := environment
	bundle := model.CaptureBundle{Plane: model.PlaneConfigured, Environment: &name}
	for key, artefact := range keys {
		bundle.Facts = append(bundle.Facts, model.Fact{Plane: model.PlaneConfigured,
			Subject: "config:orders-api/" + key, Predicate: model.PredicateExists, Value: true,
			Environment: environment, CapturedAt: clock,
			Provenance: model.Provenance{SourceKind: model.SourceIntrospection, Extractor: "culprit@test",
				Artefact: artefact, ConfidenceRank: model.RankRuntimeIntrospection}})
	}
	if skipped {
		bundle.Skipped = []model.Skip{{Want: string(model.WantConfigKeys), Component: "orders-api",
			Reason: "orders-api's environment could not be enumerated completely"}}
	}
	return bundle
}

func TestAKeyOneTemplateListsIsSaidAsAChangeToTheTemplate(t *testing.T) {
	template := model.ArtefactKubernetesTemplate + "orders-api"
	staging := kubeBundle("staging", map[string]string{"PORT": template, "FEATURE_FLAG": template}, true)
	production := kubeBundle("production", map[string]string{"PORT": template}, true)
	result := CompareAll([]model.CaptureBundle{staging, production}, Options{Now: clock})
	if len(result.Divergences) != 1 {
		t.Fatalf("want one finding, got %d: %+v", len(result.Divergences), result.Divergences)
	}
	finding := result.Divergences[0]
	if finding.Kind != model.KindEnvVsEnv || finding.Subject != "config:orders-api/FEATURE_FLAG" {
		t.Fatalf("the wrong finding: %+v", finding)
	}
	for _, words := range []string{"Deployment's template", "production's template does not",
		"may come from a source Culprit cannot read"} {
		if !strings.Contains(finding.Explanation, words) {
			t.Errorf("the explanation does not say %q: %s", words, finding.Explanation)
		}
	}
}

func TestAnIncompleteCaptureNeverProvesAKeyAbsentFromIntent(t *testing.T) {
	template := model.ArtefactKubernetesTemplate + "orders-api"
	intent := model.CaptureBundle{Plane: model.PlaneIntent, Facts: []model.Fact{
		fact("config:orders-api/FEATURE_FLAG", model.PredicateExists, true, "culprit-extract-python@test",
			"app/settings.py", 90),
		fact("config:orders-api/PORT", model.PredicateExists, true, "culprit-extract-python@test",
			"app/settings.py", 90),
	}}
	production := kubeBundle("production", map[string]string{"PORT": template}, true)
	result := CompareAll([]model.CaptureBundle{intent, production}, Options{Now: clock})
	for _, finding := range result.Divergences {
		if finding.Subject == "config:orders-api/FEATURE_FLAG" {
			t.Errorf("an incomplete capture was the evidence a key INTENT names is absent: %+v", finding)
		}
	}
}
