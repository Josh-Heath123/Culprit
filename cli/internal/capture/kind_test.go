// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package capture

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Phase 30 field 13: capture against a kind cluster.
//
// Real kubectl, a real API server, a real Pod whose status reports a real
// image digest. The fixture is cli/testdata/kind/fixture.yaml, which the
// `kind-capture` CI job (and `just cli-test-kind` locally) applies before
// running this with CULPRIT_KIND_TESTS=1. Without it the test is skipped
// and says NOT RUN — a skipped cluster test is not a passing one.
//
// The recorded-output tests in capture_test.go pin down the adapter's
// parsing; this pins down that the parsing matches what a cluster
// actually returns, which recorded output cannot.
func TestKubernetesCaptureAgainstKind(t *testing.T) {
	if os.Getenv("CULPRIT_KIND_TESTS") != "1" {
		t.Skip("NOT RUN: set CULPRIT_KIND_TESTS=1 with cli/testdata/kind/fixture.yaml applied to run the kind test")
	}
	if _, err := exec.LookPath("kubectl"); err != nil {
		t.Fatal("CULPRIT_KIND_TESTS=1 but kubectl is not on PATH")
	}
	kubeContext := os.Getenv("CULPRIT_KIND_CONTEXT")
	if kubeContext == "" {
		kubeContext = "kind-culprit-capture"
	}

	manifest := loadManifest(t, `
version: 1
components:
  - name: orders-api
environments:
  kind:
    adapter: kubernetes
    kubernetes:
      context: `+kubeContext+`
      namespace: culprit-capture
    grants:
      config.read.names: true
      deploy.metadata.read: true
    components:
      orders-api: {container: api}
`)
	bundle, err := Run(context.Background(), Options{
		Manifest:    manifest,
		Environment: "kind",
		Now:         time.Now().UTC(),
		Version:     "test",
		Runner:      ExecRunner{Timeout: 60 * time.Second},
	})
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	// Every envFrom source here is readable, so the one gap is the one no
	// Kubernetes capture can close (F44-013): the image's own ENV and what
	// an admission webhook injects are not in the Deployment's template.
	// No other gap — a ConfigMap or Secret it could not read — is allowed.
	const templateOnly = "orders-api's environment could not be enumerated completely (the image's own ENV " +
		"and anything a mutating admission webhook adds are not in the Deployment's template), so no key " +
		"is judged missing from it"
	if len(bundle.Skipped) != 1 || bundle.Skipped[0].Want != string(model.WantConfigKeys) ||
		bundle.Skipped[0].Reason != templateOnly {
		t.Fatalf("the capture recorded a gap other than the template's own against a cluster it can "+
			"fully read: %+v", bundle.Skipped)
	}

	for key, want := range map[string]model.ValueType{
		"PORT":                  model.TypeString,  // a literal value:
		"DATABASE_URL":          model.TypeUnknown, // valueFrom secretKeyRef
		"LOG_LEVEL":             model.TypeString,  // envFrom ConfigMap
		"STRIPE_URL":            model.TypeString,  // envFrom ConfigMap
		"SECRET_JWT_SECRET_KEY": model.TypeUnknown, // envFrom Secret, prefixed: key only
		"SECRET_STRIPE_API_KEY": model.TypeUnknown,
	} {
		fact, ok := find(bundle, "config:orders-api/"+key, model.PredicateValueShape)
		if !ok || fact.ValueShape.Type != want || !fact.ValueShape.Present {
			t.Errorf("%s: %+v (found: %t)", key, fact.ValueShape, ok)
		}
	}
	if stripe, _ := find(bundle, "config:orders-api/STRIPE_URL", model.PredicateValueShape); stripe.ValueShape.Scheme != model.SchemeHTTPS {
		t.Errorf("STRIPE_URL scheme = %q", stripe.ValueShape.Scheme)
	}
	if reference, _ := find(bundle, "image:orders-api", PredicateReference); reference.Value != "alpine:3.20" {
		t.Errorf("reference = %v", reference.Value)
	}
	digest, ok := find(bundle, "image:orders-api", PredicateDigest)
	if value, _ := digest.Value.(string); !ok || !strings.HasPrefix(value, "sha256:") {
		t.Errorf("no digest from the running Pod: %+v", digest)
	}

	envelope, err := Seal(bundle, nil)
	if err != nil {
		t.Fatal(err)
	}
	encoded, _ := json.Marshal(envelope)
	payload, _ := base64.StdEncoding.DecodeString(envelope.Payload)
	for _, secret := range []string{
		"kind-fixture-jwt-planted", "sk_live_kind_fixture_planted_0123", "kind-fixture-db-password-planted",
	} {
		if strings.Contains(string(encoded), secret) || strings.Contains(string(payload), secret) {
			t.Errorf("the capture contains the Secret value %q", secret)
		}
	}
}
