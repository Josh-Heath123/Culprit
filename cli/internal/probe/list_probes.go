package probe

import (
	"context"
	"fmt"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/probe/guardedhttp"
)

// --- probe.http.response_items -------------------------------------------
//
// Phase 38 part 2 (docs/PERFORMANCE_PLAN.md, "Part 2 — lists", decision 4).
// How many items a list route answers, against the `response_items_max`
// budget declared for it, judged by model.JudgeResponseItems — the rule
// shared/culprit_model/lists.py holds too, so the verdict is a pure
// function of the reading.
//
//   - One GET, under the refusals probe.http.latency has: GET only, the
//     url on the budgeted route with no query, fragment or userinfo
//     (urlOffRoute), no header and so no credential, no redirect followed,
//     through the guarded client.
//   - It counts the items of the array at the budget's `at:` (the top
//     level when there is none).
//   - It keeps the count only: never an item, a key or a value.
//     guardedhttp.CountItems returns nothing else.
//   - pass within the bound, fail over it, inconclusive, saying why, when
//     the answer is not 2xx, not JSON, larger than the read cap, or holds
//     no array at `at:`.
//
// It is run from `culprit probe` against budgeted routes, and is not a
// hypothesis in the walk: §2's hypotheses have none for lists, and Phase
// 39 decides what an unbounded list costs.

// ItemCounter counts the array a GET answers. RealHTTPClient implements
// it; an HTTPClient that does not cannot count, and the probe says so.
type ItemCounter interface {
	CountItems(ctx context.Context, url string, tokens []string) (ItemCount, error)
}

// ItemCount is one counted response.
type ItemCount = guardedhttp.ItemCount

type httpResponseItems struct{}

func (httpResponseItems) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		// A literal, so api/tests/test_probes_api.py can read it; held equal
		// to model.ResponseItemsProbeID by its test.
		ID:           "probe.http.response_items",
		Verdicts:     allVerdicts,
		Version:      1,
		Effect:       model.EffectInterrogate,
		Capabilities: []string{"net.http.outbound"},
		TimeoutMS:    15_000,
		ExpectedFrom: model.PlaneIntent,
		Produces: []model.Produces{
			{SubjectTemplate: "http:{component}/{method} {path}", Predicate: "response_items_max"},
		},
		Cost: model.CostCheap,
		Inputs: map[string]any{
			"type": "object",
			"properties": map[string]any{
				// Either a full url, or an http: target plus base_url, as
				// probe.http.latency takes them.
				"url":      map[string]any{"type": "string"},
				"base_url": map[string]any{"type": "string"},
				"method":   map[string]any{"type": "string"},
			},
		},
	}
}

var notCountedKnown = map[string]bool{
	model.NotCountedStatus: true, model.NotCountedNotJSON: true,
	model.NotCountedNoArray: true, model.NotCountedTooLarge: true,
}

func (httpResponseItems) Run(ctx context.Context, request Request, deps Deps) Outcome {
	url, method, problem := routeOf(request)
	if problem != "" {
		return inconclusive(problem)
	}
	if !strings.EqualFold(method, "GET") {
		return inconclusive(fmt.Sprintf(
			"%s %s is not a GET route, and this probe sends GET only: nothing was sent",
			strings.ToUpper(method), url))
	}
	if request.Expectation == nil {
		return withoutExpectation(request, nil, "no request was sent")
	}
	// The budget's own subject says which route it is on, whatever the
	// inputs say, as for probe.http.latency.
	kind, parts, err := model.ParseSubject(request.Expectation.Subject)
	if err != nil || kind != model.KindHTTP {
		return inconclusive("the budget is not on an http: route, so there is no list to count")
	}
	if !strings.EqualFold(parts["method"], "GET") {
		return inconclusive(fmt.Sprintf(
			"the budget is on %s %s, which is not a GET route, and this probe sends GET only: "+
				"nothing was sent", parts["method"], parts["path"]))
	}
	if problem := urlOffRoute(url, parts); problem != "" {
		return inconclusive(problem + ": nothing was sent")
	}
	bound, at, valid := model.ListBudget(request.Expectation.Value)
	if !valid {
		return inconclusive(fmt.Sprintf(
			"the budget for %s is not a whole number of items from 1 to %d with a JSON pointer: "+
				"nothing was sent", url, model.MaxListItems))
	}
	counter, ok := deps.HTTP.(ItemCounter)
	if !ok {
		return inconclusive("no HTTP client that can count a list is available to this agent")
	}
	count, err := counter.CountItems(ctx, url, model.PointerTokens(at))
	if err != nil {
		return inconclusive(fmt.Sprintf("the GET did not complete (%v), so no list was counted", err))
	}

	measured := map[string]any{"url": url, "method": "GET", "at": at, "status": count.Status}
	switch {
	case count.Counted:
		measured["items"] = count.Items
	case notCountedKnown[count.NotCounted]:
		measured["not_counted"] = count.NotCounted
	default:
		return inconclusive("the response could not be counted; this is a bug in the probe")
	}
	expected := map[string]any{"response_items_max": bound, "at": at}
	verdict, reason, err := model.JudgeResponseItems(measured, expected)
	if err != nil {
		return inconclusive(fmt.Sprintf("the count could not be judged (%v); this is a bug in the probe", err))
	}
	return Outcome{
		Verdict: verdict, Measured: measured, Expected: expected,
		ExpectedSource: provenanceOf(request.Expectation), Reason: reason,
	}
}
