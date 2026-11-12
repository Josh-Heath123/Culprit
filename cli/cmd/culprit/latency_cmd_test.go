package main

import (
	"context"
	"encoding/json"
	"io"
	stdhttp "net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/probe"
)

// Naming probe.http.latency twice — `-p x -p x` to culprit probe, or a
// list over culprit_probe — runs it once (Phase 36 part 1 phase audit,
// finding A: it ran twice, concurrently, for twice the request cap).

const latencyManifest = agentManifest + `budgets:
  - subject: "http:payments/GET /health"
    predicate: latency_p50_ms
    value: 300
    why: a test budget on the declared endpoint's health route
`

func writeLatencyManifest(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(latencyManifest), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestALatencyProbeNamedTwiceRunsOnce(t *testing.T) {
	http := &countingHTTP{}
	readings, _, err := runProbe(context.Background(), probeInput{
		ManifestPath: writeLatencyManifest(t), Environment: "production", Target: "connection:orders->payments",
		ProbeIDs: []string{model.LatencyProbeID, model.LatencyProbeID},
		Inputs:   map[string]any{"url": "http://payments.internal:8443/health"},
		AgentID:  "test", NoPlugins: true, Timeout: 2 * time.Second,
		Through: &wire{Network: &countingNetwork{}, HTTP: http},
	})
	if err != nil || len(readings) != 1 {
		t.Fatalf("%v: %d readings, want 1", err, len(readings))
	}
	if readings[0].Verdict != model.VerdictPass {
		t.Errorf("%s: %s", readings[0].Verdict, readings[0].Reason)
	}
	if requests := http.requests.Load(); requests != 20 {
		t.Errorf("%d requests, want 20: the probe ran more than once", requests)
	}
}

func TestALatencyProbeListedTwiceOverMCPRunsOnce(t *testing.T) {
	http := &countingHTTP{}
	client := mcpSession(t, &mcpServer{
		manifestPath: writeLatencyManifest(t), stateDir: t.TempDir(), agentID: "test", noPlugins: true,
		through: &wire{Network: &countingNetwork{}, HTTP: http}, stderr: io.Discard,
	})
	result := client.call("culprit_probe", map[string]any{
		"target": "connection:orders->payments", "environment": "production",
		"probes": []string{model.LatencyProbeID, model.LatencyProbeID},
		"inputs": map[string]any{"url": "http://payments.internal:8443/health"},
	})
	if result.IsError {
		t.Fatalf("refused: %s", result.Structured)
	}
	var answer struct {
		Readings []model.Reading `json:"readings"`
	}
	if err := json.Unmarshal(result.Structured, &answer); err != nil || len(answer.Readings) != 1 {
		t.Fatalf("%v: want one reading in %s", err, result.Structured)
	}
	if requests := http.requests.Load(); requests != 20 {
		t.Errorf("%d requests, want 20: the probe ran more than once", requests)
	}
}

// TestCulpritMcpServesTheBuiltInCatalogue: the catalogue every command and
// culprit mcp run from is exactly BuiltIn's. register_test.go holds the
// source; this holds what the binary builds, which a registration hidden
// from a source scan (by reflection) would change (Q25, Phase 36 re-audit).
func TestCulpritMcpServesTheBuiltInCatalogue(t *testing.T) {
	served, built := catalogue().IDs(), probe.BuiltIn().IDs()
	if len(served) != 14 || strings.Join(served, ",") != strings.Join(built, ",") {
		t.Fatalf("culprit serves %v, BuiltIn registers %v", served, built)
	}
}

// TestDiagnoseFindsASlowComponentAndVerifyJudgesItsFix is the walk's
// latency pass through the real commands, on loopback (Phase 36 part 2):
// a component whose GET /health is slower than both its budgets is the
// root, one run gives both readings, and `culprit verify` runs each such
// run once a round and says verified after the delay is taken out.
// Without the latency case in placement the probe was never placed — every
// unit test passed, and the first real walk said so.
func TestDiagnoseFindsASlowComponentAndVerifyJudgesItsFix(t *testing.T) {
	var delay atomic.Int64
	delay.Store(int64(40 * time.Millisecond))
	var latencyRequests atomic.Int64
	server := httptest.NewServer(stdhttp.HandlerFunc(func(w stdhttp.ResponseWriter, r *stdhttp.Request) {
		if r.Method != stdhttp.MethodGet {
			t.Errorf("a %s request reached the server", r.Method)
		}
		latencyRequests.Add(1)
		time.Sleep(time.Duration(delay.Load()))
		w.WriteHeader(stdhttp.StatusOK)
	}))
	defer server.Close()
	address := strings.TrimPrefix(server.URL, "http://")
	host, port, _ := strings.Cut(address, ":")
	manifest := `version: 1
components:
  - name: web
    kind: frontend
    connections:
      - to: api
        kind: http
        criticality: on_request_path
  - name: api
    kind: service
environments:
  local:
    adapter: process
    components: { api: {} }
    endpoints: { api: { host: ` + host + `, port: ` + port + `, health_path: /health } }
    grants: { config.read.names: true, net.http.outbound: true, net.tcp.connect: true, net.dns.resolve: true }
invariants:
  - subject: "http:api/GET /health"
    predicate: exists
    why: the route the budgets are on
budgets:
  - subject: "http:api/GET /health"
    predicate: latency_p95_ms
    value: 20
    why: a test budget, well under the injected delay
  - subject: "http:api/GET /health"
    predicate: latency_p50_ms
    value: 20
    why: a test budget, well under the injected delay
`
	dir := t.TempDir()
	path := filepath.Join(dir, "culprit.yaml")
	if err := os.WriteFile(path, []byte(manifest), 0o600); err != nil {
		t.Fatal(err)
	}
	state := filepath.Join(dir, "state")
	inv, err := runDiagnose(context.Background(), diagnoseInput{
		ManifestPath: path, Environment: "local", From: "web", Symptom: "web", AgentID: "test",
		StateDir: state, NoPlugins: true, Timeout: 5 * time.Second, Stderr: io.Discard,
	})
	if err != nil {
		t.Fatal(err)
	}
	if d := inv.Diagnosis; d.RootSubject != "component:api" || !d.Complete {
		t.Fatalf("root %s complete=%v: %s", d.RootSubject, d.Complete, d.Statement)
	}
	var latency []model.InvestigationReading
	for _, item := range inv.Readings {
		if item.Reading.ProbeID == model.LatencyProbeID {
			latency = append(latency, item)
		}
	}
	// The walk's run and the rubric's run again, each giving two readings.
	if len(latency) != 4 {
		t.Fatalf("%d latency readings, want 4 (two runs, two budgets each)", len(latency))
	}
	var record struct {
		Requests []struct {
			ReadingID string `json:"reading_id"`
			SameRunAs string `json:"same_run_as"`
		} `json:"requests"`
	}
	raw, err := os.ReadFile(filepath.Join(state, "investigations", inv.ID, "record.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(raw, &record); err != nil {
		t.Fatal(err)
	}
	shared := 0
	for _, request := range record.Requests {
		if request.SameRunAs != "" {
			shared++
		}
	}
	if shared != 2 {
		t.Fatalf("%d readings recorded as from another's run, want 2: %s", shared, raw)
	}
	// The fix, then verification: four latency readings, two runs a round.
	delay.Store(0)
	latencyRequests.Store(0)
	verification, err := runVerify(context.Background(), verifyInput{
		ManifestPath: path, StateDir: state, From: "web", InvestigationID: inv.ID, AgentID: "test",
		Changes: []string{"action:took the delay out of /health"}, NoPlugins: true,
		Timeout: 5 * time.Second, Stderr: io.Discard,
	})
	if err != nil {
		t.Fatal(err)
	}
	if verification.Verdict != model.VerificationVerified {
		t.Fatalf("verdict %s: %s", verification.Verdict, verification.Reason)
	}
	// Two rounds of two runs of 50, and two rounds of the one health check.
	if got := latencyRequests.Load(); got != 2*2*model.LatencyMaxRequests+2 {
		t.Fatalf("%d requests during verification, want %d: a shared run was taken more than once",
			got, 2*2*model.LatencyMaxRequests+2)
	}
}
