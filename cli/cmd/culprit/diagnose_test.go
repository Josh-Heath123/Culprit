package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// diagnoseFixture is a two-component system: web calls api on the request
// path, and both web and api say GET /orders exists and is called. The test
// server standing in for api answers /health and nothing else — a contract
// fault: the route both sides declare is not served.
const diagnoseFixture = `version: 1
components:
  - name: web
    kind: frontend
    connections:
      - to: api
        kind: http
        criticality: on_request_path
  - name: api
    kind: service
invariants:
  - subject: "http:api/GET /orders"
    predicate: exists
    why: api declares it serves this route
  - subject: "http:api/GET /orders"
    predicate: calls
    why: web calls it on every page load
environments:
  local:
    adapter: process
    components:
      web: {}
    endpoints:
      api: { host: 127.0.0.1, port: %d, health_path: /health }
    grants:
      net.http.outbound: true
      net.tcp.connect: true
      net.dns.resolve: true
`

func startAPI(t *testing.T) int {
	t.Helper()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/health" {
			_, _ = w.Write([]byte(`{"status":"ok"}`))
			return
		}
		http.NotFound(w, r)
	}))
	t.Cleanup(server.Close)
	_, port, err := net.SplitHostPort(strings.TrimPrefix(server.URL, "http://"))
	if err != nil {
		t.Fatal(err)
	}
	var number int
	fmt.Sscanf(port, "%d", &number)
	return number
}

func writeDiagnoseFixture(t *testing.T, port int) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(fmt.Sprintf(diagnoseFixture, port)), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

// TestDiagnoseFindsTheContractNotTheCaller runs the real command, real
// probes, against a real (local) server, with LLM_PROVIDER=none — Phase
// 32's fourth criterion: the fault tree is complete and correct with no
// model anywhere. Nothing in the walk reads that variable; the test is that
// nothing needed to.
func TestDiagnoseFindsTheContractNotTheCaller(t *testing.T) {
	t.Setenv("LLM_PROVIDER", "none")
	path := writeDiagnoseFixture(t, startAPI(t))

	stdout, err := run(t, "diagnose", "web", "-f", path, "--env", "local", "--from", "web",
		"--no-plugins", "--format", "json")
	if err != nil {
		t.Fatalf("diagnose: %v\n%s", err, stdout)
	}
	var inv model.Investigation
	if err := json.Unmarshal([]byte(stdout), &inv); err != nil {
		t.Fatalf("output is not an investigation: %v\n%s", err, stdout)
	}
	if err := inv.Validate(); err != nil {
		t.Fatalf("the investigation does not validate: %v", err)
	}
	if inv.Diagnosis == nil || !inv.Diagnosis.Complete {
		t.Fatalf("diagnosis %+v, want a complete one", inv.Diagnosis)
	}
	if got, want := inv.Diagnosis.RootSubject, "http:api/GET /orders"; got != want {
		t.Errorf("root %s, want %s — the route, not the caller and not api as a whole", got, want)
	}
	causedBy := false
	for _, edge := range inv.FaultTree {
		if edge.Relation == model.RelationCausedBy && edge.ToSubject == "http:api/GET /orders" {
			causedBy = true
		}
	}
	if !causedBy {
		t.Errorf("no caused_by edge reaches the route: %+v", inv.FaultTree)
	}
	// api itself answered, and web could open a connection to it: both
	// were ruled out by a reading, not assumed.
	for _, kind := range []string{model.HypothesisComponentFails, model.HypothesisConnectionUnreachable} {
		ruledOut := false
		for _, h := range inv.Hypotheses {
			if h.Kind == kind && h.Status == model.HypothesisRuledOut && len(h.Readings) > 0 {
				ruledOut = true
			}
		}
		if !ruledOut {
			t.Errorf("%s was not ruled out by a reading", kind)
		}
	}
}

// TestDiagnoseWithoutAVantageIsPartialAndSaysWhy: from outside every
// component, the connection web -> api cannot be probed, and the diagnosis
// must say so rather than treat the untested edge as fine.
func TestDiagnoseWithoutAVantageIsPartialAndSaysWhy(t *testing.T) {
	path := writeDiagnoseFixture(t, startAPI(t))
	stdout, err := run(t, "diagnose", "web", "-f", path, "--env", "local", "--no-plugins")
	var partial *partialDiagnosisError
	if !errors.As(err, &partial) {
		t.Fatalf("err = %v, want a partial diagnosis (exit 1)\n%s", err, stdout)
	}
	for _, needle := range []string{"PARTIAL", "--from web", "Unexplored", "stopped at", "could not check"} {
		if !strings.Contains(stdout, needle) {
			t.Errorf("text output does not say %q:\n%s", needle, stdout)
		}
	}
	// Phase 32.1 field 14: a partial diagnosis is never shown under the
	// word "root" or "cause", and offers no fix.
	start := strings.Index(stdout, "Diagnosis (")
	end := strings.Index(stdout, "Confidence")
	if start < 0 || end < start {
		t.Fatalf("no diagnosis block in:\n%s", stdout)
	}
	block := strings.ToLower(stdout[start:end])
	for _, word := range []string{"root", "cause", "fix "} {
		if strings.Contains(block, word) {
			t.Errorf("the partial diagnosis says %q:\n%s", word, stdout[start:end])
		}
	}
}

func TestDiagnoseRefusesAnUndeclaredEnvironmentOrComponent(t *testing.T) {
	path := writeDiagnoseFixture(t, startAPI(t))
	if _, err := run(t, "diagnose", "web", "-f", path, "--env", "nowhere", "--no-plugins"); err == nil {
		t.Error("an undeclared environment was accepted")
	}
	if _, err := run(t, "diagnose", "no-such-component", "-f", path, "--env", "local", "--no-plugins"); err == nil {
		t.Error("an undeclared component was accepted as a symptom")
	}
}
