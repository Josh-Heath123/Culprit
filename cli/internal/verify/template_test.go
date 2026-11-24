// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package verify

import (
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Q47 (Phase 44 batch 3): incompleteness is about what Culprit could not
// see, and must never hide what it did see. Every Kubernetes capture
// records that the Deployment's template is not the whole environment
// (F44-013); a key one template lists and the other does not is still a
// difference, and verify is not `verified` past it. A key from an envFrom
// source the other capture could not read is never compared.

const template = "kubernetes:deployment/order-service"

// kubeCapture is order-service's environment as the Kubernetes adapter
// records it: each key with the source it was read from, and the skip
// every Kubernetes capture carries, plus one per unread envFrom source.
func kubeCapture(id string, unread []string, keys map[string]string) *model.CaptureBundle {
	bundle := capture(id)
	for key, artefact := range keys {
		subject := model.MustBuildSubject(model.KindConfig, model.Parts{"component": "order-service", "key": key})
		shape := model.ShapeOfString("a-value")
		provenance := model.Provenance{SourceKind: model.SourceIntrospection, Extractor: "culprit@test",
			Artefact: artefact, ConfidenceRank: model.RankRuntimeIntrospection}
		bundle.Facts = append(bundle.Facts,
			model.Fact{Plane: model.PlaneConfigured, Subject: subject, Predicate: model.PredicateExists, Value: true,
				Environment: env, Provenance: provenance, CapturedAt: clock, CaptureID: id},
			model.Fact{Plane: model.PlaneConfigured, Subject: subject, Predicate: model.PredicateValueShape,
				ValueShape: &shape, Environment: env, Provenance: provenance, CapturedAt: clock, CaptureID: id})
	}
	reasons := append([]string{"the image's own ENV and anything a mutating admission webhook adds are not in " +
		"the Deployment's template"}, unread...)
	bundle.Skipped = append(bundle.Skipped, model.Skip{Want: string(model.WantConfigKeys), Component: "order-service",
		Reason: "order-service's environment could not be enumerated completely (" + strings.Join(reasons, "; ") +
			"), so no key is judged missing from it"})
	return bundle
}

func TestAKeyTheTemplateNoLongerListsIsAChangeUnderneath(t *testing.T) {
	before := kubeCapture("cap-before", nil, map[string]string{
		"INVENTORY_SERVICE_URL": template, "FEATURE_FLAG": template})
	// After: the key is gone from the template, and a Secret the template
	// now loads could not be listed. The key may have moved there; the
	// template's change is still seen.
	after := kubeCapture("cap-after",
		[]string{"the keys of Secret order-secrets, which it loads with envFrom, could not be listed"},
		map[string]string{"INVENTORY_SERVICE_URL": template})
	verification, _ := verifyIn(t, scenario{world: fixed, changes: contractFx, before: before, after: after})
	if verification.Verdict != model.VerificationChangedUnderneath {
		t.Fatalf("verdict %s, want changed_underneath: %s", verification.Verdict, verification.Reason)
	}
	if !strings.Contains(verification.Reason, "FEATURE_FLAG") {
		t.Errorf("the reason does not name the key: %s", verification.Reason)
	}
}

func TestAKeyFromASecretTheOtherCaptureCouldNotReadIsNotCompared(t *testing.T) {
	before := kubeCapture("cap-before", nil, map[string]string{
		"INVENTORY_SERVICE_URL": template, "INVENTORY_TOKEN": "kubernetes:secret/order-secrets"})
	after := kubeCapture("cap-after",
		[]string{"the keys of Secret order-secrets, which it loads with envFrom, could not be listed"},
		map[string]string{"INVENTORY_SERVICE_URL": template})
	verification, _ := verifyIn(t, scenario{world: fixed, changes: contractFx, before: before, after: after})
	if verification.Verdict != model.VerificationVerified {
		t.Fatalf("verdict %s, want verified: %s", verification.Verdict, verification.Reason)
	}
	if len(verification.Differences) != 0 {
		t.Errorf("a key from a Secret the other capture could not read was compared: %+v", verification.Differences)
	}
}
