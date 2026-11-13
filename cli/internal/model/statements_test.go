package model

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// TestTheStatementRuleHoldsToTheSharedCases: shared/tests/
// statement_conformance.json, which culprit_model/statements.py is held
// to as well.
func TestTheStatementRuleHoldsToTheSharedCases(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "shared", "tests", "statement_conformance.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Cases []struct {
			Why      string         `json:"why"`
			Measured map[string]any `json:"measured"`
			Verdict  Verdict        `json:"verdict"`
			Reason   string         `json:"reason"`
			Error    bool           `json:"error"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(raw, &fixture); err != nil || len(fixture.Cases) == 0 {
		t.Fatalf("statement_conformance.json: %v", err)
	}
	for _, c := range fixture.Cases {
		verdict, reason, err := JudgeStatements(c.Measured)
		switch {
		case c.Error && err == nil:
			t.Errorf("%s: judged %s, want the shape refused", c.Why, verdict)
		case !c.Error && err != nil:
			t.Errorf("%s: refused: %v", c.Why, err)
		case !c.Error && (verdict != c.Verdict || reason != c.Reason):
			t.Errorf("%s: %s %q, want %s %q", c.Why, verdict, reason, c.Verdict, c.Reason)
		}
	}
}

// TestAStatementReadingWhoseVerdictDisagreesIsRefused: the reading's
// verdict is re-judged from its integers.
func TestAStatementReadingWhoseVerdictDisagreesIsRefused(t *testing.T) {
	target, err := BuildSubject(KindComponent, Parts{"name": "inventory-db"})
	if err != nil {
		t.Fatal(err)
	}
	reading := Reading{
		Target:  target,
		ProbeID: StatementProbeID, ProbeVersion: 1, Environment: "local",
		Verdict: VerdictPass, AgentID: "test", TakenAt: time.Unix(0, 0).UTC(),
		Measured: map[string]any{
			"reset_during_window": false,
			"statements": []any{map[string]any{
				"queryid": "101", "calls": 5, "total_us": 260000, "budget_ms": 50,
			}},
		},
	}
	if err := reading.Validate(); err == nil {
		t.Fatal("a pass reading over its budget was accepted")
	}
	reading.Verdict, reading.Reason = VerdictFail, "over"
	if err := reading.Validate(); err != nil {
		t.Fatalf("the reading its integers give was refused: %v", err)
	}
}
