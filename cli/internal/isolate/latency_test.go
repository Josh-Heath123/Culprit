package isolate

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The second pass (Phase 36 part 2), on synthetic chains with recorded
// samples and no network: every latency reading here is one the rule
// itself judged, so each validates as a real one would.

// timing is how one component answers: each request's connection setup
// and the server's own time, in milliseconds.
type timing struct{ setup, server int }

// latencyWorld answers probe.http.latency from recorded timings, and every
// other probe with a pass: the error pass finds nothing.
type latencyWorld struct {
	timings map[string]timing // component -> how it answers
	order   []string          // probe ids, in the order they ran
	// deadlines are the context deadline each latency run was given, left
	// from the moment it started.
	deadlines []time.Duration
	// cutShort, when set, makes a latency run stop after three requests,
	// as the probe does at its deadline.
	cutShort bool
	// runs counts latency runs per target.
	runs map[string]int
}

func (l *latencyWorld) Run(ctx context.Context, request Request) model.Reading {
	return l.RunSet(ctx, request)[0]
}

func (l *latencyWorld) RunSet(ctx context.Context, request Request) []model.Reading {
	l.order = append(l.order, request.ProbeID)
	base := model.Reading{
		ProbeID: request.ProbeID, ProbeVersion: 1, Target: request.Target,
		Environment: "simulated", Verdict: model.VerdictPass, TakenAt: clock, AgentID: "simulated-runner",
	}
	if request.ProbeID != model.LatencyProbeID {
		return []model.Reading{base}
	}
	if l.runs == nil {
		l.runs = map[string]int{}
	}
	l.runs[request.Target]++
	if deadline, ok := ctx.Deadline(); ok {
		l.deadlines = append(l.deadlines, time.Until(deadline))
	}
	_, parts, _ := model.ParseSubject(request.Target)
	answer := l.timings[parts["component"]]
	requests := model.LatencyMaxRequests
	if l.cutShort {
		requests = 3
	}
	var samples, connects []int
	for index := 0; index < requests; index++ {
		samples = append(samples, (answer.setup+answer.server)*1000)
		connects = append(connects, answer.setup*1000)
	}
	measured := map[string]any{
		"percentile": 95, "requests": requests, "planned": model.LatencyMaxRequests,
		"samples_us": samples, "connect_us": connects, "timeout_connect_us": []int{}, "timeouts": 0,
	}
	expected := map[string]any{"latency_p95_ms": 300}
	verdict, reason, err := model.JudgeLatency(measured, expected)
	if err != nil {
		panic(err)
	}
	base.Verdict, base.Reason, base.Measured, base.Expected = verdict, reason, measured, expected
	if verdict == model.VerdictPass || verdict == model.VerdictFail {
		base.Reason = ""
	}
	return []model.Reading{base}
}

func latencyManifests() []model.ProbeManifest {
	return append(manifests(), model.ProbeManifest{
		ID: model.LatencyProbeID, Version: 1, Discriminates: []string{KindLatencyBudgetExceeded},
		Cost: model.CostMetered,
	})
}

// budgetsOn declares a 300 ms p95 budget on GET /ready of each component.
func budgetsOn(names ...string) []model.Fact {
	var facts []model.Fact
	for _, name := range names {
		facts = append(facts, model.Fact{
			Plane: model.PlaneIntent, Predicate: "latency_p95_ms", Value: 300,
			Subject: model.MustBuildSubject(model.KindHTTP, model.Parts{"component": name, "method": "GET", "path": "/ready"}),
		})
	}
	return facts
}

func latencyWalk(t *testing.T, world *latencyWorld, vantage string, facts []model.Fact) model.Investigation {
	t.Helper()
	components, connections, _ := chain(3) // c0 -> c1 -> c2
	walk := New(components, connections, facts, latencyManifests(), world,
		openPlacement{vantage: vantage}, Options{Environment: "simulated", Now: func() time.Time { return clock }})
	return diagnose(t, walk, "c0")
}

func hypothesisOn(inv model.Investigation, kind, subject string) *model.Hypothesis {
	for index := range inv.Hypotheses {
		if inv.Hypotheses[index].Kind == kind && inv.Hypotheses[index].Subject == subject {
			return &inv.Hypotheses[index]
		}
	}
	return nil
}

func edges(inv model.Investigation) []string {
	var out []string
	for _, edge := range inv.FaultTree {
		out = append(out, edge.FromSubject+" -["+string(edge.Relation)+"]-> "+edge.ToSubject)
	}
	return out
}

// On A -> B -> C with C slowed, where B's budgeted route calls C (so B is
// slow too, and A through it), the root is C's latency, and A -> B and
// B -> C are propagation, never the root. No latency reading is taken
// before the error pass has found nothing.
func TestASlowCalleeIsTheRootAndItsCallersPropagate(t *testing.T) {
	world := &latencyWorld{timings: map[string]timing{
		"c0": {setup: 1, server: 802}, "c1": {setup: 1, server: 801}, "c2": {setup: 1, server: 800},
	}}
	inv := latencyWalk(t, world, "", budgetsOn("c0", "c1", "c2"))
	d := inv.Diagnosis
	if d.RootSubject != component("c2") || !d.Complete {
		t.Fatalf("root %s complete=%v, want component c2 complete: %s", d.RootSubject, d.Complete, d.Statement)
	}
	if h := hypothesisOn(inv, KindLatencyBudgetExceeded, component("c2")); h == nil || h.Status != model.HypothesisSupported {
		t.Fatalf("the root's latency hypothesis is %+v, want supported", h)
	}
	want := map[string]bool{
		component("c2") + " -[propagates_to]-> " + component("c1"): true,
		component("c1") + " -[propagates_to]-> " + component("c0"): true,
	}
	for _, edge := range edges(inv) {
		delete(want, edge)
		if strings.Contains(edge, "caused_by") {
			t.Errorf("a slow caller was recorded as a cause: %s", edge)
		}
	}
	if len(want) > 0 {
		t.Errorf("the tree lacks the propagation edges %v: %v", want, edges(inv))
	}
	firstLatency := -1
	for index, id := range world.order {
		if id == model.LatencyProbeID && firstLatency < 0 {
			firstLatency = index
		}
		if id != model.LatencyProbeID && firstLatency >= 0 {
			t.Fatalf("an error probe (%s) ran after a latency reading: %v", id, world.order)
		}
	}
	if firstLatency <= 0 {
		t.Fatalf("no error probe ran before the latency pass: %v", world.order)
	}
}

// With B fast and C slow, the root is still C: a latency pass at B rules
// out B's own latency, nothing below it.
func TestAFastCallerRulesOutOnlyItself(t *testing.T) {
	world := &latencyWorld{timings: map[string]timing{
		"c0": {setup: 1, server: 802}, "c1": {setup: 1, server: 5}, "c2": {setup: 1, server: 800},
	}}
	inv := latencyWalk(t, world, "", budgetsOn("c0", "c1", "c2"))
	if inv.Diagnosis.RootSubject != component("c2") || !inv.Diagnosis.Complete {
		t.Fatalf("root %s complete=%v: %s", inv.Diagnosis.RootSubject, inv.Diagnosis.Complete, inv.Diagnosis.Statement)
	}
	if h := hypothesisOn(inv, KindLatencyBudgetExceeded, component("c1")); h == nil || h.Status != model.HypothesisRuledOut {
		t.Fatalf("c1's latency is %+v, want ruled out by its own pass", h)
	}
	if h := hypothesisOn(inv, KindLatencyBudgetExceeded, component("c2")); h == nil || h.Status != model.HypothesisSupported {
		t.Fatalf("c2's latency is %+v, want supported: c1's pass ruled out nothing below it", h)
	}
}

// When the errors explain the symptom, latency is never asked.
func TestLatencyIsNotAskedWhenTheErrorsExplain(t *testing.T) {
	components, connections, names := chain(3)
	errors := componentFault(names, 2)
	world := &latencyWorld{timings: map[string]timing{"c2": {setup: 1, server: 800}}}
	runner := runnerFunc(func(ctx context.Context, request Request) model.Reading {
		if request.ProbeID == model.LatencyProbeID {
			return world.Run(ctx, request)
		}
		world.order = append(world.order, request.ProbeID)
		verdict := errors(request.ProbeID, request.Target)
		reading := model.Reading{ProbeID: request.ProbeID, ProbeVersion: 1, Target: request.Target,
			Environment: "simulated", Verdict: verdict, TakenAt: clock, AgentID: "simulated-runner"}
		return reading
	})
	walk := New(components, connections, budgetsOn("c0", "c1", "c2"), latencyManifests(), runner,
		openPlacement{}, Options{Environment: "simulated", Now: func() time.Time { return clock }})
	inv := diagnose(t, walk, "c0")
	for _, id := range world.order {
		if id == model.LatencyProbeID {
			t.Fatalf("a latency reading was taken although a request at c2 fails: %v", world.order)
		}
	}
	for _, h := range inv.Hypotheses {
		if h.Kind == KindLatencyBudgetExceeded {
			t.Fatalf("a latency hypothesis was generated: %+v", h)
		}
	}
}

type runnerFunc func(ctx context.Context, request Request) model.Reading

func (f runnerFunc) Run(ctx context.Context, request Request) model.Reading { return f(ctx, request) }

// Hop or component, from the same samples: each case is the slow reading
// at c2 split into its setup and its server time.
func TestHopOrComponentFromTheSameSamples(t *testing.T) {
	connection := model.MustBuildSubject(model.KindConnection, model.Parts{"from_component": "c1", "to_component": "c2"})
	for _, test := range []struct {
		name     string
		at       timing
		vantage  string
		root     string
		complete bool
		says     []string
	}{
		{name: "setup alone over, the agent in the caller: the connection",
			at: timing{setup: 800, server: 5}, vantage: "c1", root: connection, complete: true,
			says: []string{"connection setup alone is over"}},
		{name: "server time alone over: the component",
			at: timing{setup: 2, server: 800}, vantage: "c1", root: component("c2"), complete: true,
			says: []string{"c2's own"}},
		{name: "neither alone over: partial, naming both",
			at: timing{setup: 200, server: 200}, vantage: "c1", root: component("c2"), complete: false,
			says: []string{"the connection from c1 to c2", "c2 itself", "cannot be told apart"}},
		{name: "the agent outside every component: partial, reaching it from this agent",
			at: timing{setup: 800, server: 5}, vantage: "", root: component("c2"), complete: false,
			says: []string{"reaching c2 from this agent"}},
	} {
		t.Run(test.name, func(t *testing.T) {
			world := &latencyWorld{timings: map[string]timing{"c2": test.at}}
			inv := latencyWalk(t, world, test.vantage, budgetsOn("c2"))
			d := inv.Diagnosis
			if d.RootSubject != test.root || d.Complete != test.complete {
				t.Fatalf("root %s complete=%v, want %s complete=%v: %s",
					d.RootSubject, d.Complete, test.root, test.complete, d.Statement)
			}
			for _, phrase := range test.says {
				if !strings.Contains(d.Statement, phrase) {
					t.Errorf("the statement does not say %q: %s", phrase, d.Statement)
				}
			}
			if test.root == connection {
				if h := hypothesisOn(inv, KindLatencyBudgetExceeded, connection); h == nil || h.Status != model.HypothesisSupported {
					t.Errorf("the connection's latency hypothesis is %+v, want supported", h)
				}
				found := false
				for _, edge := range edges(inv) {
					found = found || edge == component("c1")+" -[caused_by]-> "+connection
				}
				if !found {
					t.Errorf("the tree does not end at the connection: %v", edges(inv))
				}
				// The component's own time was within its budget, so its
				// latency is ruled out by the same reading, not left supported.
				if h := hypothesisOn(inv, KindLatencyBudgetExceeded, component("c2")); h == nil || h.Status != model.HypothesisRuledOut {
					t.Errorf("c2's own latency is %+v, want ruled out", h)
				}
			}
		})
	}
}

// A slow component whose callee declares no budget is partial, and names
// the callee; with no budget anywhere, the diagnosis says none is declared.
func TestWhatAnUnbudgetedComponentLeavesUnknownIsSaid(t *testing.T) {
	world := &latencyWorld{timings: map[string]timing{"c1": {setup: 1, server: 800}}}
	inv := latencyWalk(t, world, "", budgetsOn("c1"))
	if inv.Diagnosis.Complete || !strings.Contains(inv.Diagnosis.Statement, "whether c2, which c1 calls") {
		t.Fatalf("a slow c1 over an unbudgeted c2: complete=%v: %s", inv.Diagnosis.Complete, inv.Diagnosis.Statement)
	}
	none := latencyWalk(t, &latencyWorld{}, "", nil)
	if none.Diagnosis.Complete || !strings.Contains(none.Diagnosis.Statement, "no latency budget a GET request can measure is declared") {
		t.Fatalf("no budgets: complete=%v: %s", none.Diagnosis.Complete, none.Diagnosis.Statement)
	}
	for _, h := range none.Hypotheses {
		if h.Kind == KindLatencyBudgetExceeded {
			t.Fatalf("a component with no budget was given the hypothesis: %+v", h)
		}
	}
}

// A latency probe started near the end of the walk's wall clock is given
// the walk's deadline, stops there, and the hypothesis is unexplored.
func TestALatencyProbeStopsAtTheWalksDeadline(t *testing.T) {
	world := &latencyWorld{timings: map[string]timing{"c2": {setup: 1, server: 800}}, cutShort: true}
	components, connections, _ := chain(3)
	started := clock
	now := started
	// Each probe the walk runs moves the clock on, so the latency run
	// starts with three seconds of the walk's two minutes left.
	advancing := runnerFunc(func(ctx context.Context, request Request) model.Reading {
		if request.ProbeID != model.LatencyProbeID {
			now = started.Add(117 * time.Second)
		}
		return world.Run(ctx, request)
	})
	walk := New(components, connections, budgetsOn("c2"), latencyManifests(), advancing,
		openPlacement{}, Options{Environment: "simulated", MaxWallClock: 2 * time.Minute,
			Now: func() time.Time { return now }})
	inv := diagnose(t, walk, "c0")
	if len(world.deadlines) == 0 {
		t.Fatal("the latency run was given no deadline")
	}
	if left := world.deadlines[0]; left > 3*time.Second || left <= 0 {
		t.Fatalf("the latency run's deadline was %s away, want the walk's remaining 3s", left)
	}
	h := hypothesisOn(inv, KindLatencyBudgetExceeded, component("c2"))
	if h == nil || h.Status != model.HypothesisUnexplored || !strings.Contains(h.Reason, "cut short") {
		t.Fatalf("the hypothesis is %+v, want unexplored, cut short", h)
	}
}

// A slow component with only fast components below it is the root itself:
// the rule is "nothing slow below", not "something below" (the Phase 36
// part 2 audit found this case untested).
func TestASlowComponentAboveFastOnesIsTheRoot(t *testing.T) {
	world := &latencyWorld{timings: map[string]timing{
		"c0": {setup: 1, server: 5}, "c1": {setup: 1, server: 800}, "c2": {setup: 1, server: 5},
	}}
	inv := latencyWalk(t, world, "", budgetsOn("c0", "c1", "c2"))
	if inv.Diagnosis.RootSubject != component("c1") || !inv.Diagnosis.Complete {
		t.Fatalf("root %s complete=%v, want c1, slow above a fast c2: %s",
			inv.Diagnosis.RootSubject, inv.Diagnosis.Complete, inv.Diagnosis.Statement)
	}
	if h := hypothesisOn(inv, KindLatencyBudgetExceeded, component("c2")); h == nil || h.Status != model.HypothesisRuledOut {
		t.Fatalf("c2's latency is %+v, want ruled out", h)
	}
}
