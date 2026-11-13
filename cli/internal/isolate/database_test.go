package isolate

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The third pass (Phase 37 part 3), on recorded readings with no network:
// the statement reading is judged by the rule itself, and the plan reading
// is the plan probe's shape, so each validates as a real one would.

const (
	shop      = "shop-service"
	shopDB    = "shop-db"
	products  = "public.products"
	queryID   = "4242"
	sortIndex = "ix_products_sku"
)

var (
	productsTable  = model.MustBuildSubject(model.KindSchema, model.Parts{"database": shopDB, "namespace": "public", "table": "products"})
	categoryColumn = model.MustBuildSubject(model.KindSchema, model.Parts{"database": shopDB, "namespace": "public", "table": "products", "column": "category"})
)

// dbWorld answers the statement and plan probes from what it is told, and
// every other probe with a pass, so the error pass finds nothing below the
// entry and there is no latency budget.
type dbWorld struct {
	// statement is the statement reading's verdict and reason when it is
	// not judged from the window (inconclusive, refused); "" judges it.
	statementVerdict model.Verdict
	statementReason  string
	// overMS is the statement's mean per call; the table budget is 20 ms.
	overMS int
	// plan is the plan reading's verdict; "" passes with the nodes below.
	planVerdict model.Verdict
	planReason  string
	nodes       []any
	indexes     []any
	// failing names components whose reachability probe fails.
	failing map[string]bool
	ran     []string
}

func (d *dbWorld) Run(_ context.Context, request Request) model.Reading {
	d.ran = append(d.ran, request.ProbeID)
	reading := model.Reading{
		ProbeID: request.ProbeID, ProbeVersion: 1, Target: request.Target,
		Environment: "simulated", Verdict: model.VerdictPass, TakenAt: clock, AgentID: "simulated-runner",
	}
	switch request.ProbeID {
	case model.StatementProbeID:
		if d.statementVerdict != "" {
			reading.Verdict, reading.Reason = d.statementVerdict, d.statementReason
			return reading
		}
		reading.Measured = map[string]any{
			"database": shopDB, "window_s": 30, "reset_during_window": false, "planned": true,
			"other_statements": 0, "statements_too_large": 0, "server_version_num": 160004,
			"statements": []any{map[string]any{
				"queryid": queryID, "calls": 10, "total_us": d.overMS * 1000 * 10,
				"text":   "SELECT sku FROM products WHERE category = $1 ORDER BY sku LIMIT $2",
				"tables": []any{products}, "budget_ms": 20, "budget_on": products,
			}},
		}
		verdict, reason, err := model.JudgeStatements(reading.Measured)
		if err != nil {
			panic(err)
		}
		reading.Verdict, reading.Reason = verdict, reason
	case model.PlanProbeID:
		if request.Inputs["queryid"] != queryID {
			panic("the plan probe was not given the statement's queryid")
		}
		if d.planVerdict != "" {
			reading.Verdict, reading.Reason = d.planVerdict, d.planReason
			return reading
		}
		reading.Measured = map[string]any{
			"queryid": queryID, "nodes": d.nodes, "tables": []any{products},
			"indexes": map[string]any{products: d.indexes}, "server_version_num": 160004,
		}
	default:
		_, parts, _ := model.ParseSubject(request.Target)
		if d.failing[parts["name"]] || d.failing[parts["component"]] || d.failing[parts["to_component"]] {
			reading.Verdict, reading.Reason = model.VerdictFail, "it fails"
		}
	}
	return reading
}

// sortWalk is the demo's plan with no index on category: the sku index
// walked for the order, category filtered row by row.
func sortWalk() []any {
	return []any{
		map[string]any{"node_type": "Limit", "plan_rows": 50, "total_cost": 10.0},
		map[string]any{"node_type": "Index Scan", "relation": products, "index": sortIndex,
			"filter_columns": []any{"category"}, "index_cond_columns": []any{}, "plan_rows": 50, "total_cost": 900.0},
	}
}

func index(name string, columns ...string) map[string]any {
	listed := []any{}
	for _, c := range columns {
		listed = append(listed, c)
	}
	return map[string]any{"name": name, "columns": listed}
}

func dbManifests() []model.ProbeManifest {
	return append(manifests(),
		model.ProbeManifest{ID: model.StatementProbeID, Version: 1, Discriminates: []string{KindStatementBudgetExceeded}},
		model.ProbeManifest{ID: model.PlanProbeID, Version: 2, Discriminates: []string{KindMissingIndex}},
	)
}

// tableBudget is the 20 ms query_mean_ms_max on products.
func tableBudget() model.Fact {
	return model.Fact{Plane: model.PlaneIntent, Subject: productsTable, Predicate: "query_mean_ms_max", Value: 20}
}

// migrationsSay is the INTENT plane for category: whether the migrations
// declare an index led by it.
func migrationsSay(leads bool) model.Fact {
	return model.Fact{Plane: model.PlaneIntent, Subject: categoryColumn, Predicate: model.PredicateLeadsIndex, Value: leads}
}

func dbWalk(t *testing.T, world *dbWorld, facts []model.Fact, extra ...Connection) model.Investigation {
	t.Helper()
	components := []Component{{Name: shop, Kind: "service"}, {Name: shopDB, Kind: "database"}, {Name: "pricing", Kind: "service"}}
	connections := append([]Connection{{From: shop, To: shopDB, Kind: "sql", OnRequestPath: false}}, extra...)
	walk := New(components, connections, facts, dbManifests(), world,
		openPlacement{}, Options{Environment: "simulated", Now: func() time.Time { return clock }})
	return diagnose(t, walk, shop)
}

func edgesOf(inv model.Investigation) string {
	var edges []string
	for _, edge := range inv.FaultTree {
		edges = append(edges, edge.FromSubject+" -["+string(edge.Relation)+"]-> "+edge.ToSubject)
	}
	return strings.Join(edges, "\n")
}

// TestFourPlanesGiveAMissingIndex: over budget, the plan filters category
// with no index condition, no live index leads it, and the migrations
// declare none. The root is the column, citing the statement and the plan,
// and the recommended index is (category, sku).
func TestFourPlanesGiveAMissingIndex(t *testing.T) {
	world := &dbWorld{overMS: 96, nodes: sortWalk(), indexes: []any{index(sortIndex, "sku"), index("products_pkey", "id")}}
	inv := dbWalk(t, world, []model.Fact{tableBudget(), migrationsSay(false)})

	if inv.Diagnosis.RootSubject != categoryColumn || !inv.Diagnosis.Complete {
		t.Fatalf("root %s complete %v: %s", inv.Diagnosis.RootSubject, inv.Diagnosis.Complete, inv.Diagnosis.Statement)
	}
	h := hypothesisOn(inv, KindMissingIndex, categoryColumn)
	if h == nil || h.Status != model.HypothesisSupported || len(h.Readings) != 2 {
		t.Fatalf("missing_index: %+v", h)
	}
	for _, cited := range h.Readings {
		probeID := ""
		for _, item := range inv.Readings {
			if item.ID == cited {
				probeID = item.Reading.ProbeID
			}
		}
		if probeID != model.StatementProbeID && probeID != model.PlanProbeID {
			t.Errorf("missing_index cites %s, a %s reading", cited, probeID)
		}
	}
	for _, want := range []string{"no index serves category", "filters category row by row", "walks ix_products_sku",
		"No live index leads category", "the migrations declare none"} {
		if !strings.Contains(inv.Diagnosis.Statement, want) {
			t.Errorf("the statement does not say %q: %s", want, inv.Diagnosis.Statement)
		}
	}
	if !strings.Contains(inv.Diagnosis.Remediation, "public.products (category, sku)") {
		t.Errorf("remediation: %s", inv.Diagnosis.Remediation)
	}
	want := productsTable + " -[propagates_to]-> " + component(shop) + "\n" + productsTable + " -[caused_by]-> " + categoryColumn
	if got := edgesOf(inv); !strings.Contains(got, want) {
		t.Errorf("tree:\n%s\nwant it to hold:\n%s", got, want)
	}
}

// TestALiveIndexThePlanDoesNotUseRootsAtTheBudget: an index leads category,
// but the plan walks the sku index for the order and filters category row
// by row. Not a missing index: the root is the statement's budget, with the
// plan and the live index cited and named.
func TestALiveIndexThePlanDoesNotUseRootsAtTheBudget(t *testing.T) {
	world := &dbWorld{overMS: 96, nodes: sortWalk(),
		indexes: []any{index("ix_products_category", "category"), index(sortIndex, "sku")}}
	inv := dbWalk(t, world, []model.Fact{tableBudget(), migrationsSay(true)})

	if inv.Diagnosis.RootSubject != productsTable || !inv.Diagnosis.Complete {
		t.Fatalf("root %s complete %v: %s", inv.Diagnosis.RootSubject, inv.Diagnosis.Complete, inv.Diagnosis.Statement)
	}
	h := hypothesisOn(inv, KindStatementBudgetExceeded, productsTable)
	if h == nil || h.Status != model.HypothesisSupported || len(h.Readings) != 2 {
		t.Fatalf("statement_budget_exceeded on the table: %+v", h)
	}
	if m := hypothesisOn(inv, KindMissingIndex, categoryColumn); m == nil || m.Status != model.HypothesisRuledOut {
		t.Fatalf("missing_index on category: %+v", m)
	}
	for _, want := range []string{"a live index leads category (ix_products_category)", "the plan does not use it", "walks ix_products_sku"} {
		if !strings.Contains(inv.Diagnosis.Statement, want) {
			t.Errorf("the statement does not say %q: %s", want, inv.Diagnosis.Statement)
		}
	}
	if !strings.Contains(inv.Diagnosis.Remediation, "public.products (category, sku)") {
		t.Errorf("remediation: %s", inv.Diagnosis.Remediation)
	}
}

// TestWithoutAPlanTheDiagnosisIsPartialAndNamesTheGrant: without
// db.plan.read the statement probe cannot apply the table's budget, so
// nothing is judged and the diagnosis names the capability.
func TestWithoutAPlanTheDiagnosisIsPartialAndNamesTheGrant(t *testing.T) {
	world := &dbWorld{statementVerdict: model.VerdictInconclusive,
		statementReason: "no call to a statement with a budget fell in the window; a table's budget was not " +
			"applied: db.plan.read is not granted (or the server is before PostgreSQL 16), so which tables a " +
			"statement reads is not known"}
	inv := dbWalk(t, world, []model.Fact{tableBudget(), migrationsSay(false)})
	if inv.Diagnosis.Complete || !strings.Contains(inv.Diagnosis.Statement, "db.plan.read") {
		t.Fatalf("complete %v: %s", inv.Diagnosis.Complete, inv.Diagnosis.Statement)
	}
	for _, ran := range world.ran {
		if ran == model.PlanProbeID {
			t.Fatal("the plan probe ran with no statement over a budget")
		}
	}
}

// TestADatabaseWithNoBudgetIsNamedUnbudgeted: nothing declares how fast a
// statement should be, so none is judged, and the diagnosis says so.
func TestADatabaseWithNoBudgetIsNamedUnbudgeted(t *testing.T) {
	world := &dbWorld{}
	inv := dbWalk(t, world, nil)
	if !strings.Contains(inv.Diagnosis.Statement, "no statement budget (query_mean_ms_max) is declared for "+shopDB) {
		t.Fatalf("%s", inv.Diagnosis.Statement)
	}
	for _, ran := range world.ran {
		if ran == model.StatementProbeID {
			t.Fatal("the statement probe ran on an unbudgeted database")
		}
	}
}

// TestNoDatabaseIsAskedWhenTheErrorsFoundARootBelowTheEntry: pricing, on
// the request path below the entry, fails; the database pass does not run.
func TestNoDatabaseIsAskedWhenTheErrorsFoundARootBelowTheEntry(t *testing.T) {
	world := &dbWorld{overMS: 96, nodes: sortWalk(), failing: map[string]bool{"pricing": true}}
	inv := dbWalk(t, world, []model.Fact{tableBudget(), migrationsSay(false)},
		Connection{From: shop, To: "pricing", Kind: "http", OnRequestPath: true})
	for _, ran := range world.ran {
		if ran == model.StatementProbeID || ran == model.PlanProbeID {
			t.Fatalf("%s ran though the errors found a root below the entry: %s", ran, inv.Diagnosis.Statement)
		}
	}
}

// TestAWindowCutByTheDeadlineLeavesTheHypothesisUnexplored: the statement
// probe could not fit its window before the walk's deadline.
func TestAWindowCutByTheDeadlineLeavesTheHypothesisUnexplored(t *testing.T) {
	reason := shopDB + ": the caller's deadline leaves 12s, less than the 30s window and its snapshots, so no " +
		"window was started, so no statement was timed"
	world := &dbWorld{statementVerdict: model.VerdictInconclusive, statementReason: reason}
	inv := dbWalk(t, world, []model.Fact{tableBudget(), migrationsSay(false)})
	h := hypothesisOn(inv, KindStatementBudgetExceeded, component(shopDB))
	if h == nil || h.Status != model.HypothesisUnexplored || !strings.Contains(h.Reason, "no window was started") {
		t.Fatalf("%+v", h)
	}
	if inv.Diagnosis.Complete {
		t.Fatalf("complete: %s", inv.Diagnosis.Statement)
	}
}

// TestWithoutMigrationFactsTheIndexIsNotClaimedMissing: the walk was given
// no INTENT for category, so three planes are not four, and the diagnosis
// says what it was not given.
func TestWithoutMigrationFactsTheIndexIsNotClaimedMissing(t *testing.T) {
	world := &dbWorld{overMS: 96, nodes: sortWalk(), indexes: []any{index(sortIndex, "sku")}}
	inv := dbWalk(t, world, []model.Fact{tableBudget()})
	h := hypothesisOn(inv, KindMissingIndex, categoryColumn)
	if h == nil || h.Status != model.HypothesisUnexplored || !strings.Contains(h.Reason, "nothing extracted the migrations") {
		t.Fatalf("%+v", h)
	}
	if inv.Diagnosis.Complete || inv.Diagnosis.RootSubject != productsTable {
		t.Fatalf("root %s complete %v: %s", inv.Diagnosis.RootSubject, inv.Diagnosis.Complete, inv.Diagnosis.Statement)
	}
}

// TestTheRecommendationIsDerivedFromThePlan holds the rule itself.
func TestTheRecommendationIsDerivedFromThePlan(t *testing.T) {
	for _, c := range []struct {
		unserved, walked []string
		want             string
	}{
		{[]string{"category"}, []string{"sku"}, "public.products (category, sku)"},
		{[]string{"category"}, nil, "public.products (category)"},
		{[]string{"category", "vendor"}, []string{"sku", "category"}, "public.products (category, vendor, sku)"},
		{nil, []string{"sku"}, ""},
	} {
		if got := recommendIndex(products, c.unserved, c.walked); got != c.want {
			t.Errorf("%v %v: %q, want %q", c.unserved, c.walked, got, c.want)
		}
	}
}
