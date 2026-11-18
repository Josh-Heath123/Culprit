package isolate

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The N+1 step (Phase 39 part 2), on recorded readings with no network:
// the latency reading is judged by its own rule and the per-item reading by
// model.JudgePerItem, so each validates as a real one would.

const (
	perItemQuery = "7777"
	listQuery    = "1111"
)

var itemsRoute = model.MustBuildSubject(model.KindHTTP, model.Parts{"component": shop, "method": "GET", "path": "/items"})

// perItemWorld answers probe.http.latency on shop-service's route (slow or
// fast), probe.db.statements_per_request from the statements it is given,
// and the statement and plan probes as dbWorld does.
type perItemWorld struct {
	db     dbWorld
	slowMS int // the route's every sample, in ms; the budget is 300
	// verdict, when set, is the per-item reading's verdict, with reason.
	verdict model.Verdict
	reason  string
	items   int
	calls   map[string]int // queryid -> calls in the bracket
	ran     []string
	inputs  map[string]any // the per-item request's inputs
}

func (p *perItemWorld) Run(ctx context.Context, request Request) model.Reading {
	p.ran = append(p.ran, request.ProbeID)
	reading := model.Reading{
		ProbeID: request.ProbeID, ProbeVersion: 1, Target: request.Target,
		Environment: "simulated", Verdict: model.VerdictPass, TakenAt: clock, AgentID: "simulated-runner",
	}
	switch request.ProbeID {
	case model.LatencyProbeID:
		var samples, connects []int
		for index := 0; index < model.LatencyMaxRequests; index++ {
			samples = append(samples, p.slowMS*1000)
			connects = append(connects, 1000)
		}
		reading.Measured = map[string]any{
			"percentile": 95, "requests": model.LatencyMaxRequests, "planned": model.LatencyMaxRequests,
			"samples_us": samples, "connect_us": connects, "timeout_connect_us": []int{}, "timeouts": 0,
		}
		reading.Expected = map[string]any{"latency_p95_ms": 300}
		verdict, _, err := model.JudgeLatency(reading.Measured, reading.Expected)
		if err != nil {
			panic(err)
		}
		reading.Verdict = verdict
		return reading
	case model.StatementsPerRequestProbeID:
		p.inputs = request.Inputs
		if p.verdict != "" {
			reading.Verdict, reading.Reason = p.verdict, p.reason
			return reading
		}
		statements := []map[string]any{}
		for queryID, calls := range p.calls {
			statements = append(statements, map[string]any{"queryid": queryID, "calls": calls, "text": "SELECT $1"})
		}
		ordered := make([]model.PerItemStatement, 0, len(statements))
		for _, statement := range statements {
			ordered = append(ordered, model.PerItemStatement{QueryID: statement["queryid"].(string), Calls: statement["calls"].(int)})
		}
		model.PerItemOrder(ordered)
		kept := []any{}
		for _, statement := range ordered {
			text := "SELECT id FROM items ORDER BY id LIMIT $1"
			if statement.QueryID == perItemQuery {
				text = "SELECT detail FROM item_details WHERE item_id = $1"
			}
			kept = append(kept, map[string]any{"queryid": statement.QueryID, "calls": statement.Calls, "text": text})
		}
		reading.Measured = map[string]any{
			"url": "http://shop-service/items", "method": "GET", "at": "/items", "database": shopDB,
			"quiet_window_s": 2, "quiet_calls": 0, "status": 200, "items": p.items,
			"statements": kept, "other_statements": 0, "statements_too_large": 0,
		}
		verdict, reason, perItem, err := model.JudgePerItem(reading.Measured)
		if err != nil {
			panic(err)
		}
		reading.Verdict, reading.Reason, reading.Measured["per_item"] = verdict, reason, perItem
		return reading
	}
	return p.db.Run(ctx, request)
}

func perItemManifests() []model.ProbeManifest {
	return append(dbManifests(),
		model.ProbeManifest{ID: model.LatencyProbeID, Version: 1, Discriminates: []string{KindLatencyBudgetExceeded}, Cost: model.CostMetered},
		model.ProbeManifest{ID: model.StatementsPerRequestProbeID, Version: 1, Discriminates: []string{KindNPlusOne}},
	)
}

// routeBudgets are shop-service's route budgets: 300 ms p95, and a list
// bound at /items. The products table has its statement budget too, so a
// database pass, when it runs, has something to ask.
func routeBudgets() []model.Fact {
	return []model.Fact{
		{Plane: model.PlaneIntent, Subject: itemsRoute, Predicate: "latency_p95_ms", Value: 300},
		{Plane: model.PlaneIntent, Subject: itemsRoute, Predicate: "response_items_max", Value: model.ListBudgetValue(50, "/items")},
		tableBudget(),
	}
}

func perItemWalk(t *testing.T, world *perItemWorld, isolated bool) model.Investigation {
	t.Helper()
	components := []Component{{Name: shop, Kind: "service"}, {Name: shopDB, Kind: "database"}}
	connections := []Connection{{From: shop, To: shopDB, Kind: "sql"}}
	walk := New(components, connections, routeBudgets(), perItemManifests(), world, openPlacement{},
		Options{Environment: "simulated", Isolated: isolated, Now: func() time.Time { return clock }})
	symptom := model.Symptom{Kind: model.SymptomEndpoint, Subject: itemsRoute, Source: "simulated"}
	inv, err := walk.Diagnose(context.Background(), symptom, shop)
	if err != nil {
		t.Fatal(err)
	}
	inv.ID, inv.OpenedAt = "inv-test", clock
	if err := inv.Validate(); err != nil {
		t.Fatalf("the walk built an investigation the model rejects: %v", err)
	}
	assertReadable(t, inv)
	return inv
}

func ranProbe(ran []string, id string) bool {
	for _, each := range ran {
		if each == id {
			return true
		}
	}
	return false
}

// TestAStatementRunPerItemRootsAtTheRoute: in an isolated environment, the
// slow route's per-item reading names a statement, so the root is the
// route, citing that statement, its calls and the item count, with the
// recommendation; the database pass is not run.
func TestAStatementRunPerItemRootsAtTheRoute(t *testing.T) {
	world := &perItemWorld{slowMS: 900, items: 50, calls: map[string]int{perItemQuery: 50, listQuery: 1}}
	inv := perItemWalk(t, world, true)

	d := inv.Diagnosis
	if d.RootSubject != itemsRoute || !d.Complete {
		t.Fatalf("root %s complete %v: %s", d.RootSubject, d.Complete, d.Statement)
	}
	h := hypothesisOn(inv, KindNPlusOne, itemsRoute)
	if h == nil || h.Status != model.HypothesisSupported {
		t.Fatalf("n_plus_one: %+v", h)
	}
	for _, want := range []string{"statement " + perItemQuery, "item_details", "ran 50 times for the 50 items",
		"runs one statement per item"} {
		if !strings.Contains(d.Statement, want) {
			t.Errorf("the statement does not say %q: %s", want, d.Statement)
		}
	}
	if !strings.Contains(d.Remediation, "in one statement") || !strings.Contains(d.Remediation, perItemQuery) {
		t.Errorf("remediation: %s", d.Remediation)
	}
	if world.inputs["at"] != "/items" {
		t.Errorf("the probe was given at %v, want the list budget's /items", world.inputs["at"])
	}
	if ranProbe(world.ran, model.StatementProbeID) {
		t.Errorf("the database pass ran under an N+1 root: %v", world.ran)
	}
	want := component(shop) + " -[caused_by]-> " + itemsRoute
	if got := edgesOf(inv); !strings.Contains(got, want) {
		t.Errorf("tree:\n%s\nwant it to hold:\n%s", got, want)
	}
	if !d.Confidence.Reproduced.Holds {
		t.Errorf("reproduced: %s", d.Confidence.Reproduced.Reason)
	}
}

// TestNoStatementPerItemRulesItOut: the reading saw statements and names
// none, so N+1 is ruled out and the database pass runs as it does now.
func TestNoStatementPerItemRulesItOut(t *testing.T) {
	world := &perItemWorld{slowMS: 900, items: 50, calls: map[string]int{listQuery: 1, perItemQuery: 3},
		db: dbWorld{overMS: 1}}
	inv := perItemWalk(t, world, true)

	h := hypothesisOn(inv, KindNPlusOne, itemsRoute)
	if h == nil || h.Status != model.HypothesisRuledOut {
		t.Fatalf("n_plus_one: %+v", h)
	}
	if !ranProbe(world.ran, model.StatementProbeID) {
		t.Errorf("the database pass did not run: %v", world.ran)
	}
	if inv.Diagnosis.RootSubject != component(shop) || !inv.Diagnosis.Complete {
		t.Errorf("root %s complete %v: %s", inv.Diagnosis.RootSubject, inv.Diagnosis.Complete, inv.Diagnosis.Statement)
	}
}

// TestARequestWithNoVisibleStatementIsNotEvidence: a pass that saw no
// statement at all leaves N+1 unexplored, saying why, never ruled out
// (decision 7): the route was served without the database, or under
// Culprit's own role.
func TestARequestWithNoVisibleStatementIsNotEvidence(t *testing.T) {
	world := &perItemWorld{slowMS: 900, items: 50, calls: map[string]int{}, db: dbWorld{overMS: 1}}
	inv := perItemWalk(t, world, true)

	h := hypothesisOn(inv, KindNPlusOne, itemsRoute)
	if h == nil || h.Status != model.HypothesisUnexplored {
		t.Fatalf("n_plus_one with no statement seen: %+v, want unexplored", h)
	}
	for _, want := range []string{"no statement Culprit could see on " + shopDB, "Culprit's own role", "not evidence"} {
		if !strings.Contains(h.Reason, want) {
			t.Errorf("the reason does not say %q: %s", want, h.Reason)
		}
	}
	if inv.Diagnosis.Complete || !strings.Contains(inv.Diagnosis.Statement, "no statement Culprit could see") {
		t.Errorf("the diagnosis does not say what it could not check: complete %v, %s",
			inv.Diagnosis.Complete, inv.Diagnosis.Statement)
	}
}

// TestAnInconclusivePerItemReadingIsUnexplored: the quiet window was not
// quiet, so N+1 is unexplored with the probe's reason.
func TestAnInconclusivePerItemReadingIsUnexplored(t *testing.T) {
	for _, verdict := range []model.Verdict{model.VerdictInconclusive, model.VerdictRefused} {
		world := &perItemWorld{slowMS: 900, verdict: verdict, reason: "3 call(s) by another client in the 2 s quiet window",
			db: dbWorld{overMS: 1}}
		inv := perItemWalk(t, world, true)
		h := hypothesisOn(inv, KindNPlusOne, itemsRoute)
		if h == nil || h.Status != model.HypothesisUnexplored || !strings.Contains(h.Reason, "quiet window") {
			t.Errorf("%s: n_plus_one %+v, want unexplored with the probe's reason", verdict, h)
		}
		if inv.Diagnosis.Complete {
			t.Errorf("%s: the diagnosis is complete with N+1 unexplored: %s", verdict, inv.Diagnosis.Statement)
		}
	}
}

// TestNPlusOneIsNotAskedOutsideAnIsolatedEnvironment: no hypothesis, no
// per-item request, the database pass as before, and one sentence saying
// why; the diagnosis is as complete as it was.
func TestNPlusOneIsNotAskedOutsideAnIsolatedEnvironment(t *testing.T) {
	world := &perItemWorld{slowMS: 900, items: 50, calls: map[string]int{perItemQuery: 50}, db: dbWorld{overMS: 1}}
	inv := perItemWalk(t, world, false)

	if h := hypothesisOn(inv, KindNPlusOne, itemsRoute); h != nil {
		t.Errorf("an n_plus_one hypothesis outside an isolated environment: %+v", h)
	}
	if ranProbe(world.ran, model.StatementsPerRequestProbeID) {
		t.Errorf("the per-item probe ran outside an isolated environment: %v", world.ran)
	}
	if !ranProbe(world.ran, model.StatementProbeID) {
		t.Errorf("the database pass did not run: %v", world.ran)
	}
	d := inv.Diagnosis
	if !strings.Contains(d.Statement, "runs one statement per item was not asked") ||
		!strings.Contains(d.Statement, "not run in an environment declared isolated") {
		t.Errorf("the statement does not say why N+1 was not asked: %s", d.Statement)
	}
	if d.RootSubject != component(shop) || !d.Complete {
		t.Errorf("root %s complete %v: the line must not make it partial: %s", d.RootSubject, d.Complete, d.Statement)
	}
}

// TestNPlusOneIsNotAskedOfAFastRoute: with the route within its budget, the
// step's condition does not hold: no hypothesis, no request, no sentence.
func TestNPlusOneIsNotAskedOfAFastRoute(t *testing.T) {
	for _, isolated := range []bool{true, false} {
		world := &perItemWorld{slowMS: 5, items: 50, calls: map[string]int{perItemQuery: 50}, db: dbWorld{overMS: 1}}
		inv := perItemWalk(t, world, isolated)
		if h := hypothesisOn(inv, KindNPlusOne, itemsRoute); h != nil || ranProbe(world.ran, model.StatementsPerRequestProbeID) {
			t.Errorf("isolated=%v: N+1 asked of a route within its budget: %+v %v", isolated, h, world.ran)
		}
		if strings.Contains(inv.Diagnosis.Statement, "one statement per item") {
			t.Errorf("isolated=%v: %s", isolated, inv.Diagnosis.Statement)
		}
	}
}
