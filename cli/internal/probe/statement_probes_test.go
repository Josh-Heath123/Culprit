package probe

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/capture"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

func TestTheStatementProbesAreTheOnesTheRuleJudges(t *testing.T) {
	if (dbStatementBudget{}).Manifest().ID != model.StatementProbeID || (dbPlan{}).Manifest().ID != model.PlanProbeID {
		t.Fatal("the statement probes' ids are not the ones model's rule and validation name")
	}
}

const productsTable = "schema:inventory-db/public.products"

func tableBudget(ms int) model.Fact {
	return *declaredAs(productsTable, "query_mean_ms_max", ms)
}

func slowProducts() capture.StatementWindow {
	return capture.StatementWindow{
		Statements: []capture.StatementStats{{
			QueryID: 7, Calls: 5, TotalMicros: 260000, TextKept: true,
			Text: "SELECT id, name FROM products WHERE category = $1", PlanJSON: seqScanPlan,
		}},
		TableColumns: map[string][]string{"public.products": {"id", "category", "name"}},
	}
}

// TestATableBudgetIsUnjudgedWithoutAPlan: without db.plan.read only the
// database's own budget applies; a table budget stays unjudged, and the
// reading says so.
func TestATableBudgetIsUnjudgedWithoutAPlan(t *testing.T) {
	request := Request{ProbeID: model.StatementProbeID, Target: "component:inventory-db",
		Related: []model.Fact{tableBudget(50)}}
	outcome := dbStatementBudget{}.Run(context.Background(), request,
		Deps{Statements: fakeStatements{window: slowProducts(), planned: false}})
	if outcome.Verdict != model.VerdictInconclusive || !strings.Contains(outcome.Reason, "db.plan.read is not granted") {
		t.Fatalf("%s: %s", outcome.Verdict, outcome.Reason)
	}
}

// TestAStatementIsJudgedByItsTablesBudget: with a plan, the strictest
// budget of the tables the statement reads applies, before the database's.
func TestAStatementIsJudgedByItsTablesBudget(t *testing.T) {
	request := Request{ProbeID: model.StatementProbeID, Target: "component:inventory-db",
		Expectation: declaredAs("component:inventory-db", "query_mean_ms_max", 500),
		Related:     []model.Fact{tableBudget(50)}}
	outcome := dbStatementBudget{}.Run(context.Background(), request,
		Deps{Statements: fakeStatements{window: slowProducts(), planned: true}})
	if outcome.Verdict != model.VerdictFail {
		t.Fatalf("%s: %s", outcome.Verdict, outcome.Reason)
	}
	statements := outcome.Measured["statements"].([]any)
	first := statements[0].(map[string]any)
	if first["budget_ms"] != 50 || first["budget_on"] != "public.products" {
		t.Fatalf("judged against %v on %v, want the table's 50 ms", first["budget_ms"], first["budget_on"])
	}
	// Without the table budget, the database's 500 ms applies, and it is within.
	request.Related = nil
	outcome = dbStatementBudget{}.Run(context.Background(), request,
		Deps{Statements: fakeStatements{window: slowProducts(), planned: true}})
	if outcome.Verdict != model.VerdictPass {
		t.Fatalf("against the database's budget: %s: %s", outcome.Verdict, outcome.Reason)
	}
}

// TestTheReadingKeepsOverBudgetStatementsFirst: past 20 statements, those
// over budget are kept before faster ones with more time in the window, so
// the kept integers judge as the whole window does.
func TestTheReadingKeepsOverBudgetStatementsFirst(t *testing.T) {
	window := capture.StatementWindow{}
	for i := int64(1); i <= 25; i++ {
		window.Statements = append(window.Statements, capture.StatementStats{QueryID: i, Calls: 1000, TotalMicros: 1000 * 1000})
	}
	window.Statements = append(window.Statements, capture.StatementStats{QueryID: 99, Calls: 1, TotalMicros: 60000})
	request := Request{ProbeID: model.StatementProbeID, Target: "component:inventory-db",
		Expectation: declaredAs("component:inventory-db", "query_mean_ms_max", 50)}
	outcome := dbStatementBudget{}.Run(context.Background(), request, Deps{Statements: fakeStatements{window: window}})
	statements := outcome.Measured["statements"].([]any)
	if outcome.Verdict != model.VerdictFail || len(statements) != model.StatementReadingMax ||
		statements[0].(map[string]any)["queryid"] != "99" || outcome.Measured["other_statements"] != 6 {
		t.Fatalf("%s, %d kept, first %v, %v others", outcome.Verdict, len(statements),
			statements[0], outcome.Measured["other_statements"])
	}
}

// TestAStatementWhoseTextIsNotKeptSaysSo (Q29 (2)).
func TestAStatementWhoseTextIsNotKeptSaysSo(t *testing.T) {
	window := capture.StatementWindow{Statements: []capture.StatementStats{{QueryID: 3, Calls: 1, TotalMicros: 10}}}
	request := Request{ProbeID: model.StatementProbeID, Target: "component:inventory-db",
		Expectation: declaredAs("component:inventory-db", "query_mean_ms_max", 50)}
	outcome := dbStatementBudget{}.Run(context.Background(), request, Deps{Statements: fakeStatements{window: window}})
	if text := outcome.Measured["statements"].([]any)[0].(map[string]any)["text"]; text != TextNotKept {
		t.Fatalf("text %v", text)
	}
}

// TestAPlanKeepsNoConstant: a plan's filter is read for the relation's
// own column names and dropped; a constant in it reaches no reading.
func TestAPlanKeepsNoConstant(t *testing.T) {
	plan := `[{"Plan": {"Node Type": "Bitmap Heap Scan", "Relation Name": "products",
	  "Plan Rows": 250, "Total Cost": 12.5,
	  "Recheck Cond": "(category = 'hunter2-secret'::text)",
	  "Filter": "((name)::text ~~ 'category%'::text)",
	  "Plans": [{"Node Type": "Bitmap Index Scan", "Index Name": "products_category",
	    "Plan Rows": 250, "Total Cost": 4.2, "Index Cond": "(category = 'hunter2-secret'::text)"}]}}]`
	nodes := ParsePlan(plan, map[string][]string{"public.products": {"id", "category", "name"}})
	out, _ := json.Marshal(nodes)
	if strings.Contains(string(out), "hunter2") || strings.Contains(string(out), "::text") {
		t.Fatalf("a plan reading holds part of the filter: %s", out)
	}
	if len(nodes) != 2 || nodes[0]["relation"] != "public.products" || nodes[1]["index"] != "products_category" {
		t.Fatalf("nodes: %s", out)
	}
	if columns := nodes[0]["filter_columns"].([]string); strings.Join(columns, ",") != "category,name" {
		t.Fatalf("filter columns %v, want category and name (and not category from inside a string)", columns)
	}
}
