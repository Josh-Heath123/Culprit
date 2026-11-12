package main

import (
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
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
