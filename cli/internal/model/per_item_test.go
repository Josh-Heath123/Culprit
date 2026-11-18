package model

import (
	"strings"
	"testing"
	"time"
)

// Phase 39 part 1: the per-item rule, held to
// shared/tests/per_item_conformance.json, which culprit_model.per_item
// records (shared/tests/test_per_item.py).

type perItemFixture struct {
	Cases []struct {
		Name     string         `json:"name"`
		Measured map[string]any `json:"measured"`
		Expect   struct {
			Verdict string   `json:"verdict"`
			Reason  string   `json:"reason"`
			PerItem []string `json:"per_item"`
			Error   bool     `json:"error"`
		} `json:"expect"`
	} `json:"cases"`
}

func TestJudgePerItemMatchesTheConformanceFixture(t *testing.T) {
	fixture := readFixture[perItemFixture](t, "per_item_conformance.json")
	if len(fixture.Cases) < 60 {
		t.Fatalf("only %d cases", len(fixture.Cases))
	}
	named := 0
	for _, c := range fixture.Cases {
		verdict, reason, perItem, err := JudgePerItem(c.Measured)
		switch {
		case c.Expect.Error:
			if err == nil {
				t.Errorf("%s: Go judged %s (%s), Python refused the reading", c.Name, verdict, reason)
			}
		case err != nil:
			t.Errorf("%s: Go refused the reading (%v), Python judged %s", c.Name, err, c.Expect.Verdict)
		case string(verdict) != c.Expect.Verdict || reason != c.Expect.Reason ||
			strings.Join(perItem, ",") != strings.Join(c.Expect.PerItem, ","):
			t.Errorf("%s: Go %s %q %v, Python %s %q %v", c.Name, verdict, reason, perItem,
				c.Expect.Verdict, c.Expect.Reason, c.Expect.PerItem)
		}
		if len(perItem) > 0 {
			named++
		}
	}
	if named == 0 {
		t.Error("no case names a statement")
	}
}

// TestTheRulesAnchors are the brief's cases, asserted by hand in Go too.
func TestTheRulesAnchors(t *testing.T) {
	statements := func(pairs ...any) []any {
		var out []any
		for index := 0; index < len(pairs); index += 2 {
			out = append(out, map[string]any{"queryid": pairs[index], "calls": pairs[index+1]})
		}
		return out
	}
	for _, c := range []struct {
		name     string
		measured map[string]any
		verdict  Verdict
		perItem  string
	}{
		{"one per item of 5", map[string]any{"items": 5, "statements": statements("101", 1, "202", 5)}, VerdictPass, "202"},
		{"loaded together", map[string]any{"items": 5, "statements": statements("101", 1)}, VerdictPass, ""},
		{"one short", map[string]any{"items": 5, "statements": statements("202", 4)}, VerdictPass, ""},
		{"one item", map[string]any{"items": 1, "statements": statements("202", 1)}, VerdictInconclusive, ""},
		{"no items", map[string]any{"items": 0, "statements": statements()}, VerdictInconclusive, ""},
	} {
		if c.measured["statements"] == nil {
			c.measured["statements"] = []any{}
		}
		verdict, _, perItem, err := JudgePerItem(c.measured)
		if err != nil || verdict != c.verdict || strings.Join(perItem, ",") != c.perItem {
			t.Errorf("%s: %s %v %v, want %s [%s]", c.name, verdict, perItem, err, c.verdict, c.perItem)
		}
	}
}

func TestAPerItemReadingIsItsOwnIntegers(t *testing.T) {
	target, err := BuildSubject(KindHTTP, Parts{"component": "inventory-service", "method": "GET", "path": "/products"})
	if err != nil {
		t.Fatal(err)
	}
	reading := func(verdict Verdict, measured map[string]any) Reading {
		return Reading{ProbeID: StatementsPerRequestProbeID, ProbeVersion: 1, Target: target,
			Environment: "isolated", Verdict: verdict, Reason: "judged", Measured: measured,
			TakenAt: time.Unix(0, 0), AgentID: "test"}
	}
	nPlusOne := func(perItem any) map[string]any {
		return map[string]any{"items": 5, "statements": []any{
			map[string]any{"queryid": "202", "calls": 5}, map[string]any{"queryid": "101", "calls": 1},
		}, "per_item": perItem}
	}
	if err := reading(VerdictPass, nPlusOne([]any{"202"})).Validate(); err != nil {
		t.Errorf("the rule's own reading is refused: %v", err)
	}
	for name, r := range map[string]Reading{
		"another verdict":              reading(VerdictInconclusive, nPlusOne([]any{"202"})),
		"none named":                   reading(VerdictPass, nPlusOne([]any{})),
		"one more named":               reading(VerdictPass, nPlusOne([]any{"101", "202"})),
		"per_item missing":             reading(VerdictPass, nPlusOne(nil)),
		"a pass with no statements":    reading(VerdictPass, map[string]any{"url": "http://x/products"}),
		"names what it does not carry": reading(VerdictInconclusive, map[string]any{"per_item": []any{"202"}}),
	} {
		if r.Validate() == nil {
			t.Errorf("%s: validated", name)
		}
	}
	if err := reading(VerdictInconclusive, map[string]any{"quiet_calls": 3}).Validate(); err != nil {
		t.Errorf("an inconclusive reading with nothing bracketed is refused: %v", err)
	}
}
