package probe

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// probe.http.latency against a real server with controlled delays,
// counting every request at the server (Phase 36 part 1's criteria).

// countingServer answers each request by its arrival number, and records
// what arrived and when.
type countingServer struct {
	*httptest.Server
	mu       sync.Mutex
	arrivals []time.Time
	methods  []string
	bodies   int
	headers  []http.Header
}

func newCountingServer(t *testing.T, answer func(n int, w http.ResponseWriter)) *countingServer {
	t.Helper()
	server := &countingServer{}
	server.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		server.mu.Lock()
		n := len(server.arrivals)
		server.arrivals = append(server.arrivals, time.Now())
		server.methods = append(server.methods, r.Method)
		server.headers = append(server.headers, r.Header.Clone())
		if body, _ := io.ReadAll(r.Body); len(body) > 0 {
			server.bodies++
		}
		server.mu.Unlock()
		answer(n, w)
	}))
	t.Cleanup(server.Close)
	return server
}

func (s *countingServer) count() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.arrivals)
}

// closestGap is the least time between two consecutive arrivals.
func (s *countingServer) closestGap() time.Duration {
	s.mu.Lock()
	defer s.mu.Unlock()
	closest := time.Duration(-1)
	for index := 1; index < len(s.arrivals); index++ {
		gap := s.arrivals[index].Sub(s.arrivals[index-1])
		if closest < 0 || gap < closest {
			closest = gap
		}
	}
	return closest
}

// neverSentAnythingButAPlainGET is the probe's other promise: no OPTIONS,
// no HEAD, no body, no credential.
func (s *countingServer) neverSentAnythingButAPlainGET(t *testing.T) {
	t.Helper()
	s.mu.Lock()
	defer s.mu.Unlock()
	for index, method := range s.methods {
		if method != http.MethodGet {
			t.Errorf("request %d was %s", index, method)
		}
	}
	if s.bodies > 0 {
		t.Errorf("%d request(s) carried a body", s.bodies)
	}
	for index, header := range s.headers {
		for _, name := range []string{"Authorization", "Cookie", "Proxy-Authorization", "X-Api-Key"} {
			if header.Get(name) != "" {
				t.Errorf("request %d carried %s", index, name)
			}
		}
	}
}

func delayed(delay func(n int) time.Duration, status func(n int) int) func(int, http.ResponseWriter) {
	return func(n int, w http.ResponseWriter) {
		time.Sleep(delay(n))
		w.WriteHeader(status(n))
		_, _ = w.Write([]byte(`{"status":"ready"}`))
	}
}

func constant(value time.Duration) func(int) time.Duration {
	return func(int) time.Duration { return value }
}
func always(status int) func(int) int { return func(int) int { return status } }

func measureLatency(t *testing.T, server *countingServer, budget *model.Fact, inputs map[string]any,
	overrides map[string]extractOverride,
) model.Reading {
	t.Helper()
	if inputs == nil {
		inputs = map[string]any{}
	}
	inputs["url"] = server.URL + "/ready"
	options := Options{Ledger: grantEverything(t), Deps: Deps{HTTP: NewRealHTTPClient(5 * time.Second), Now: time.Now}}
	if overrides != nil {
		options.Overrides = toOverrides(overrides)
	}
	readings := NewRunner(options).Run(context.Background(), []Request{{
		ProbeID: model.LatencyProbeID, Target: "component:inventory-service",
		Environment: "local", Inputs: inputs, Expectation: budget,
	}})
	if len(readings) != 1 {
		t.Fatalf("%d readings", len(readings))
	}
	if err := readings[0].Validate(); err != nil {
		t.Fatalf("the reading does not validate: %v", err)
	}
	return readings[0]
}

func p50(ms int) *model.Fact {
	return declaredAs("http:inventory-service/GET /ready", "latency_p50_ms", ms)
}

func TestTheLatencyProbeAgainstAServerWithControlledDelays(t *testing.T) {
	t.Run("well under the budget passes", func(t *testing.T) {
		server := newCountingServer(t, delayed(constant(0), always(200)))
		reading := measureLatency(t, server, p50(300), nil, nil)
		if reading.Verdict != model.VerdictPass || server.count() != 20 {
			t.Errorf("%s after %d requests: %s", reading.Verdict, server.count(), reading.Reason)
		}
		server.neverSentAnythingButAPlainGET(t)
	})
	t.Run("well over the budget fails", func(t *testing.T) {
		server := newCountingServer(t, delayed(constant(120*time.Millisecond), always(200)))
		reading := measureLatency(t, server, p50(40), nil, nil)
		if reading.Verdict != model.VerdictFail || server.count() != 20 {
			t.Errorf("%s after %d requests: %s", reading.Verdict, server.count(), reading.Reason)
		}
	})
	t.Run("straddling the budget is inconclusive", func(t *testing.T) {
		alternate := func(n int) time.Duration {
			if n%2 == 0 {
				return 0
			}
			return 150 * time.Millisecond
		}
		server := newCountingServer(t, delayed(alternate, always(200)))
		reading := measureLatency(t, server, p50(60), nil, nil)
		if reading.Verdict != model.VerdictInconclusive {
			t.Errorf("%s: %s", reading.Verdict, reading.Reason)
		}
	})
	for name, status := range map[string]int{"401": 401, "500": 500} {
		t.Run("mostly "+name+" answers are inconclusive", func(t *testing.T) {
			mostly := func(n int) int {
				if n%10 == 0 {
					return 200
				}
				return status
			}
			server := newCountingServer(t, delayed(constant(0), mostly))
			reading := measureLatency(t, server, p50(300), nil, nil)
			if reading.Verdict != model.VerdictInconclusive || reading.Measured["not_samples"] != 18 {
				t.Errorf("%s with %v not samples: %s", reading.Verdict, reading.Measured["not_samples"], reading.Reason)
			}
		})
	}
	t.Run("a request past its timeout counts as slow", func(t *testing.T) {
		// A 100 ms budget gives each request 700 ms. Fourteen of twenty
		// hang past it; dropped, the six fast answers would pass.
		hang := func(n int) time.Duration {
			if n < 14 {
				return time.Second
			}
			return 0
		}
		server := newCountingServer(t, delayed(hang, always(200)))
		reading := measureLatency(t, server, p50(100), nil, nil)
		if reading.Verdict != model.VerdictFail || reading.Measured["timeouts"] != 14 {
			t.Errorf("%s with %v timeouts: %s", reading.Verdict, reading.Measured["timeouts"], reading.Reason)
		}
	})
}

type extractOverride struct{ timeoutMS int }

func toOverrides(overrides map[string]extractOverride) map[string]Override {
	converted := map[string]Override{}
	for id, override := range overrides {
		converted[id] = Override{TimeoutMS: override.timeoutMS}
	}
	return converted
}

func TestNothingMakesTheLatencyProbeSendMoreThanFiftyOrCloserThanFiftyMilliseconds(t *testing.T) {
	p95 := declaredAs("http:inventory-service/GET /ready", "latency_p95_ms", 300)
	tries := map[string]struct {
		budget    *model.Fact
		inputs    map[string]any
		overrides map[string]extractOverride
	}{
		"inputs asking for more and faster": {p95, map[string]any{
			"count": 500, "requests": 500, "samples": 500, "spacing_ms": 0, "interval": "0s",
			"parallel": 8, "concurrency": 8,
		}, nil},
		"configuration raising the probe's timeout": {p95, nil,
			map[string]extractOverride{model.LatencyProbeID: {timeoutMS: 300_000}}},
		"a manifest declaring the strictest budget": {p95, nil, nil},
		"credentials offered as inputs": {p95, map[string]any{
			"token": "not-a-real-token", "authorization": "Bearer not-a-real-token",
			"headers": map[string]any{"Authorization": "Bearer not-a-real-token"},
		}, nil},
	}
	for name, try := range tries {
		t.Run(name, func(t *testing.T) {
			server := newCountingServer(t, delayed(constant(0), always(200)))
			measureLatency(t, server, try.budget, try.inputs, try.overrides)
			if got := server.count(); got > model.LatencyMaxRequests || got == 0 {
				t.Errorf("%d requests, want at most %d", got, model.LatencyMaxRequests)
			}
			if gap := server.closestGap(); gap < LatencySpacing {
				t.Errorf("two requests %s apart, want at least %s", gap, LatencySpacing)
			}
			server.neverSentAnythingButAPlainGET(t)
		})
	}
}

func TestABudgetOnARouteThatIsNotGetSendsNothing(t *testing.T) {
	server := newCountingServer(t, delayed(constant(0), always(200)))
	budget := declaredAs("http:inventory-service/POST /orders", "latency_p95_ms", 300)
	readings := NewRunner(Options{
		Ledger: grantEverything(t), Deps: Deps{HTTP: NewRealHTTPClient(5 * time.Second), Now: time.Now},
	}).Run(context.Background(), []Request{{
		ProbeID: model.LatencyProbeID, Target: "component:inventory-service", Environment: "local",
		Inputs:      map[string]any{"url": server.URL + "/orders", "method": "POST"},
		Expectation: budget,
	}})
	if readings[0].Verdict != model.VerdictInconclusive || server.count() != 0 {
		t.Errorf("%s after %d requests: %s", readings[0].Verdict, server.count(), readings[0].Reason)
	}
}

func TestTheLatencyProbeIsTheOneTheRuleJudges(t *testing.T) {
	if id := (httpLatency{}).Manifest().ID; id != model.LatencyProbeID {
		t.Fatalf("the latency probe is %q, but readings are judged for %q", id, model.LatencyProbeID)
	}
}

// TestAPostBudgetSendsNothingWhateverTheInputsSay: the method comes from
// the budget's subject, so a url input with no method, method=GET, or a
// base_url cannot turn a POST route's budget into timed GETs (Phase 36
// phase audit, finding B).
func TestAPostBudgetSendsNothingWhateverTheInputsSay(t *testing.T) {
	server := newCountingServer(t, delayed(constant(0), always(200)))
	budget := declaredAs("http:inventory-service/POST /orders", "latency_p50_ms", 300)
	for name, request := range map[string]Request{
		"a url input":          {Target: "component:inventory-service", Inputs: map[string]any{"url": server.URL + "/orders"}},
		"url and method=GET":   {Target: "component:inventory-service", Inputs: map[string]any{"url": server.URL + "/orders", "method": "GET"}},
		"the http: POST route": {Target: "http:inventory-service/POST /orders", Inputs: map[string]any{"url": server.URL + "/orders"}},
		"base_url and method":  {Target: "http:inventory-service/POST /orders", Inputs: map[string]any{"base_url": server.URL, "method": "get"}},
	} {
		request.ProbeID, request.Environment, request.Expectation = model.LatencyProbeID, "local", budget
		readings := NewRunner(Options{
			Ledger: grantEverything(t), Deps: Deps{HTTP: NewRealHTTPClient(5 * time.Second), Now: time.Now},
		}).Run(context.Background(), []Request{request})
		if readings[0].Verdict != model.VerdictInconclusive {
			t.Errorf("%s: %s: %s", name, readings[0].Verdict, readings[0].Reason)
		}
	}
	if got := server.count(); got != 0 {
		t.Errorf("%d requests were sent for a POST route's budget", got)
	}
}

// TestTwoLatencyRunsAtOnceDoNotInterleave: the runner runs requests
// concurrently, and two latency runs in one process take turns, so no two
// requests are closer than the spacing (finding A).
func TestTwoLatencyRunsAtOnceDoNotInterleave(t *testing.T) {
	server := newCountingServer(t, delayed(constant(0), always(200)))
	request := Request{
		ProbeID: model.LatencyProbeID, Target: "component:inventory-service", Environment: "local",
		Inputs: map[string]any{"url": server.URL + "/ready"}, Expectation: p50(300),
	}
	readings := NewRunner(Options{
		Ledger: grantEverything(t), Deps: Deps{HTTP: NewRealHTTPClient(5 * time.Second), Now: time.Now},
		Concurrency: 4,
	}).Run(context.Background(), []Request{request, request})
	for _, reading := range readings {
		if reading.Measured["requests"] != 20 {
			t.Errorf("a run sent %v requests, want 20", reading.Measured["requests"])
		}
	}
	if gap := server.closestGap(); gap < LatencySpacing {
		t.Errorf("two requests %s apart, want at least %s", gap, LatencySpacing)
	}
}

// TestABudgetOutsideItsBoundsSendsNothing: an integer budget past
// model.MaxBudgetMS overflowed the request timeout to a negative duration
// and failed with nothing sent (finding E).
func TestABudgetOutsideItsBoundsSendsNothing(t *testing.T) {
	server := newCountingServer(t, delayed(constant(0), always(200)))
	for _, value := range []any{5_000_000_000_000, int64(5_000_000_000_000), model.MaxBudgetMS + 1, 0, -1, 1.5} {
		reading := measureLatency(t, server,
			declaredAs("http:inventory-service/GET /ready", "latency_p50_ms", value), nil, nil)
		if reading.Verdict != model.VerdictInconclusive {
			t.Errorf("budget %v: %s: %s", value, reading.Verdict, reading.Reason)
		}
	}
	if got := server.count(); got != 0 {
		t.Errorf("%d requests were sent for budgets out of bounds", got)
	}
}

// TestTheLargestBudgetIsStillMeasured: a request's timeout is cut to what
// the run has left rather than the run stopping, so a 60 s budget against
// a fast route still takes its twenty samples (finding F).
func TestTheLargestBudgetIsStillMeasured(t *testing.T) {
	server := newCountingServer(t, delayed(constant(0), always(200)))
	reading := measureLatency(t, server, p50(model.MaxBudgetMS), nil, nil)
	if reading.Verdict != model.VerdictPass || server.count() != 20 {
		t.Errorf("%s after %d requests: %s", reading.Verdict, server.count(), reading.Reason)
	}
}

// TestAUrlOnAnotherRouteSendsNothing: the budget fixes the path as well
// as the method, so GET /ready's budget is never passed on another route's
// times (Phase 36 re-audit).
func TestAUrlOnAnotherRouteSendsNothing(t *testing.T) {
	server := newCountingServer(t, delayed(constant(0), always(200)))
	for name, inputs := range map[string]map[string]any{
		"another path":     {"url": server.URL + "/elsewhere"},
		"a longer path":    {"url": server.URL + "/ready/now"},
		"no path at all":   {"url": server.URL},
		"another base_url": {"base_url": server.URL + "/v2"},
	} {
		readings := NewRunner(Options{
			Ledger: grantEverything(t), Deps: Deps{HTTP: NewRealHTTPClient(5 * time.Second), Now: time.Now},
		}).Run(context.Background(), []Request{{
			ProbeID: model.LatencyProbeID, Target: "http:inventory-service/GET /ready", Environment: "local",
			Inputs: inputs, Expectation: p50(300),
		}})
		if readings[0].Verdict != model.VerdictInconclusive {
			t.Errorf("%s: %s: %s", name, readings[0].Verdict, readings[0].Reason)
		}
	}
	if got := server.count(); got != 0 {
		t.Errorf("%d requests were sent to a route the budget is not on", got)
	}
	// A declared template matches a concrete path, and is measured.
	templated := declaredAs("http:inventory-service/GET /items/{}", "latency_p50_ms", 300)
	readings := NewRunner(Options{
		Ledger: grantEverything(t), Deps: Deps{HTTP: NewRealHTTPClient(5 * time.Second), Now: time.Now},
	}).Run(context.Background(), []Request{{
		ProbeID: model.LatencyProbeID, Target: "component:inventory-service", Environment: "local",
		Inputs: map[string]any{"url": server.URL + "/items/42"}, Expectation: templated,
	}})
	if readings[0].Verdict != model.VerdictPass || server.count() != 20 {
		t.Errorf("a concrete path under a declared template: %s after %d requests: %s",
			readings[0].Verdict, server.count(), readings[0].Reason)
	}
}

// TestAUrlTheRouteCheckOnceAcceptedSendsNothing holds the re-audit of part
// 1: each of these was timed against GET /ready's budget (or /items/{}'s),
// because the check compared a canonical form of the path and the probe
// then sent the raw URL. Counted at the server: nothing is sent for any.
func TestAUrlTheRouteCheckOnceAcceptedSendsNothing(t *testing.T) {
	server := newCountingServer(t, delayed(constant(0), always(200)))
	host := strings.TrimPrefix(server.URL, "http://")
	ready := p50(300)
	items := declaredAs("http:inventory-service/GET /items/{}", "latency_p50_ms", 300)
	for name, test := range map[string]struct {
		url    string
		budget *model.Fact
	}{
		"a trailing slash":               {server.URL + "/ready/", ready},
		"a doubled slash":                {server.URL + "//ready", ready},
		"an empty template segment":      {server.URL + "/items//42", items},
		"an escaped question mark":       {server.URL + "/ready%3Fanything/else", ready},
		"an escape then a traversal":     {server.URL + "/ready%3F/../../admin", ready},
		"an escaped hash":                {server.URL + "/ready%23x/y/z", ready},
		"an escaped space":               {server.URL + "/ready%20", ready},
		"an escaped tab":                 {server.URL + "/ready%09", ready},
		"a dot-dot template segment":     {server.URL + "/items/..", items},
		"an escaped slash":               {server.URL + "/items%2F42", items},
		"a query string":                 {server.URL + "/ready?delay=9999", ready},
		"an empty query":                 {server.URL + "/ready?", ready},
		"a fragment":                     {server.URL + "/ready#x", ready},
		"userinfo, sent as a credential": {"http://admin:secret@" + host + "/ready", ready},
	} {
		readings := NewRunner(Options{
			Ledger: grantEverything(t), Deps: Deps{HTTP: NewRealHTTPClient(5 * time.Second), Now: time.Now},
		}).Run(context.Background(), []Request{{
			ProbeID: model.LatencyProbeID, Target: "component:inventory-service", Environment: "local",
			Inputs: map[string]any{"url": test.url}, Expectation: test.budget,
		}})
		if readings[0].Verdict != model.VerdictInconclusive || !strings.Contains(readings[0].Reason, "nothing was sent") {
			t.Errorf("%s: %s: %s", name, readings[0].Verdict, readings[0].Reason)
		}
	}
	if got := server.count(); got != 0 {
		t.Errorf("%d requests were sent for a URL that is not the budget's route", got)
	}
	// Still measured: the route itself, and a concrete segment under a template.
	for name, test := range map[string]struct {
		url    string
		budget *model.Fact
	}{
		"the route": {server.URL + "/ready", ready}, "a template": {server.URL + "/items/42", items},
	} {
		before := server.count()
		readings := measureOnce(t, test.url, test.budget)
		if readings.Verdict != model.VerdictPass || server.count()-before != 20 {
			t.Errorf("%s: %s after %d requests: %s", name, readings.Verdict, server.count()-before, readings.Reason)
		}
	}
}

func measureOnce(t *testing.T, url string, budget *model.Fact) model.Reading {
	t.Helper()
	return NewRunner(Options{
		Ledger: grantEverything(t), Deps: Deps{HTTP: NewRealHTTPClient(5 * time.Second), Now: time.Now},
	}).Run(context.Background(), []Request{{
		ProbeID: model.LatencyProbeID, Target: "component:inventory-service", Environment: "local",
		Inputs: map[string]any{"url": url}, Expectation: budget,
	}})[0]
}

// TestARouteWithBothBudgetsIsMeasuredOnceAndJudgedTwice (Phase 36 part 2):
// part 1 measured only the p95 when a route declared both, so the p50 was
// declared, never judged and never said to be unjudged. Now one run of 50
// requests, counted at the server, gives one reading per budget, each
// judged by the rule from the same samples and each validating. The
// budgets come from expectation resolution, as they would from culprit.yaml.
func TestARouteWithBothBudgetsIsMeasuredOnceAndJudgedTwice(t *testing.T) {
	server := newCountingServer(t, delayed(constant(0), always(200)))
	route := "http:inventory-service/GET /ready"
	facts := []model.Fact{*declaredAs(route, "latency_p50_ms", 5), *declaredAs(route, "latency_p95_ms", 300)}
	readings := NewRunner(Options{
		Ledger: grantEverything(t), Deps: Deps{HTTP: NewRealHTTPClient(5 * time.Second), Now: time.Now},
		Expectations: NewExpectations(facts),
	}).RunOne(context.Background(), Request{
		ProbeID: model.LatencyProbeID, Target: route, Environment: "local",
		Inputs: map[string]any{"base_url": server.URL},
	})
	if got := server.count(); got != model.LatencyMaxRequests {
		t.Fatalf("%d requests for a route with two budgets, want one run of %d", got, model.LatencyMaxRequests)
	}
	server.neverSentAnythingButAPlainGET(t)
	if len(readings) != 2 {
		t.Fatalf("%d readings, want one per budget: %+v", len(readings), readings)
	}
	judged := map[string]model.Verdict{}
	for _, reading := range readings {
		if err := reading.Validate(); err != nil {
			t.Fatalf("a reading does not validate: %v", err)
		}
		for predicate := range reading.Expected {
			judged[predicate] = reading.Verdict
		}
		if reading.ExpectedSource == nil {
			t.Errorf("a reading cites no budget: %+v", reading)
		}
	}
	if judged["latency_p95_ms"] != model.VerdictPass || judged["latency_p50_ms"] == "" {
		t.Fatalf("judged %v, want the p95 passed and the p50 judged", judged)
	}
	if !samplesEqual(readings[0].Measured["samples_us"], readings[1].Measured["samples_us"]) {
		t.Fatal("the two readings were not judged from the same samples")
	}
}

func samplesEqual(a, b any) bool {
	left, lok := a.([]int)
	right, rok := b.([]int)
	if !lok || !rok || len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
}
