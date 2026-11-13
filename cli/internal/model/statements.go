package model

import (
	"fmt"
	"math"
)

// The statement rule (Phase 37 part 2, docs/PERFORMANCE_PLAN.md: "Part 2 —
// statements and plans"). probe.db.statement_budget takes two snapshots of
// pg_stat_statements, a fixed window apart, in one session; for each
// statement it has the change in calls and in total execution time, in whole
// microseconds. The rule is integer comparison, nothing else:
//
//   - over budget when total_us > budget_ms × 1000 × calls;
//   - within budget otherwise;
//   - inconclusive when the statistics were reset, or a statement evicted,
//     during the window, or when no call to a budgeted statement fell in it.
//
// There is no interval: pg_stat_statements keeps no per-call samples, so a
// band would be a number Culprit chose. The reading shows the calls, and
// LIMITS says that a mean of few calls is a mean of few calls.
//
// culprit_model/statements.py holds the same rule, and
// shared/tests/statement_conformance.json holds the two to one answer. A
// reading's verdict is re-judged from its integers by Reading.Validate, in
// Python and at POST /readings.

// StatementProbeID is the probe whose readings the statement rule judges.
const StatementProbeID = "probe.db.statement_budget"

// PlanProbeID is the planner probe: evidence, with no expectation.
const PlanProbeID = "probe.db.plan"

// StatementReadingMax is the most statements one reading keeps, those over
// budget first, then by time in the window; the rest are counted.
const StatementReadingMax = 20

// maxStatementCalls is boundedNumber's own ceiling: a call count, like every
// count a reading holds, is at most 2^31-1, so budget × 1000 × calls fits int64.
const maxStatementCalls = math.MaxInt32

// StatementInputs is one statement as the rule reads it.
type StatementInputs struct {
	QueryID  string
	Calls    int
	TotalUS  int
	BudgetMS int // 0 when no budget applies: not judged
}

// ParseStatementInputs reads a statement reading's measurement.
func ParseStatementInputs(measured map[string]any) (bool, []StatementInputs, error) {
	reset, ok := measured["reset_during_window"].(bool)
	if !ok {
		return false, nil, shapeError("reset_during_window must be true or false")
	}
	raw, ok := measured["statements"].([]any)
	if !ok {
		if typed, isTyped := measured["statements"].([]map[string]any); isTyped {
			for _, item := range typed {
				raw = append(raw, item)
			}
		} else {
			return false, nil, shapeError("statements must be a list")
		}
	}
	if len(raw) > StatementReadingMax {
		return false, nil, shapeError("a reading keeps at most %d statements", StatementReadingMax)
	}
	out := make([]StatementInputs, 0, len(raw))
	for index, item := range raw {
		statement, ok := item.(map[string]any)
		if !ok {
			return false, nil, shapeError("statements[%d] must be an object", index)
		}
		queryID, ok := statement["queryid"].(string)
		if !ok || queryID == "" {
			return false, nil, shapeError("statements[%d].queryid must be text", index)
		}
		calls, err := boundedNumber(statement["calls"], fmt.Sprintf("statements[%d].calls", index), 1, maxStatementCalls)
		if err != nil {
			return false, nil, err
		}
		total, err := wholeNumber(statement["total_us"], fmt.Sprintf("statements[%d].total_us", index), 0)
		if err != nil {
			return false, nil, err
		}
		budget := 0
		if value, present := statement["budget_ms"]; present {
			budget, err = boundedNumber(value, fmt.Sprintf("statements[%d].budget_ms", index), 1, MaxBudgetMS)
			if err != nil {
				return false, nil, err
			}
		}
		out = append(out, StatementInputs{QueryID: queryID, Calls: calls, TotalUS: total, BudgetMS: budget})
	}
	return reset, out, nil
}

// statementOver is the rule's comparison: integers, no division.
func statementOver(s StatementInputs) bool {
	return int64(s.TotalUS) > int64(s.BudgetMS)*1000*int64(s.Calls)
}

// JudgeStatements is the verdict and reason for a statement window.
func JudgeStatements(measured map[string]any) (Verdict, string, error) {
	reset, statements, err := ParseStatementInputs(measured)
	if err != nil {
		return "", "", err
	}
	if reset {
		return VerdictInconclusive, "pg_stat_statements was reset, or a statement evicted from it, " +
			"during the window, so no change over it can be trusted", nil
	}
	judged := 0
	for _, statement := range statements {
		if statement.BudgetMS == 0 {
			continue
		}
		judged++
		if statementOver(statement) {
			return VerdictFail, fmt.Sprintf(
				"statement %s is over its %d ms budget: %d µs over %d call(s) in the window, "+
					"more than %d ms each", statement.QueryID, statement.BudgetMS,
				statement.TotalUS, statement.Calls, statement.BudgetMS), nil
		}
	}
	if judged == 0 {
		return VerdictInconclusive, "no call to a statement with a budget fell in the window", nil
	}
	return VerdictPass, fmt.Sprintf(
		"every one of %d budgeted statement(s) called in the window is within its budget", judged), nil
}

// validateStatements is Reading.Validate's statement rule: a
// probe.db.statement_budget reading's verdict must be the one its own
// integers give.
func (r Reading) validateStatements() error {
	if r.ProbeID != StatementProbeID || r.Verdict == VerdictRefused {
		return nil
	}
	if _, measured := r.Measured["statements"]; !measured {
		if r.Verdict != VerdictInconclusive {
			return fmt.Errorf("a %s statement reading must carry the statements it was judged on", r.Verdict)
		}
		return nil
	}
	verdict, _, err := JudgeStatements(r.Measured)
	if err != nil {
		return fmt.Errorf("a statement reading's measurement is not the rule's input: %w", err)
	}
	if verdict != r.Verdict {
		return fmt.Errorf("a statement reading says %s, but its own integers give %s", r.Verdict, verdict)
	}
	return nil
}
