package probe

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// --- probe.http.latency ------------------------------------------------
//
// Phase 36 part 1 (docs/PERFORMANCE_PLAN.md, "How Phase 36 is run"). A
// route's latency, measured against the budget INTENT declares for it, and
// judged by the rule in model.JudgeLatency — the same rule Python holds,
// so the verdict is a pure function of the reading.
//
// A latency probe must not become load (§0.4). So:
//
//   - a fixed number of requests — 50 for a p95 budget, 20 for a p50 — and
//     never more than LatencyMaxRequests, enforced here, not configured;
//   - sequential, each at least LatencySpacing after the last one ended;
//   - GET only. A budget on a route that is not GET is inconclusive and
//     nothing is sent: an OPTIONS is answered by CORS middleware before any
//     handler runs, so its time says nothing about the route;
//   - no credential. A route that needs a token answers 401, which is not
//     a sample, so its budget is inconclusive (LIMITS).
//
// A sample is a 2xx answer or a timeout. Anything else measures a refusal,
// not the route. A request that does not answer within its timeout counts
// as slower than the budget: dropping it would report a service that has
// stopped answering as fast.

// LatencySpacing is the least time between one request ending and the next
// starting.
const LatencySpacing = 50 * time.Millisecond

// latencyRequests is how many requests a budget's percentile takes. At 90%
// a p95 can be shown within budget only from 45 samples, so a p95 takes the
// cap; a p50 needs far fewer.
var latencyRequests = map[int]int{50: 20, 95: model.LatencyMaxRequests}

// latencyTimeout is one request's timeout: above the budget, so a timeout
// is always slower than it. The probe's own timeout bounds the whole run.
func latencyTimeout(budgetMS int) time.Duration {
	return time.Duration(2*budgetMS)*time.Millisecond + 500*time.Millisecond
}

type httpLatency struct{}

func (httpLatency) Manifest() model.ProbeManifest {
	route := "http:{component}/{method} {path}"
	return model.ProbeManifest{
		// A literal, so api/tests/test_probes_api.py can read it; held equal to
		// model.LatencyProbeID by TestTheLatencyProbeIsTheOneTheRuleJudges.
		ID:           "probe.http.latency",
		Version:      1,
		Effect:       model.EffectInterrogate,
		Capabilities: []string{"net.http.outbound"},
		// Fifty requests at the budget's timeout, spaced: the whole run is
		// bounded here, and the probe stops early rather than overrun it.
		TimeoutMS:    120_000,
		ExpectedFrom: model.PlaneIntent,
		// p95 first: when a route has both budgets, the stricter one is
		// measured (LIMITS).
		Produces: []model.Produces{
			{SubjectTemplate: route, Predicate: "latency_p95_ms"},
			{SubjectTemplate: route, Predicate: "latency_p50_ms"},
		},
		Cost: model.CostMetered,
		Inputs: map[string]any{
			"type": "object",
			"properties": map[string]any{
				// Either a full url, or an http: target plus base_url, as
				// probe.http.route_conformance takes them.
				"url":      map[string]any{"type": "string"},
				"base_url": map[string]any{"type": "string"},
				"method":   map[string]any{"type": "string"},
			},
		},
	}
}

func (httpLatency) Run(ctx context.Context, request Request, deps Deps) Outcome {
	url, method, problem := routeOf(request)
	if problem != "" {
		return inconclusive(problem)
	}
	if !strings.EqualFold(method, "GET") {
		return inconclusive(fmt.Sprintf(
			"%s %s is not a GET route, and this probe sends GET only: nothing was sent, "+
				"so its latency cannot be measured", strings.ToUpper(method), url))
	}
	if request.Expectation == nil {
		return withoutExpectation(request, nil, "no request was sent")
	}
	predicate := request.Expectation.Predicate
	percentile, known := model.BudgetPredicates[predicate]
	budget, valid := wholeMilliseconds(request.Expectation.Value)
	if !known || !valid {
		return inconclusive(fmt.Sprintf(
			"the budget for %s is not a whole number of milliseconds under a budget predicate", url))
	}
	timer, ok := deps.HTTP.(Timer)
	if !ok {
		return inconclusive("no HTTP client that can time a request is available to this agent")
	}

	count := latencyRequests[percentile]
	if count > model.LatencyMaxRequests {
		count = model.LatencyMaxRequests
	}
	timeout := latencyTimeout(budget)
	samples := make([]int, 0, count)
	connects := make([]int, 0, count)
	requests, timeouts, refused := 0, 0, 0
	for requests < count {
		if requests > 0 && !pause(ctx, LatencySpacing) {
			break
		}
		// Stop rather than overrun the probe's own timeout: a request cut
		// off by the run's deadline measured nothing.
		if deadline, bounded := ctx.Deadline(); bounded && time.Until(deadline) < timeout+LatencySpacing {
			break
		}
		timing, err := timer.TimeGet(ctx, url, timeout)
		if ctx.Err() != nil {
			break
		}
		requests++
		switch {
		case err != nil:
			refused++
		case timing.TimedOut:
			timeouts++
		case timing.Status >= 200 && timing.Status < 300:
			samples = append(samples, int(timing.Total.Microseconds()))
			connects = append(connects, int(timing.Connect.Microseconds()))
		default:
			refused++
		}
	}

	measured := map[string]any{
		"url": url, "method": "GET", "percentile": percentile,
		"requests": requests, "samples_us": samples, "timeouts": timeouts,
		// Connection setup per answered sample, in the same order: what one
		// sample measured, recorded separately (part 2 needs it).
		"connect_us": connects,
		// Requests that answered other than 2xx or failed outright: not
		// samples, and counted so the reading says why there are few.
		"not_samples": refused,
	}
	expected := map[string]any{predicate: budget}
	verdict, reason, err := model.JudgeLatency(measured, expected)
	if err != nil {
		return inconclusive(fmt.Sprintf("the measurement could not be judged (%v); this is a bug in the probe", err))
	}
	return Outcome{
		Verdict: verdict, Measured: measured, Expected: expected,
		ExpectedSource: provenanceOf(request.Expectation), Reason: reason,
	}
}

// pause waits, or reports false when the run ends first.
func pause(ctx context.Context, wait time.Duration) bool {
	timer := time.NewTimer(wait)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-timer.C:
		return true
	}
}

// wholeMilliseconds reads a budget fact's value.
func wholeMilliseconds(value any) (int, bool) {
	switch typed := value.(type) {
	case int:
		return typed, typed > 0
	case int64:
		return int(typed), typed > 0
	case float64:
		whole := int(typed)
		return whole, typed > 0 && float64(whole) == typed && typed < 1<<31
	}
	return 0, false
}
