package extract

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// culprit.yaml's `probes:` section.
//
// The cases that matter are the refusals: a section that silently
// accepts a typo is worse than no section, because a probe disabled by a
// misspelled environment name looks exactly like a probe that passed.

func writeManifest(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatalf("writing manifest: %v", err)
	}
	return path
}

const probeManifestHeader = `version: 1
components:
  - name: orders-api
    kind: service
environments:
  staging:
    adapter: process
    components:
      orders-api: {}
`

func TestProbesSectionIsParsed(t *testing.T) {
	path := writeManifest(t, probeManifestHeader+`probes:
  probe.net.tls_validity:
    enabled: false
    reason: certificates are managed by the platform team
  probe.http.route_conformance:
    timeout_ms: 30000
    environments: [staging]
`)
	manifest, err := LoadManifest(path)
	if err != nil {
		t.Fatalf("LoadManifest: %v", err)
	}
	if len(manifest.Probes) != 2 {
		t.Fatalf("expected 2 probe specs, got %d", len(manifest.Probes))
	}
	tls := manifest.Probes["probe.net.tls_validity"]
	if tls.Enabled == nil || *tls.Enabled {
		t.Error("probe.net.tls_validity should be explicitly disabled")
	}
	route := manifest.Probes["probe.http.route_conformance"]
	if route.TimeoutMS != 30000 {
		t.Errorf("timeout_ms = %d, want 30000", route.TimeoutMS)
	}
	if route.Enabled != nil {
		t.Error("an unmentioned `enabled` must stay nil, so absent and " +
			"explicitly-false remain distinguishable")
	}
}

func TestDisablingAProbeWithoutAReasonIsRefused(t *testing.T) {
	path := writeManifest(t, probeManifestHeader+`probes:
  probe.net.tls_validity:
    enabled: false
`)
	_, err := LoadManifest(path)
	if err == nil {
		t.Fatal("a probe disabled with no reason was accepted")
	}
	if !strings.Contains(err.Error(), "reason") {
		t.Errorf("the error should ask for a reason, got: %v", err)
	}
}

func TestProbesSectionRefusesAnUndeclaredEnvironment(t *testing.T) {
	path := writeManifest(t, probeManifestHeader+`probes:
  probe.http.reachable:
    environments: [staging, prodcution]
`)
	_, err := LoadManifest(path)
	if err == nil {
		t.Fatal("a misspelled environment name was accepted; it would have " +
			"silently disabled the probe everywhere")
	}
	if !strings.Contains(err.Error(), "prodcution") {
		t.Errorf("the error should name the offending value, got: %v", err)
	}
}

func TestProbesSectionRefusesAMalformedProbeID(t *testing.T) {
	path := writeManifest(t, probeManifestHeader+`probes:
  tls_validity:
    timeout_ms: 1000
`)
	if _, err := LoadManifest(path); err == nil {
		t.Fatal("a bare name was accepted as a probe id")
	}
}

func TestProbesSectionRefusesAnAbsurdTimeout(t *testing.T) {
	path := writeManifest(t, probeManifestHeader+`probes:
  probe.http.reachable:
    timeout_ms: 900000
`)
	if _, err := LoadManifest(path); err == nil {
		t.Fatal("a fifteen-minute probe timeout was accepted")
	}
}

// TestProbesSectionAcceptsAnUnknownProbeID is the deliberate non-check.
//
// Third-party probes are manifests plus an exec procedure, so a
// culprit.yaml may configure a probe this binary does not have. Refusing
// it here would make the file unshareable between a team using a plugin
// and a team that is not; the runner reports an unknown id as
// inconclusive at run time, which is the honest place for it.
func TestProbesSectionAcceptsAnUnknownProbeID(t *testing.T) {
	path := writeManifest(t, probeManifestHeader+`probes:
  probe.vendor.custom_thing:
    timeout_ms: 1000
`)
	if _, err := LoadManifest(path); err != nil {
		t.Fatalf("a third-party probe id was refused: %v", err)
	}
}

func TestAManifestWithNoProbesSectionStillLoads(t *testing.T) {
	path := writeManifest(t, probeManifestHeader)
	manifest, err := LoadManifest(path)
	if err != nil {
		t.Fatalf("LoadManifest: %v", err)
	}
	if len(manifest.Probes) != 0 {
		t.Errorf("expected no probe specs, got %d", len(manifest.Probes))
	}
}
