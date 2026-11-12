package model

import (
	"strings"
	"testing"
	"time"
)

// The latency rule's Go half, held to shared/tests/latency_conformance.json
// with the Python half: the same verdict and the same reason, character for
// character.

type latencyCase struct {
	Why      string         `json:"why"`
	Measured map[string]any `json:"measured"`
	Expected map[string]any `json:"expected"`
	Verdict  Verdict        `json:"verdict"`
	Reason   string         `json:"reason"`
}

type latencyFixture struct {
	Judged   []latencyCase `json:"judged"`
	Rejected []latencyCase `json:"rejected"`
}

func TestTheLatencyRuleGivesTheFixturesVerdictAndReason(t *testing.T) {
	fixture := readFixture[latencyFixture](t, "latency_conformance.json")
	if len(fixture.Judged) == 0 || len(fixture.Rejected) == 0 {
		t.Fatal("the latency fixture is empty")
	}
	for _, c := range fixture.Judged {
		verdict, reason, err := JudgeLatency(c.Measured, c.Expected)
		if err != nil {
			t.Errorf("%s: %v", c.Why, err)
			continue
		}
		if verdict != c.Verdict || reason != c.Reason {
			t.Errorf("%s:\n got  %s | %s\n want %s | %s", c.Why, verdict, reason, c.Verdict, c.Reason)
		}
	}
	for _, c := range fixture.Rejected {
		if _, _, err := JudgeLatency(c.Measured, c.Expected); err == nil {
			t.Errorf("%s: accepted, want refused", c.Why)
		}
	}
}

func TestTheRanksAreTheBinomialsWorkedByHand(t *testing.T) {
	if lower, upper := LowerRank(20, 50), UpperRank(20, 50); lower != 7 || upper != 14 {
		t.Errorf("p50 of 20: ranks %d and %d, want 7 and 14", lower, upper)
	}
	if UpperRank(45, 95) != 45 || UpperRank(44, 95) != 0 || UpperRank(50, 95) != 50 {
		t.Errorf("the p95 floor is not at 45 samples")
	}
}

func TestMovingABoundOneRankTurnsTheFixtureRed(t *testing.T) {
	fixture := readFixture[latencyFixture](t, "latency_conformance.json")
	for _, shift := range []string{"lower", "upper"} {
		lower, upper := lowerRank, upperRank
		if shift == "lower" {
			lowerRank = func(n, p int) int {
				if rank := lower(n, p); rank > 0 && rank < n {
					return rank + 1
				}
				return lower(n, p)
			}
		} else {
			upperRank = func(n, p int) int {
				if rank := upper(n, p); rank > 1 {
					return rank - 1
				}
				return upper(n, p)
			}
		}
		differing := 0
		for _, c := range fixture.Judged {
			verdict, reason, err := JudgeLatency(c.Measured, c.Expected)
			if err != nil || verdict != c.Verdict || reason != c.Reason {
				differing++
			}
		}
		lowerRank, upperRank = lower, upper
		if differing == 0 {
			t.Errorf("moving the %s bound one rank changed no case", shift)
		}
	}
}

func latencyReading(verdict Verdict, c latencyCase) Reading {
	return Reading{
		ProbeID: LatencyProbeID, ProbeVersion: 1,
		Target: "http:inventory-service/GET /ready", Environment: "local",
		Verdict: verdict, Measured: c.Measured, Expected: c.Expected, Reason: "r",
		TakenAt: time.Date(2026, 11, 12, 0, 0, 0, 0, time.UTC), AgentID: "culprit-cli",
	}
}

func TestALatencyReadingWhoseVerdictItsSamplesDoNotGiveIsRefused(t *testing.T) {
	fixture := readFixture[latencyFixture](t, "latency_conformance.json")
	for _, c := range fixture.Judged {
		if err := latencyReading(c.Verdict, c).Validate(); err != nil {
			t.Errorf("%s: the rule's own verdict was refused: %v", c.Why, err)
		}
		for _, other := range []Verdict{VerdictPass, VerdictFail, VerdictInconclusive} {
			if other == c.Verdict {
				continue
			}
			err := latencyReading(other, c).Validate()
			if err == nil || !strings.Contains(err.Error(), "its own samples and budget give") {
				t.Errorf("%s: a %s reading was not refused (%v)", c.Why, other, err)
			}
		}
	}
	bare := latencyReading(VerdictPass, latencyCase{Measured: map[string]any{"url": "http://x/ready"}})
	if err := bare.Validate(); err == nil {
		t.Error("a pass latency reading with no samples was accepted")
	}
	bare.Verdict = VerdictInconclusive
	if err := bare.Validate(); err != nil {
		t.Errorf("an inconclusive latency reading with nothing measured was refused: %v", err)
	}
}

type budgetLiteral struct {
	Literal string `json:"literal"`
	Plain   bool   `json:"plain"`
	Refused bool   `json:"refused"`
	Reason  string `json:"reason"`
}

// TestABudgetIsWrittenAsPlainDecimalDigits: the shared fixture's literals,
// the same refusals and reasons Python gives (Phase 36 part 2).
func TestABudgetIsWrittenAsPlainDecimalDigits(t *testing.T) {
	fixture := readFixture[struct {
		Literals []budgetLiteral `json:"budget_literals"`
	}](t, "latency_conformance.json")
	if len(fixture.Literals) == 0 {
		t.Fatal("the fixture has no budget_literals")
	}
	for _, c := range fixture.Literals {
		got := BudgetLiteralProblem(c.Literal, c.Plain)
		if c.Refused && got != c.Reason {
			t.Errorf("%q (plain %v): %q, want %q", c.Literal, c.Plain, got, c.Reason)
		}
		if !c.Refused && got != "" {
			t.Errorf("%q: refused (%s), want accepted", c.Literal, got)
		}
	}
}
