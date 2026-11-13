package model

import (
	"encoding/json"
	"fmt"
	"math"
	"math/big"
	"regexp"
	"sort"
)

// The latency rule — Phase 36 part 1, the Go half of
// shared/culprit_model/latency.py.
//
// A declared budget is the reference a measured latency diverges from
// (docs/PERFORMANCE_PLAN.md §0.1, P2). The verdict of a probe.http.latency
// reading is a pure function of its own samples and its budget, so
// Reading.Validate refuses one whose verdict this does not give.
//
// Integer arithmetic only: samples are whole microseconds, a percentile is
// the nearest-rank order statistic, and its bounds are the order
// statistics at the ranks the exact binomial gives for Confidence percent
// on each side — 100^n and binomial coefficients in math/big, so Go and
// Python cannot disagree in a last digit. Both are held to
// shared/tests/latency_conformance.json, verdicts and reasons alike.

// LatencyProbeID is the probe whose readings the rule judges.
const LatencyProbeID = "probe.http.latency"

// LatencyConfidence is each one-sided bound's confidence, in percent.
const LatencyConfidence = 90

// LatencyMaxRequests is the most requests one latency reading may record:
// the probe's hard cap.
const LatencyMaxRequests = 50

// MaxBudgetMS is the largest budget, in milliseconds: a bound on what can
// be declared, not a threshold anything is judged by. The probe's whole
// run is 120 s, and a request must be able to take longer than the budget
// for a timeout to mean "slower than the budget". Python holds the same.
const MaxBudgetMS = 60_000

// MaxSampleUS is the largest sample, in microseconds: no request is timed
// past the probe's run, so anything above this is not a measurement.
const MaxSampleUS = 1_000_000_000

// BudgetPredicates are the predicates a budget may name, with the
// percentile each declares. A closed set, grown one phase at a time (P1).
var BudgetPredicates = map[string]int{
	"latency_p50_ms": 50,
	"latency_p95_ms": 95,
}

// StatementBudgetPredicates are the predicates a budget on a database may
// name (Phase 37 part 2): the mean execution time, in whole milliseconds, a
// normalised statement may take. On a table (`schema:<database>/<ns>.<table>`)
// or on the database's component. Kept apart from BudgetPredicates, which
// the latency walk reads as percentiles of a route.
var StatementBudgetPredicates = map[string]bool{"query_mean_ms_max": true}

// plainDecimal is a budget as written in culprit.yaml: plain decimal
// digits, no sign, no leading zero.
var plainDecimal = regexp.MustCompile(`^[1-9][0-9]*$`)

// BudgetLiteralProblem says why a budget's value, as written in YAML, is
// not a plain decimal integer, or "" when it is. plain is whether the
// scalar was written unquoted, with no tag or alias.
//
// Phase 36 part 2: the two YAML readers of one INTENT value read some
// forms differently — YAML 1.1 (PyYAML) reads `0454` as octal 300 and
// `300_000` as 300000, YAML 1.2 (yaml.v3) reads `1e3` as 1000 and `0o454`
// as 300. Two readers must not read two values, so both refuse every form
// but this one, each from latency_conformance.json's budget_literals. The
// Python half is culprit_model.latency.budget_literal_problem.
func BudgetLiteralProblem(literal string, plain bool) string {
	if !plain {
		return "a budget is written as plain decimal digits, without quotes, a tag or an alias"
	}
	if !plainDecimal.MatchString(literal) {
		// Never the literal itself: error text is output, and a value
		// pasted in the wrong place can be a credential (invariant 7).
		return "a budget is written as plain decimal digits, and this value is not"
	}
	return ""
}

// BudgetMergeProblem is the refusal of a budget entry with a merge key
// (`<<`): the fields it brings in are not checked for their form, so both
// readers refuse it (latency_conformance.json's budget_entries). Python
// holds the same sentence as BUDGET_MERGE_PROBLEM.
const BudgetMergeProblem = "a budget entry is written out in full: a merge key (<<) is not read"

// LatencyShapeError is a measurement that is not the rule's input.
type LatencyShapeError struct{ Message string }

func (e *LatencyShapeError) Error() string { return e.Message }

func shapeError(format string, args ...any) error {
	return &LatencyShapeError{Message: fmt.Sprintf(format, args...)}
}

// wholeNumber accepts what a measurement map can hold for a count: an int
// from a probe, or a float64 with no fraction from decoded JSON.
func wholeNumber(value any, name string, minimum int) (int, error) {
	return boundedNumber(value, name, minimum, math.MaxInt32)
}

// boundedNumber is wholeNumber with a largest value. Bounded at most at
// MaxInt32, so a float decoded from JSON converts exactly and Python, whose
// ints are unbounded, is held to the same numbers.
func boundedNumber(value any, name string, minimum, maximum int) (int, error) {
	var number int
	switch typed := value.(type) {
	case int:
		number = typed
	case int64:
		if typed > math.MaxInt32 || typed < math.MinInt32 {
			return 0, shapeError("%s must be at most %d", name, maximum)
		}
		number = int(typed)
	case float64:
		if typed != math.Trunc(typed) || math.IsInf(typed, 0) || math.IsNaN(typed) {
			return 0, shapeError("%s must be a whole number", name)
		}
		if math.Abs(typed) > math.MaxInt32 {
			return 0, shapeError("%s must be at most %d", name, maximum)
		}
		number = int(typed)
	case json.Number:
		parsed, err := typed.Int64()
		if err != nil {
			return 0, shapeError("%s must be a whole number", name)
		}
		number = int(parsed)
	default:
		return 0, shapeError("%s must be a whole number of at least %d", name, minimum)
	}
	if number < minimum {
		return 0, shapeError("%s must be a whole number of at least %d", name, minimum)
	}
	if number > maximum {
		return 0, shapeError("%s must be at most %d", name, maximum)
	}
	return number, nil
}

// LatencyInputs are the rule's inputs, validated.
type LatencyInputs struct {
	Percentile int
	BudgetMS   int
	Requests   int
	SamplesUS  []int
	Timeouts   int
	// Planned is how many requests the run set out to send; required. A run
	// cut short by its deadline is judged inconclusive (Phase 36 part 2):
	// the count stays fixed, and nothing stops early.
	Planned int
}

// ParseLatencyInputs reads the rule's inputs from a reading's measured and
// expected maps.
func ParseLatencyInputs(measured, expected map[string]any) (LatencyInputs, error) {
	var in LatencyInputs
	var err error
	if in.Percentile, err = wholeNumber(measured["percentile"], "percentile", 0); err != nil {
		return in, err
	}
	known := false
	for _, percentile := range BudgetPredicates {
		known = known || percentile == in.Percentile
	}
	if !known {
		return in, shapeError("percentile %d is not one a budget can declare", in.Percentile)
	}
	if in.Requests, err = wholeNumber(measured["requests"], "requests", 0); err != nil {
		return in, err
	}
	if in.Requests > LatencyMaxRequests {
		return in, shapeError("requests %d is over the cap of %d", in.Requests, LatencyMaxRequests)
	}
	// Required since Phase 37 part 1 (probe version 2): a reading without
	// it would be judged on its samples alone, so a run cut short could
	// pass or fail on fewer requests than it set out to send.
	planned, stated := measured["planned"]
	if !stated {
		return in, shapeError("planned must say how many requests the run set out to send")
	}
	if in.Planned, err = boundedNumber(planned, "planned", 1, LatencyMaxRequests); err != nil {
		return in, err
	}
	if in.Requests > in.Planned {
		return in, shapeError("requests %d is more than the %d planned", in.Requests, in.Planned)
	}
	raw, ok := measured["samples_us"].([]any)
	if !ok {
		if typed, isInts := measured["samples_us"].([]int); isInts {
			raw = make([]any, len(typed))
			for index, value := range typed {
				raw[index] = value
			}
		} else {
			return in, shapeError("samples_us must be a list")
		}
	}
	in.SamplesUS = make([]int, 0, len(raw))
	for _, item := range raw {
		sample, err := boundedNumber(item, "a sample", 0, MaxSampleUS)
		if err != nil {
			return in, err
		}
		in.SamplesUS = append(in.SamplesUS, sample)
	}
	if in.Timeouts, err = wholeNumber(measured["timeouts"], "timeouts", 0); err != nil {
		return in, err
	}
	if len(in.SamplesUS)+in.Timeouts > in.Requests {
		return in, shapeError("more samples and timeouts than requests")
	}
	if expected == nil {
		return in, shapeError("a latency reading must carry its budget in expected")
	}
	var declared []string
	for key := range expected {
		if _, isBudget := BudgetPredicates[key]; isBudget {
			declared = append(declared, key)
		}
	}
	if len(declared) != 1 {
		return in, shapeError("expected must name exactly one budget predicate")
	}
	if BudgetPredicates[declared[0]] != in.Percentile {
		return in, shapeError("the budget is %s but p%d was measured", declared[0], in.Percentile)
	}
	if in.BudgetMS, err = boundedNumber(expected[declared[0]], "the budget", 1, MaxBudgetMS); err != nil {
		return in, err
	}
	return in, nil
}

// binomialTerms returns C(n,i) * p^i * (100-p)^(n-i) for i = 0..n, and
// 100^n: the binomial probabilities scaled to integers.
func binomialTerms(n, percentile int) ([]*big.Int, *big.Int) {
	terms := make([]*big.Int, n+1)
	p := big.NewInt(int64(percentile))
	q := big.NewInt(int64(100 - percentile))
	for i := 0; i <= n; i++ {
		term := new(big.Int).Binomial(int64(n), int64(i))
		term.Mul(term, new(big.Int).Exp(p, big.NewInt(int64(i)), nil))
		term.Mul(term, new(big.Int).Exp(q, big.NewInt(int64(n-i)), nil))
		terms[i] = term
	}
	total := new(big.Int).Exp(big.NewInt(100), big.NewInt(int64(n)), nil)
	return terms, total
}

// atConfidence reports 100*sum >= LatencyConfidence*total.
func atConfidence(sum, total *big.Int) bool {
	left := new(big.Int).Mul(sum, big.NewInt(100))
	right := new(big.Int).Mul(total, big.NewInt(LatencyConfidence))
	return left.Cmp(right) >= 0
}

// LowerRank is the largest rank l with P(Binomial(n, p) >= l) at
// LatencyConfidence, or 0 when there is none.
func LowerRank(n, percentile int) int { return lowerRank(n, percentile) }

// UpperRank is the smallest rank u with P(Binomial(n, p) <= u-1) at
// LatencyConfidence, or 0 when there is none.
func UpperRank(n, percentile int) int { return upperRank(n, percentile) }

// lowerRank and upperRank are variables only so this package's own test
// can move a bound one rank and watch the fixture turn red. Unexported: no
// other package can swap the rule a reading is validated by.
var lowerRank = func(n, percentile int) int {
	terms, total := binomialTerms(n, percentile)
	tail := new(big.Int)
	for rank := n; rank >= 1; rank-- {
		tail.Add(tail, terms[rank])
		if atConfidence(tail, total) {
			return rank
		}
	}
	return 0
}

var upperRank = func(n, percentile int) int {
	terms, total := binomialTerms(n, percentile)
	head := new(big.Int)
	for rank := 1; rank <= n; rank++ {
		head.Add(head, terms[rank-1])
		if atConfidence(head, total) {
			return rank
		}
	}
	return 0
}

// timeoutSample marks a timeout among the ordered samples: slower than any
// answer.
const timeoutSample = -1

func formatSample(microseconds int) string {
	if microseconds == timeoutSample {
		return "a timeout"
	}
	return fmt.Sprintf("%d.%03d ms", microseconds/1000, microseconds%1000)
}

// JudgeLatency is the verdict and reason for a latency measurement against
// its budget. An error means the inputs are not the rule's.
func JudgeLatency(measured, expected map[string]any) (Verdict, string, error) {
	in, err := ParseLatencyInputs(measured, expected)
	if err != nil {
		return "", "", err
	}
	ordered := append([]int(nil), in.SamplesUS...)
	sort.Ints(ordered)
	for i := 0; i < in.Timeouts; i++ {
		ordered = append(ordered, timeoutSample)
	}
	n := len(ordered)
	limit := in.BudgetMS * 1000
	p := in.Percentile
	if in.Requests < in.Planned {
		return VerdictInconclusive, fmt.Sprintf(
			"the run was cut short at its deadline: %d of %d requests were sent, so p%d is not "+
				"judged against the %d ms budget", in.Requests, in.Planned, p, in.BudgetMS), nil
	}
	if n == 0 {
		return VerdictInconclusive, fmt.Sprintf(
			"no sample: none of %d requests answered 2xx or timed out, so p%d was not measured",
			in.Requests, p), nil
	}
	over := func(value int) bool { return value == timeoutSample || value > limit }

	lower := lowerRank(n, p)
	upper := upperRank(n, p)
	if lower > 0 && over(ordered[lower-1]) {
		return VerdictFail, fmt.Sprintf(
			"p%d is over the %d ms budget: at %d%% confidence it is at least %s (sample %d of %d)",
			p, in.BudgetMS, LatencyConfidence, formatSample(ordered[lower-1]), lower, n), nil
	}
	if upper > 0 && !over(ordered[upper-1]) {
		return VerdictPass, fmt.Sprintf(
			"p%d is within the %d ms budget: at %d%% confidence it is at most %s (sample %d of %d)",
			p, in.BudgetMS, LatencyConfidence, formatSample(ordered[upper-1]), upper, n), nil
	}
	low := "no lower bound"
	if lower > 0 {
		low = fmt.Sprintf("at least %s (sample %d)", formatSample(ordered[lower-1]), lower)
	}
	high := "no upper bound"
	if upper > 0 {
		high = fmt.Sprintf("at most %s (sample %d)", formatSample(ordered[upper-1]), upper)
	}
	reason := fmt.Sprintf(
		"p%d cannot be placed against the %d ms budget at %d%% confidence from %d samples: %s, %s",
		p, in.BudgetMS, LatencyConfidence, n, low, high)
	if in.Requests > n {
		reason += fmt.Sprintf("; %d of %d requests did not answer 2xx and are not samples",
			in.Requests-n, in.Requests)
	}
	return VerdictInconclusive, reason, nil
}

// validateLatency is Reading.Validate's latency rule: a probe.http.latency
// reading's verdict must be the one its own samples and budget give.
func (r Reading) validateLatency() error {
	if r.ProbeID != LatencyProbeID || r.Verdict == VerdictRefused {
		return nil
	}
	if _, measured := r.Measured["samples_us"]; !measured {
		if r.Verdict != VerdictInconclusive {
			return fmt.Errorf(
				"a %s latency reading must carry the samples it was judged on", r.Verdict)
		}
		return nil
	}
	verdict, _, err := JudgeLatency(r.Measured, r.Expected)
	if err != nil {
		return fmt.Errorf("a latency reading's measurement is not the rule's input: %w", err)
	}
	if verdict != r.Verdict {
		return fmt.Errorf(
			"a latency reading says %s, but its own samples and budget give %s", r.Verdict, verdict)
	}
	return nil
}

// LatencySplit is one latency reading judged twice more, against the same
// budget by the same rule (Phase 36 part 2): its connection setup alone,
// and the server's own time, which is each answer's total less its setup.
// No new request and no new threshold.
type LatencySplit struct {
	Setup, Server             Verdict
	SetupReason, ServerReason string
}

// SplitLatency derives the two series from a reading's measured values:
//
//   - setup: each answer's connect_us, and each timeout whose connection
//     completed (timeout_connect_us); a timeout before its connection
//     completed counts as slow setup;
//   - server: each answer's total less its setup, and a timeout after its
//     connection completed counts as a slow server. A timeout before the
//     connection completed says nothing about the server, so it is not a
//     sample there.
//
// An error means the reading does not carry the setup of every answer —
// one taken before setup was recorded, or not the rule's input at all.
func SplitLatency(measured, expected map[string]any) (LatencySplit, error) {
	in, err := ParseLatencyInputs(measured, expected)
	if err != nil {
		return LatencySplit{}, err
	}
	connects, err := microsecondList(measured["connect_us"], "connect_us")
	if err != nil {
		return LatencySplit{}, err
	}
	if len(connects) != len(in.SamplesUS) {
		return LatencySplit{}, shapeError("connect_us must give the setup of every answered sample")
	}
	connectedTimeouts, err := microsecondList(measured["timeout_connect_us"], "timeout_connect_us")
	if err != nil {
		return LatencySplit{}, err
	}
	if len(connectedTimeouts) > in.Timeouts {
		return LatencySplit{}, shapeError("more connected timeouts than timeouts")
	}
	server := make([]int, len(in.SamplesUS))
	for index, total := range in.SamplesUS {
		if connects[index] > total {
			return LatencySplit{}, shapeError("an answer's setup is longer than the whole answer")
		}
		server[index] = total - connects[index]
	}
	series := func(samples []int, timeouts int) map[string]any {
		return map[string]any{
			"percentile": in.Percentile, "requests": in.Requests, "planned": in.Planned,
			"samples_us": append([]int(nil), samples...), "timeouts": timeouts,
		}
	}
	setupSamples := append(append([]int(nil), connects...), connectedTimeouts...)
	var split LatencySplit
	if split.Setup, split.SetupReason, err = JudgeLatency(
		series(setupSamples, in.Timeouts-len(connectedTimeouts)), expected); err != nil {
		return LatencySplit{}, err
	}
	if split.Server, split.ServerReason, err = JudgeLatency(
		series(server, len(connectedTimeouts)), expected); err != nil {
		return LatencySplit{}, err
	}
	return split, nil
}

// microsecondList reads a list of whole microseconds from a measurement.
func microsecondList(value any, name string) ([]int, error) {
	var raw []any
	switch typed := value.(type) {
	case []any:
		raw = typed
	case []int:
		raw = make([]any, len(typed))
		for index, item := range typed {
			raw[index] = item
		}
	default:
		return nil, shapeError("%s must be a list", name)
	}
	out := make([]int, 0, len(raw))
	for _, item := range raw {
		number, err := boundedNumber(item, name, 0, MaxSampleUS)
		if err != nil {
			return nil, err
		}
		out = append(out, number)
	}
	return out, nil
}
