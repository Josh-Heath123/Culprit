package probe

import (
	"context"
	"fmt"
	neturl "net/url"
	"strings"
	"sync"
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
// budgetMS is at most model.MaxBudgetMS, so this cannot overflow.
func latencyTimeout(budgetMS int) time.Duration {
	return time.Duration(2*budgetMS)*time.Millisecond + 500*time.Millisecond
}

// latencyRuns lets one latency run at a time send requests from this
// process. The runner runs probes concurrently, and the same probe named
// twice (`-p probe.http.latency -p probe.http.latency`, or a list over
// culprit_probe) would otherwise send two runs' requests interleaved, a
// fraction of a millisecond apart (found by the Phase 36 phase audit).
var latencyRuns sync.Mutex

// latencyLastEnded is when this process's last latency request ended,
// guarded by latencyRuns: the spacing holds between runs as well as within
// one.
var latencyLastEnded time.Time

// runMargin is kept clear of the run's deadline, so no request is cut off
// by it: one cut off measured nothing.
const runMargin = 100 * time.Millisecond

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
	// The budget's own subject says which route it is on, whatever the
	// inputs say: a `url` input with no `method`, or `method=GET`, against
	// a POST route's budget would otherwise time GETs and judge them
	// against it (found by the Phase 36 phase audit).
	if kind, parts, err := model.ParseSubject(request.Expectation.Subject); err != nil || kind != model.KindHTTP {
		return inconclusive("the budget is not on an http: route, so there is no route to time")
	} else if !strings.EqualFold(parts["method"], "GET") {
		return inconclusive(fmt.Sprintf(
			"the budget is on %s %s, which is not a GET route, and this probe sends GET only: "+
				"nothing was sent, so its latency cannot be measured", parts["method"], parts["path"]))
	} else if !urlIsOnRoute(url, parts) {
		// The path too: a url input naming another route would have that
		// route's times judged against this budget (re-audit, Phase 36).
		return inconclusive(fmt.Sprintf(
			"the url's path is not %s, the route the budget is on: nothing was sent", parts["path"]))
	}
	predicate := request.Expectation.Predicate
	percentile, known := model.BudgetPredicates[predicate]
	budget, valid := wholeMilliseconds(request.Expectation.Value)
	if !known || !valid {
		return inconclusive(fmt.Sprintf(
			"the budget for %s is not a whole number of milliseconds from 1 to %d under a budget "+
				"predicate: nothing was sent", url, model.MaxBudgetMS))
	}
	timer, ok := deps.HTTP.(Timer)
	if !ok {
		return inconclusive("no HTTP client that can time a request is available to this agent")
	}

	latencyRuns.Lock()
	defer latencyRuns.Unlock()

	count := latencyRequests[percentile]
	if count > model.LatencyMaxRequests {
		count = model.LatencyMaxRequests
	}
	limit := time.Duration(budget) * time.Millisecond
	samples := make([]int, 0, count)
	connects := make([]int, 0, count)
	requests, timeouts, refused := 0, 0, 0
	for requests < count {
		if wait := LatencySpacing - time.Since(latencyLastEnded); wait > 0 && !pause(ctx, wait) {
			break
		}
		// A request's timeout is cut to what the run has left, never past
		// the run's deadline: a request cut off by the deadline measured
		// nothing. It must still be longer than the budget, or a timeout
		// would not mean "slower than the budget" — when it cannot be, the
		// run stops.
		timeout := latencyTimeout(budget)
		if deadline, bounded := ctx.Deadline(); bounded {
			if left := time.Until(deadline) - runMargin; left < timeout {
				timeout = left
			}
		}
		if timeout <= limit {
			break
		}
		timing, err := timer.TimeGet(ctx, url, timeout)
		latencyLastEnded = time.Now()
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

	if requests == 0 {
		return inconclusive(fmt.Sprintf(
			"no request was sent: the probe's run could not give one request longer than the "+
				"%d ms budget before its own deadline", budget))
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

// urlIsOnRoute reports whether a URL's path is the budgeted route's path,
// canonicalised by the subject builder as every route is, a declared
// template (`/orders/{}`) matching a concrete path.
func urlIsOnRoute(raw string, route model.Parts) bool {
	parsed, err := neturl.Parse(raw)
	if err != nil || parsed.Path == "" {
		return false
	}
	built, err := model.BuildSubject(model.KindHTTP, model.Parts{
		"component": route["component"], "method": "GET", "path": parsed.Path,
	})
	if err != nil {
		return false
	}
	_, concrete, err := model.ParseSubject(built)
	if err != nil {
		return false
	}
	_, matches := pathMatches(route["path"], concrete["path"])
	return matches
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

// wholeMilliseconds reads a budget fact's value: a whole number of
// milliseconds, 1 to model.MaxBudgetMS, as every loader holds it.
func wholeMilliseconds(value any) (int, bool) {
	var whole int
	switch typed := value.(type) {
	case int:
		whole = typed
	case int64:
		if typed < 1 || typed > model.MaxBudgetMS {
			return 0, false
		}
		whole = int(typed)
	case float64:
		if typed < 1 || typed > model.MaxBudgetMS || typed != float64(int(typed)) {
			return 0, false
		}
		whole = int(typed)
	default:
		return 0, false
	}
	return whole, whole >= 1 && whole <= model.MaxBudgetMS
}
