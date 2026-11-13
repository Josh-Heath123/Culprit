package isolate

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The third pass: the database in the walk (docs/PERFORMANCE_PLAN.md,
// Phase 37 part 3).
//
// It runs only when the error pass and the latency pass found no root
// strictly below the entry. A symptom at X with nothing failing or slow
// below X leaves X's own work, and the databases X reads, as what remains;
// so it asks about the databases the entry connects to, by an edge of any
// kind. A database only a deeper component reaches is not asked (LIMITS).
//
// It sends no statement of its own and no request to make traffic: the
// statement window measures the system's own traffic.
//
// # Two hypotheses
//
// statement_budget_exceeded is on the budget's own subject, a table or the
// database component, and is supported when probe.db.statement_budget's
// reading fails.
//
// missing_index is on the filtered column's schema: subject, and is
// supported only when four planes agree (P5):
//   - OBSERVED: a statement is over its budget (the statement reading);
//   - the plan: it filters column C of table T row by row, with no index
//     condition serving C, whatever the scan node (the plan reading);
//   - CONFIGURED: no live index leads C (the plan reading's live indexes,
//     read in the plan's session from the catalogue);
//   - INTENT: the migrations declare none (a leads_index fact, false).
//
// A live index that leads C but which the plan does not use roots at the
// statement's budget instead: the evidence is the plan and that index.

// dbFinding is what the database pass established.
type dbFinding struct {
	database string
	// subject is the root: a column's schema: subject for missing_index, a
	// table's or the database's for statement_budget_exceeded.
	subject string
	kind    string
	// budgetSubject is the statement's budget's own subject.
	budgetSubject string
	statement     string // the statement reading's id
	plan          string // the plan reading's id, or ""
	// says is what the plan does, in the diagnosis's words.
	says string
	// recommend is the recommended index, "" when none can be derived.
	recommend string
	// note is said after the statement: what the walk did not ask.
	note string
}

// databasesOf are the databases entry connects to, by an edge of any kind,
// sorted.
func (w *Walk) databasesOf(entry string) []string {
	seen := map[string]bool{}
	var databases []string
	for _, edge := range w.connected[entry] {
		if w.components[edge.To].Kind == "database" && !seen[edge.To] {
			seen[edge.To] = true
			databases = append(databases, edge.To)
		}
	}
	sort.Strings(databases)
	return databases
}

// statementBudgets says whether database has a query_mean_ms_max of its own
// or on any of its tables.
func (w *Walk) statementBudgets(database string) bool {
	for _, fact := range w.facts {
		if fact.Plane != model.PlaneIntent || !model.StatementBudgetPredicates[fact.Predicate] {
			continue
		}
		kind, parts, err := model.ParseSubject(fact.Subject)
		if err != nil {
			continue
		}
		if (kind == model.KindComponent && parts["name"] == database) ||
			(kind == model.KindSchema && parts["database"] == database) {
			return true
		}
	}
	return false
}

// intentLeadsIndex is the INTENT plane for a column: whether the migrations
// declare an index led by it ("declared"), declare none ("none"), or say
// nothing the walk was given ("unknown").
func (w *Walk) intentLeadsIndex(column string) string {
	for _, fact := range w.facts {
		if fact.Plane != model.PlaneIntent || fact.Predicate != model.PredicateLeadsIndex || fact.Subject != column {
			continue
		}
		if leads, ok := fact.Value.(bool); ok {
			if leads {
				return "declared"
			}
			return "none"
		}
	}
	return "unknown"
}

// databasePass asks, of each database entry connects to, whether a
// statement is over its budget, and why.
func (w *Walk) databasePass(ctx context.Context, entry string, found *located) {
	databases := w.databasesOf(entry)
	if len(databases) == 0 {
		return
	}
	var unbudgeted []string
	for _, database := range databases {
		if !w.statementBudgets(database) {
			unbudgeted = append(unbudgeted, database)
			continue
		}
		if finding := w.askDatabase(ctx, entry, database, found); finding != nil && found.database == nil {
			found.database = finding
		}
	}
	if len(unbudgeted) > 0 {
		found.partial = append(found.partial, fmt.Sprintf(
			"no statement budget (query_mean_ms_max) is declared for %s or %s tables, so whether a "+
				"statement there is slow was not asked; Culprit does not choose a budget",
			joinNames(unbudgeted), theirOrIts(len(unbudgeted))))
	}
	found.databaseAsked = true
}

// askDatabase runs the statement probe on one database and, when a
// statement is over a table's budget, the plan probe on it.
func (w *Walk) askDatabase(ctx context.Context, entry, database string, found *located) *dbFinding {
	dbSubject := model.MustBuildSubject(model.KindComponent, model.Parts{"name": database})
	w.addHypothesis(KindStatementBudgetExceeded, dbSubject)
	h := w.hypothesis(KindStatementBudgetExceeded, dbSubject)

	statementID, reason := w.runOn(ctx, KindStatementBudgetExceeded, entry, database, dbSubject, nil)
	if statementID == "" {
		w.markUnexplored(h, reason, "")
		found.partial = append(found.partial, couldNotCheck(*h))
		return nil
	}
	reading := w.readingByID(statementID)
	h.Readings = append(h.Readings, statementID)
	if strings.Contains(reading.Reason, "db.plan.read is not granted") {
		found.partial = append(found.partial, fmt.Sprintf(
			"a table's statement budget on %s was not judged: db.plan.read is not granted, so which "+
				"tables a statement reads is not known, and no missing index can be asked", database))
	}
	switch reading.Verdict {
	case model.VerdictPass:
		h.Status, h.Reason = model.HypothesisRuledOut, ""
		return nil
	case model.VerdictFail:
	default:
		w.markUnexplored(h, fmt.Sprintf("%s on %s was %s: %s", reading.ProbeID, database, reading.Verdict, reading.Reason), statementID)
		found.partial = append(found.partial, couldNotCheck(*h))
		return nil
	}

	over := firstOverBudget(reading)
	if over == nil {
		w.markUnexplored(h, "the statement reading fails but names no statement over its budget", statementID)
		found.partial = append(found.partial, couldNotCheck(*h))
		return nil
	}
	finding := &dbFinding{database: database, statement: statementID}
	budgetOn, _ := over["budget_on"].(string)
	finding.budgetSubject = dbSubject
	if budgetOn != "" && budgetOn != "database" {
		namespace, table, _ := strings.Cut(budgetOn, ".")
		finding.budgetSubject = model.MustBuildSubject(model.KindSchema, model.Parts{
			"database": database, "namespace": namespace, "table": table})
	}
	// Supported on the database (a statement in it is over a budget) and,
	// when a table's budget judged it, on that table too: the root is the
	// budget's own subject.
	h.Status, h.Reason, h.Readings = model.HypothesisSupported, "", []string{statementID}
	if finding.budgetSubject != dbSubject {
		w.addHypothesis(KindStatementBudgetExceeded, finding.budgetSubject)
		h = w.hypothesis(KindStatementBudgetExceeded, finding.budgetSubject)
		h.Status, h.Reason, h.Readings = model.HypothesisSupported, "", []string{statementID}
	}
	finding.subject, finding.kind = finding.budgetSubject, KindStatementBudgetExceeded

	if finding.budgetSubject == dbSubject {
		finding.says = "it is judged by the database's own budget, so which table it reads, and whether " +
			"an index would serve it, was not asked"
		return finding
	}
	queryID, _ := over["queryid"].(string)
	w.explain(ctx, entry, database, budgetOn, queryID, finding, found)
	return finding
}

// firstOverBudget is the first statement in a reading over its budget: the
// reading keeps those over budget first.
func firstOverBudget(reading model.Reading) map[string]any {
	statements, _ := reading.Measured["statements"].([]any)
	for _, item := range statements {
		statement, _ := item.(map[string]any)
		calls, total, budget := wholeOf(statement["calls"]), wholeOf(statement["total_us"]), wholeOf(statement["budget_ms"])
		if budget > 0 && total > budget*1000*calls {
			return statement
		}
	}
	return nil
}

// wholeOf reads a whole number a reading holds, as an int or a float64.
func wholeOf(value any) int64 {
	switch v := value.(type) {
	case int:
		return int64(v)
	case int64:
		return v
	case float64:
		return int64(v)
	}
	return 0
}

// runOn places and runs the probe that discriminates kind against target,
// from the agent's vantage on entry's connection to database. It returns
// the reading's id, or "" and why nothing was run.
func (w *Walk) runOn(ctx context.Context, kind, entry, database, target string, extra map[string]any) (string, string) {
	if reason := w.outOfBudget(); reason != "" {
		return "", reason
	}
	connection := model.MustBuildSubject(model.KindConnection, model.Parts{
		"from_component": entry, "to_component": database})
	candidates := w.discriminators(kind)
	if len(candidates) == 0 {
		return "", "no probe in the catalogue can test for " + kindPhrase(kind)
	}
	var reasons []string
	for _, manifest := range candidates {
		inputs, reason := w.placement.Inputs(manifest, model.Hypothesis{Kind: kind, Subject: connection})
		if reason != "" {
			reasons = append(reasons, fmt.Sprintf("%s on %s: %s", manifest.ID, database, reason))
			continue
		}
		for key, value := range extra {
			if inputs == nil {
				inputs = map[string]any{}
			}
			inputs[key] = value
		}
		return w.run(ctx, Request{ProbeID: manifest.ID, Target: target, Inputs: inputs}), ""
	}
	return "", strings.Join(reasons, "; ")
}

// planNode is one node of a plan reading.
type planNodeReading struct {
	relation, index    string
	filtered, servedBy []string
}

func planNodes(reading model.Reading) []planNodeReading {
	var nodes []planNodeReading
	raw, _ := reading.Measured["nodes"].([]any)
	for _, item := range raw {
		entry, _ := item.(map[string]any)
		node := planNodeReading{}
		node.relation, _ = entry["relation"].(string)
		node.index, _ = entry["index"].(string)
		node.filtered = stringsOf(entry["filter_columns"])
		node.servedBy = stringsOf(entry["index_cond_columns"])
		nodes = append(nodes, node)
	}
	return nodes
}

func stringsOf(value any) []string {
	var out []string
	switch v := value.(type) {
	case []string:
		out = append(out, v...)
	case []any:
		for _, item := range v {
			if s, ok := item.(string); ok {
				out = append(out, s)
			}
		}
	}
	return out
}

// liveIndexes are a plan reading's live indexes on table: name -> columns.
func liveIndexes(reading model.Reading, table string) map[string][]string {
	out := map[string][]string{}
	all, _ := reading.Measured["indexes"].(map[string]any)
	listed, _ := all[table].([]any)
	for _, item := range listed {
		entry, _ := item.(map[string]any)
		name, _ := entry["name"].(string)
		out[name] = stringsOf(entry["columns"])
	}
	return out
}

// explain runs the plan probe on the statement over a table's budget, and
// settles missing_index on the column the plan filters.
func (w *Walk) explain(ctx context.Context, entry, database, table, queryID string, finding *dbFinding, found *located) {
	namespace, name, _ := strings.Cut(table, ".")
	planID, reason := w.runOn(ctx, KindMissingIndex, entry, database,
		model.MustBuildSubject(model.KindComponent, model.Parts{"name": database}),
		map[string]any{"queryid": queryID})
	tableSubject := finding.budgetSubject
	column := func(c string) string {
		return model.MustBuildSubject(model.KindSchema, model.Parts{
			"database": database, "namespace": namespace, "table": name, "column": c})
	}
	if planID == "" {
		w.addHypothesis(KindMissingIndex, tableSubject)
		h := w.hypothesis(KindMissingIndex, tableSubject)
		w.markUnexplored(h, reason, "")
		found.partial = append(found.partial, couldNotCheck(*h))
		return
	}
	plan := w.readingByID(planID)
	if plan.Verdict != model.VerdictPass {
		w.addHypothesis(KindMissingIndex, tableSubject)
		h := w.hypothesis(KindMissingIndex, tableSubject)
		w.markUnexplored(h, fmt.Sprintf("%s on %s was %s: %s", plan.ProbeID, database, plan.Verdict, plan.Reason), planID)
		found.partial = append(found.partial, couldNotCheck(*h))
		return
	}
	finding.plan = planID

	// The plan, on this table: what it filters row by row and what an index
	// condition serves, and the index it walks, if any.
	filtered, served := map[string]bool{}, map[string]bool{}
	walked := ""
	for _, node := range planNodes(plan) {
		if node.relation != table {
			continue
		}
		for _, c := range node.filtered {
			filtered[c] = true
		}
		for _, c := range node.servedBy {
			served[c] = true
		}
		if node.index != "" && walked == "" {
			walked = node.index
		}
	}
	var unserved []string
	for _, c := range sortedKeys(filtered) {
		if !served[c] {
			unserved = append(unserved, c)
		}
	}
	live := liveIndexes(plan, table)
	finding.recommend = recommendIndex(table, unserved, live[walked])

	if len(unserved) == 0 {
		finding.says = fmt.Sprintf("the plan filters no column of %s row by row: %s", table, walkPhrase(walked, served))
		return
	}
	finding.says = fmt.Sprintf("the plan filters %s row by row on %s, with no index condition serving %s, and %s",
		joinAnd(unserved), table, itOrThem(len(unserved)), walkPhrase(walked, served))

	// missing_index, on the first unserved column, by the four planes.
	c := unserved[0]
	subject := column(c)
	w.addHypothesis(KindMissingIndex, subject)
	h := w.hypothesis(KindMissingIndex, subject)
	var leading []string
	for indexName, columns := range live {
		if len(columns) > 0 && columns[0] == c {
			leading = append(leading, indexName)
		}
	}
	sort.Strings(leading)
	intent := w.intentLeadsIndex(subject)
	switch {
	case len(leading) > 0:
		// A live index leads C and the plan does not use it: not missing.
		h.Status, h.Reason, h.Readings = model.HypothesisRuledOut, "", []string{planID}
		finding.says += fmt.Sprintf("; a live index leads %s (%s), and the plan does not use it", c, strings.Join(leading, ", "))
	case intent == "unknown":
		w.markUnexplored(h, fmt.Sprintf(
			"no migration facts say whether an index leads %s.%s: nothing extracted the migrations, so the "+
				"walk has no INTENT for it (the Python extractor plugin reads them; --no-plugins, or no "+
				"extract: section that reaches them, leaves them unread)", table, c), planID)
		found.partial = append(found.partial, couldNotCheck(*h))
	case intent == "declared":
		w.markUnexplored(h, fmt.Sprintf(
			"the migrations declare an index led by %s.%s that the database does not have: the planes "+
				"disagree, so a missing index is not what they show", table, c), planID)
		found.partial = append(found.partial, couldNotCheck(*h))
	default:
		h.Status, h.Reason, h.Readings = model.HypothesisSupported, "", []string{finding.statement, planID}
		finding.subject, finding.kind = subject, KindMissingIndex
	}
}

// recommendIndex is the index the plan asks for, derived deterministically:
// the filtered columns no index condition serves, then the columns of the
// index the plan walks for its order, each once.
func recommendIndex(table string, unserved, walked []string) string {
	if len(unserved) == 0 {
		return ""
	}
	seen := map[string]bool{}
	var columns []string
	for _, c := range append(append([]string{}, unserved...), walked...) {
		if !seen[c] {
			seen[c] = true
			columns = append(columns, c)
		}
	}
	return fmt.Sprintf("%s (%s)", table, strings.Join(columns, ", "))
}

func walkPhrase(walked string, served map[string]bool) string {
	switch {
	case walked != "" && len(served) == 0:
		return fmt.Sprintf("it walks %s for its order", walked)
	case walked != "":
		return fmt.Sprintf("it walks %s, whose condition serves %s", walked, joinAnd(sortedKeys(served)))
	}
	return "it reads the table without an index"
}

func joinAnd(names []string) string {
	switch len(names) {
	case 0:
		return ""
	case 1:
		return names[0]
	}
	return strings.Join(names[:len(names)-1], ", ") + " and " + names[len(names)-1]
}

func itOrThem(n int) string {
	if n == 1 {
		return "it"
	}
	return "them"
}

// rootAtDatabase makes the database finding the walk's root: a slow entry
// above it is propagation, cited on the symptom's edge, and the request
// reproduced is the statement probe's.
func (w *Walk) rootAtDatabase(found *located) {
	finding := found.database
	found.latency = ""
	if found.latencyUnasked != "" {
		kept := found.partial[:0]
		for _, sentence := range found.partial {
			if sentence != found.latencyUnasked {
				kept = append(kept, sentence)
			}
		}
		found.partial = kept
		finding.note = " Its own latency was not asked: " + found.latencyUnasked + "."
	}
	found.root, found.rootReading = finding.subject, finding.statement
	if recorded, ok := w.requests[finding.statement]; ok {
		request := recorded.Request
		found.rootRequest = &request
	}
	if finding.plan != "" {
		if h := w.hypothesis(KindStatementBudgetExceeded, finding.budgetSubject); h != nil && finding.kind == KindStatementBudgetExceeded {
			h.Readings = append(h.Readings, finding.plan)
		}
	}
}

// databaseTree adds the database finding's edges: the statement's budget
// subject propagates to the entry, cited by the statement reading; a
// missing index causes it, cited by the plan and the statement.
func databaseTree(finding *dbFinding, entry string, add func(from, to string, relation model.Relation, ids ...string)) {
	entrySubject := model.MustBuildSubject(model.KindComponent, model.Parts{"name": entry})
	add(finding.budgetSubject, entrySubject, model.RelationPropagatesTo, finding.statement)
	if finding.kind == KindMissingIndex {
		add(finding.budgetSubject, finding.subject, model.RelationCausedBy, finding.plan, finding.statement)
	}
}

// databaseDiagnosis writes the statement, remediation and completeness of
// a database finding.
func (w *Walk) databaseDiagnosis(diagnosis *model.Diagnosis, found *located, entry string) {
	finding := found.database
	where := describe(finding.budgetSubject)
	if len(found.partial) > 0 {
		diagnosis.Statement = fmt.Sprintf(
			"The walk stopped at %s: a statement there is over the statement budget declared for it, "+
				"and %s. It could not check every alternative: %s.",
			describe(finding.subject), finding.says, strings.Join(found.partial, "; "))
		return
	}
	switch finding.kind {
	case KindMissingIndex:
		_, parts, _ := model.ParseSubject(finding.subject)
		diagnosis.Statement = fmt.Sprintf(
			"%s is slow because a statement on %s is over the statement budget declared for it, and no "+
				"index serves %s: %s. No live index leads %s, and the migrations declare none.",
			entry, where, parts["column"], finding.says, parts["column"])
	default:
		diagnosis.Statement = fmt.Sprintf(
			"%s is slow because a statement on %s is over the statement budget declared for it: %s.",
			entry, where, finding.says)
	}
	diagnosis.Statement += finding.note
	if finding.recommend != "" {
		diagnosis.Remediation = fmt.Sprintf(
			"Add an index on %s: the columns the plan filters, then those of the index it walks for its "+
				"order. Verification, not this recommendation, decides whether a change worked.",
			finding.recommend)
	} else {
		diagnosis.Remediation = fmt.Sprintf(
			"Find what makes the statement on %s slower than its budget, or correct the budget if it is "+
				"wrong; the reading cites the window and the budget it was judged against.", where)
	}
	diagnosis.Complete = true
}
