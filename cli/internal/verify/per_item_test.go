package verify

import (
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// perItemReading is a statements_per_request reading naming the given
// queryids as run per item.
func perItemReading(verdict model.Verdict, named ...string) model.Reading {
	reading := model.Reading{ProbeID: model.StatementsPerRequestProbeID, Verdict: verdict,
		Measured: map[string]any{"per_item": append([]string{}, named...)}}
	if verdict != model.VerdictPass {
		reading.Reason = "the quiet window was not quiet"
	}
	return reading
}

func nPlusOneInvestigation(status model.HypothesisStatus) model.Investigation {
	return model.Investigation{
		Hypotheses: []model.Hypothesis{{ID: "h1", Kind: model.HypothesisNPlusOne, Status: status,
			Subject: "http:inventory-service/GET /products/details", Readings: []string{"r2", "r1"}}},
		Readings: []model.InvestigationReading{
			{ID: "r1", Reading: model.Reading{ProbeID: model.LatencyProbeID, Verdict: model.VerdictFail}},
			{ID: "r2", Reading: perItemReading(model.VerdictPass, "7777")},
		},
	}
}

// TestTheDescriptionSaysWhetherTheStatementStillRunsPerItem: from the two
// rerun per-item readings, whether the statement the N+1 root cited still
// runs once per item (decision 9); nothing is said without an N+1 root.
func TestTheDescriptionSaysWhetherTheStatementStillRunsPerItem(t *testing.T) {
	rerun := func(first, second model.Reading) []model.Rerun {
		return []model.Rerun{{ReadingID: "r2", Runs: [2]model.Reading{first, second}}}
	}
	pass := func(named ...string) model.Reading { return perItemReading(model.VerdictPass, named...) }
	inv := nPlusOneInvestigation(model.HypothesisSupported)
	for name, c := range map[string]struct {
		reran []model.Rerun
		want  string
	}{
		"fixed":     {rerun(pass(), pass()), "statement 7777, which ran once per item at diagnosis (r2), no longer runs once per item on either run"},
		"not fixed": {rerun(pass("7777"), pass("7777")), "still runs once per item on both runs"},
		"flips":     {rerun(pass("7777"), pass()), "on one run and not on the other"},
		"another":   {rerun(pass("8888"), pass("8888")), "no longer runs once per item on either run"},
		"unsettled": {rerun(pass(), perItemReading(model.VerdictInconclusive)), "could not be measured again on both runs: inconclusive"},
	} {
		if got := perItemNote(inv, c.reran); !strings.Contains(got, c.want) || !strings.HasPrefix(got, "; ") {
			t.Errorf("%s: %q, want it to say %q", name, got, c.want)
		}
	}
	for _, status := range []model.HypothesisStatus{model.HypothesisRuledOut, model.HypothesisUnexplored} {
		if got := perItemNote(nPlusOneInvestigation(status), rerun(pass("7777"), pass("7777"))); got != "" {
			t.Errorf("an N+1 hypothesis %s gave a note: %q", status, got)
		}
	}
}
