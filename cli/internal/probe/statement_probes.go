package probe

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strconv"

	"github.com/josh-heath123/culprit/cli/internal/capture"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The statement probes (Phase 37 part 2, docs/PERFORMANCE_PLAN.md "Part 2 —
// statements and plans").
//
// probe.db.statement_budget measures, under db.stats.read, how long each of
// a database's normalised statements took over a fixed 30-second window, and
// judges each against its budget by model.JudgeStatements. probe.db.plan
// asks the planner, under db.plan.read, how it would run one statement. No
// row is read, nothing is reset, and EXPLAIN ANALYZE cannot be sent: the
// database package has no template for any of it.

// TextNotKept is what a reading says of a statement whose text it does not
// hold (Q29 (2)).
const TextNotKept = "text not kept: not a statement Postgres normalises"

// --- probe.db.statement_budget -----------------------------------------

type dbStatementBudget struct{}

func (dbStatementBudget) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		// A literal, held equal to model.StatementProbeID by
		// TestTheStatementProbesAreTheOnesTheRuleJudges.
		ID:           "probe.db.statement_budget",
		Version:      1,
		Effect:       model.EffectInspect,
		Capabilities: []string{"db.stats.read"},
		// The 30-second window, and the reads either side of it.
		TimeoutMS:    75_000,
		ExpectedFrom: model.PlaneIntent,
		Produces: []model.Produces{
			{SubjectTemplate: "component:{name}", Predicate: "query_mean_ms_max"},
		},
		Cost: model.CostCheap,
		// No input: the database is the target's, and how to reach it is
		// culprit.yaml's dsn_env. Under culprit mcp an agent names no
		// statement, table or address (Phase 37's decisions).
		Inputs: map[string]any{"type": "object", "properties": map[string]any{}},
	}
}

// statementBudgets are the budgets that can judge a statement in this
// database: the database's own, and each table's, by subject.
func statementBudgets(request Request) (database int, tables map[string]int, source *model.Provenance) {
	tables = map[string]int{}
	facts := append([]model.Fact{}, request.Related...)
	if request.Expectation != nil {
		facts = append([]model.Fact{*request.Expectation}, facts...)
	}
	for index, fact := range facts {
		budget, ok := wholeMilliseconds(fact.Value)
		if !ok || !model.StatementBudgetPredicates[fact.Predicate] {
			continue
		}
		if index == 0 {
			source = provenanceOf(&facts[0])
		}
		kind, parts, err := model.ParseSubject(fact.Subject)
		switch {
		case err != nil:
		case kind == model.KindComponent:
			database = budget
		case kind == model.KindSchema && parts["column"] == "":
			tables[parts["namespace"]+"."+parts["table"]] = budget
		}
	}
	return database, tables, source
}

func (dbStatementBudget) Run(ctx context.Context, request Request, deps Deps) Outcome {
	database := databaseOf(request.Target)
	databaseBudget, tableBudgets, source := statementBudgets(request)
	if databaseBudget == 0 && len(tableBudgets) == 0 {
		return withoutExpectation(request, nil, "no statement was timed")
	}
	if deps.Statements == nil {
		return inconclusive("no database client is available to this agent")
	}
	window, planned, err := deps.Statements.Window(ctx, database)
	if err != nil {
		if outcome, decided := sourceOutcome(err); decided {
			return outcome
		}
		return inconclusive(fmt.Sprintf("the statements of %s could not be read: %s",
			database, model.RedactCredentials(err.Error())))
	}
	if window.Unavailable != "" {
		return inconclusive(fmt.Sprintf("%s: %s, so no statement was timed", database, window.Unavailable))
	}

	type entry struct {
		fields map[string]any
		over   bool
		total  int64
		id     int64
	}
	var entries []entry
	tooLarge := 0
	for _, statement := range window.Statements {
		if statement.Calls > maxReadingCount || statement.TotalMicros > maxReadingCount {
			tooLarge++
			continue
		}
		fields := map[string]any{
			"queryid":  strconv.FormatInt(statement.QueryID, 10),
			"calls":    int(statement.Calls),
			"total_us": int(statement.TotalMicros),
		}
		if statement.TextKept {
			// The second layer, after the template's own filter.
			fields["text"] = model.RedactCredentials(statement.Text)
		} else {
			fields["text"] = TextNotKept
		}
		budget, budgetOn := 0, ""
		if planned && statement.PlanJSON != "" {
			nodes := ParsePlan(statement.PlanJSON, window.TableColumns)
			tables := planTables(nodes)
			fields["tables"] = tables
			for _, table := range tables {
				if ms, ok := tableBudgets[table]; ok && (budget == 0 || ms < budget) {
					budget, budgetOn = ms, table
				}
			}
		}
		if budget == 0 && databaseBudget > 0 {
			budget, budgetOn = databaseBudget, "database"
		}
		over := false
		if budget > 0 {
			fields["budget_ms"] = budget
			fields["budget_on"] = budgetOn
			over = statement.TotalMicros > int64(budget)*1000*statement.Calls
		}
		entries = append(entries, entry{fields, over, statement.TotalMicros, statement.QueryID})
	}
	// Over budget first, then by time in the window: what is kept judges
	// as the whole window does (LIMITS).
	sort.SliceStable(entries, func(i, j int) bool {
		if entries[i].over != entries[j].over {
			return entries[i].over
		}
		if entries[i].total != entries[j].total {
			return entries[i].total > entries[j].total
		}
		return entries[i].id < entries[j].id
	})
	kept := []any{}
	for index, item := range entries {
		if index < model.StatementReadingMax {
			kept = append(kept, item.fields)
		}
	}
	measured := map[string]any{
		"database":             database,
		"window_s":             int(capture.StatementWindowLength.Seconds()),
		"reset_during_window":  window.Reset,
		"planned":              planned,
		"statements":           kept,
		"other_statements":     len(entries) - len(kept),
		"server_version_num":   window.ServerVersion,
		"statements_too_large": tooLarge,
	}
	expected := map[string]any{"table_budgets_ms": tableBudgets}
	if databaseBudget > 0 {
		expected["database_budget_ms"] = databaseBudget
	}
	verdict, reason, err := model.JudgeStatements(measured)
	if err != nil {
		return inconclusive("the window's measurement is not the rule's input: " + err.Error())
	}
	if len(tableBudgets) > 0 && !planned {
		reason += "; a table's budget was not applied: db.plan.read is not granted (or the " +
			"server is before PostgreSQL 16), so which tables a statement reads is not known"
	}
	return Outcome{Verdict: verdict, Measured: measured, Expected: expected,
		ExpectedSource: source, Reason: reason}
}

// maxReadingCount is the most a reading's count may be (the rule's bound).
const maxReadingCount = 2147483647

// --- probe.db.plan ------------------------------------------------------

type dbPlan struct{}

func (dbPlan) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID:           "probe.db.plan",
		Version:      1,
		Effect:       model.EffectInspect,
		Capabilities: []string{"db.plan.read"},
		TimeoutMS:    15_000,
		// No expectation: a sequential scan of a small table is normal, so
		// a plan is evidence for the walk's join, not a finding (part 3).
		ExpectedFrom: "",
		Produces: []model.Produces{
			{SubjectTemplate: "component:{name}", Predicate: "statement_plan"},
		},
		Cost: model.CostCheap,
		Inputs: map[string]any{
			"type": "object",
			"properties": map[string]any{
				// Only the walk supplies it, from a window it read: under
				// culprit mcp, culprit_probe refuses this probe.
				"queryid": map[string]any{"type": "string"},
			},
		},
	}
}

func (dbPlan) Run(ctx context.Context, request Request, deps Deps) Outcome {
	database := databaseOf(request.Target)
	raw, ok := stringInput(request.Inputs, "queryid")
	if !ok {
		return inconclusive("no statement was named: the walk passes the queryid of one it read")
	}
	queryID, err := strconv.ParseInt(raw, 10, 64)
	if err != nil {
		return inconclusive("the queryid is not a whole number")
	}
	if deps.Statements == nil {
		return inconclusive("no database client is available to this agent")
	}
	plan, err := deps.Statements.Plan(ctx, database, queryID)
	if err != nil {
		if outcome, decided := sourceOutcome(err); decided {
			return outcome
		}
		return inconclusive(fmt.Sprintf("the plan could not be read from %s: %s",
			database, model.RedactCredentials(err.Error())))
	}
	if plan.Unavailable != "" {
		return inconclusive(fmt.Sprintf("%s: %s, so no plan was asked for", database, plan.Unavailable))
	}
	nodes := ParsePlan(plan.PlanJSON, plan.TableColumns)
	if len(nodes) == 0 {
		return inconclusive("the planner's answer could not be read")
	}
	return pass(map[string]any{
		"queryid":            raw,
		"nodes":              nodes,
		"tables":             planTables(nodes),
		"server_version_num": plan.ServerVersion,
	})
}

// --- reading a plan -----------------------------------------------------

// planNode is one node of EXPLAIN (FORMAT JSON) as the planner gives it.
type planNode struct {
	NodeType   string     `json:"Node Type"`
	Relation   string     `json:"Relation Name"`
	Schema     string     `json:"Schema"`
	Index      string     `json:"Index Name"`
	PlanRows   float64    `json:"Plan Rows"`
	TotalCost  float64    `json:"Total Cost"`
	Filter     string     `json:"Filter"`
	IndexCond  string     `json:"Index Cond"`
	Recheck    string     `json:"Recheck Cond"`
	JoinFilter string     `json:"Join Filter"`
	Plans      []planNode `json:"Plans"`
}

// ParsePlan reads a plan into the nodes a reading keeps: node type,
// relation, index, estimated rows and cost, and the relation's own columns
// its filter names. The filter expression, and any constant in it, is read
// to find those names and then dropped: it is never stored.
func ParsePlan(planJSON string, tableColumns map[string][]string) []map[string]any {
	var top []struct {
		Plan planNode `json:"Plan"`
	}
	if err := json.Unmarshal([]byte(planJSON), &top); err != nil || len(top) == 0 {
		return nil
	}
	var nodes []map[string]any
	var walk func(node planNode)
	walk = func(node planNode) {
		entry := map[string]any{
			"node_type":  node.NodeType,
			"plan_rows":  int(node.PlanRows),
			"total_cost": node.TotalCost,
		}
		if node.Relation != "" {
			namespace := node.Schema
			if namespace == "" {
				namespace = "public"
			}
			entry["relation"] = namespace + "." + node.Relation
			columns := tableColumns[namespace+"."+node.Relation]
			named := map[string]bool{}
			for _, expression := range []string{node.Filter, node.IndexCond, node.Recheck, node.JoinFilter} {
				for _, column := range columns {
					if columnNamed(expression, column) {
						named[column] = true
					}
				}
			}
			filtered := make([]string, 0, len(named))
			for column := range named {
				filtered = append(filtered, column)
			}
			sort.Strings(filtered)
			entry["filter_columns"] = filtered
		}
		if node.Index != "" {
			entry["index"] = node.Index
		}
		nodes = append(nodes, entry)
		for _, child := range node.Plans {
			walk(child)
		}
	}
	walk(top[0].Plan)
	return nodes
}

// columnNamed reports whether expression names column as an identifier:
// bare or double-quoted, not inside a quoted string.
func columnNamed(expression, column string) bool {
	if expression == "" {
		return false
	}
	unquoted := quotedText.ReplaceAllString(expression, "''")
	pattern := `(^|[^A-Za-z0-9_$"])("` + regexp.QuoteMeta(column) + `"|` + regexp.QuoteMeta(column) + `)($|[^A-Za-z0-9_$"])`
	return regexp.MustCompile(pattern).MatchString(unquoted)
}

// quotedText is a single-quoted string literal in a plan's expression.
var quotedText = regexp.MustCompile(`'(?:[^']|'')*'`)

// planTables are the relations a plan reads, "namespace.table", sorted.
func planTables(nodes []map[string]any) []string {
	seen := map[string]bool{}
	var tables []string
	for _, node := range nodes {
		if relation, ok := node["relation"].(string); ok && !seen[relation] {
			seen[relation] = true
			tables = append(tables, relation)
		}
	}
	sort.Strings(tables)
	if tables == nil {
		tables = []string{}
	}
	return tables
}
