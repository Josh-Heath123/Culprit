package model

import (
	"encoding/json"
	"fmt"
	"math"
	"math/big"
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

// BudgetPredicates are the predicates a budget may name, with the
// percentile each declares. A closed set, grown one phase at a time (P1).
var BudgetPredicates = map[string]int{
	"latency_p50_ms": 50,
	"latency_p95_ms": 95,
}

// LatencyShapeError is a measurement that is not the rule's input.
type LatencyShapeError struct{ Message string }

func (e *LatencyShapeError) Error() string { return e.Message }

func shapeError(format string, args ...any) error {
	return &LatencyShapeError{Message: fmt.Sprintf(format, args...)}
}

// wholeNumber accepts what a measurement map can hold for a count: an int
// from a probe, or a float64 with no fraction from decoded JSON.
func wholeNumber(value any, name string, minimum int) (int, error) {
	var number int
	switch typed := value.(type) {
	case int:
		number = typed
	case int64:
		number = int(typed)
	case float64:
		if typed != math.Trunc(typed) || math.IsInf(typed, 0) || math.Abs(typed) > 1e15 {
			return 0, shapeError("%s must be a whole number", name)
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
	return number, nil
}

// LatencyInputs are the rule's inputs, validated.
type LatencyInputs struct {
	Percentile int
	BudgetMS   int
	Requests   int
	SamplesUS  []int
	Timeouts   int
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
		sample, err := wholeNumber(item, "a sample", 0)
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
	if in.BudgetMS, err = wholeNumber(expected[declared[0]], "the budget", 1); err != nil {
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
var LowerRank = func(n, percentile int) int {
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

// UpperRank is the smallest rank u with P(Binomial(n, p) <= u-1) at
// LatencyConfidence, or 0 when there is none.
var UpperRank = func(n, percentile int) int {
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
	if n == 0 {
		return VerdictInconclusive, fmt.Sprintf(
			"no sample: none of %d requests answered 2xx or timed out, so p%d was not measured",
			in.Requests, p), nil
	}
	over := func(value int) bool { return value == timeoutSample || value > limit }

	lower := LowerRank(n, p)
	upper := UpperRank(n, p)
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
