package probe

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
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
