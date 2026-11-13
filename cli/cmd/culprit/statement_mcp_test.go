package main

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/capture"
)

// Phase 37 part 2: nothing an agent says reaches SQL. Through culprit mcp,
// culprit_probe refuses probe.db.plan (its queryid is the walk's), any
// queryid, and any input to probe.db.statement_budget — before anything
// is sent, counted on a statement source that answers everything. Both
// grants are given, so the refusal is this rule's, not a missing grant's.

const statementManifest = `version: 1
components:
  - name: inventory
    kind: service
    connections:
      - to: inventory-db
        kind: sql
        criticality: on_request_path
  - name: inventory-db
    kind: database
environments:
  production:
    adapter: process
    components:
      inventory:
        database: { dsn_env: INVENTORY_DATABASE_URL, name: inventory-db }
    endpoints:
      inventory: { host: inventory.internal, port: 8002, health_path: /ready }
    grants:
      db.stats.read: true
      db.plan.read: true
      db.metadata.read: true
budgets:
  - subject: "component:inventory-db"
    predicate: query_mean_ms_max
    value: 50
    why: so the statement probe reaches its source when it runs, and the count can move
`

type countingStatements struct{ calls atomic.Int64 }

func (c *countingStatements) Window(context.Context, string) (capture.StatementWindow, bool, error) {
	c.calls.Add(1)
	return capture.StatementWindow{}, false, nil
}

func (c *countingStatements) Plan(context.Context, string, int64) (capture.StatementPlan, error) {
	c.calls.Add(1)
	return capture.StatementPlan{}, nil
}

func TestCulpritProbeRefusesWhatOnlyTheWalkMayName(t *testing.T) {
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(statementManifest), 0o600); err != nil {
		t.Fatal(err)
	}
	statements := &countingStatements{}
	client := mcpSession(t, &mcpServer{
		manifestPath: path, stateDir: t.TempDir(), agentID: "test", noPlugins: true,
		through: &wire{Network: &countingNetwork{}, HTTP: &countingHTTP{}, Statements: statements},
		stderr:  io.Discard,
	})
	for _, c := range []struct {
		probes []string
		inputs map[string]any
	}{
		{[]string{"probe.db.plan"}, map[string]any{"queryid": "7"}},
		{[]string{"probe.db.plan"}, nil},
		{[]string{"probe.db.statement_budget"}, map[string]any{"queryid": "7"}},
		{[]string{"probe.db.statement_budget"}, map[string]any{"host": "inventory.internal", "port": 8002}},
		{[]string{"probe.db.statement_budget"}, map[string]any{"url": "http://inventory.internal:8002/"}},
		{[]string{"probe.db.statement_budget"}, map[string]any{"table": "products"}},
		{[]string{"probe.db.connect"}, map[string]any{"queryid": "7"}},
	} {
		arguments := map[string]any{"target": "component:inventory-db",
			"environment": "production", "probes": c.probes}
		if c.inputs != nil {
			arguments["inputs"] = c.inputs
		}
		result := client.call("culprit_probe", arguments)
		if !result.IsError || !strings.Contains(string(result.Structured), "names no statement") {
			t.Errorf("%v %v: not refused: %s", c.probes, c.inputs, result.Structured)
		}
	}
	if calls := statements.calls.Load(); calls != 0 {
		t.Fatalf("%d call(s) reached the statement source for calls that were all refused", calls)
	}
	// The statement probe with no input runs: the declared database only.
	result := client.call("culprit_probe", map[string]any{"target": "component:inventory-db",
		"environment": "production", "probes": []string{"probe.db.statement_budget"}})
	if result.IsError {
		t.Fatalf("the statement probe with no input was refused: %s", result.Structured)
	}
	// And it reached the source: the count above is one that can move
	// (phase-auditor, 2026-11-13: without a budget the probe returned
	// before its source, and the count stayed 0 with the guard removed).
	if calls := statements.calls.Load(); calls == 0 {
		t.Fatal("the statement probe that ran never reached the statement source, so the zero above proves nothing")
	}
}
