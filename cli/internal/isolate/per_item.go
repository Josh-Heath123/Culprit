// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package isolate

import (
	"context"
	"fmt"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The N+1 step (docs/PERFORMANCE_PLAN.md, Phase 39 part 2).
//
// N+1 is evidence beneath a route over its declared latency budget, never a
// finding of its own (decision 1). So it is asked only where the database
// pass would be: the entry's own GET route over its latency budget, with
// nothing below the entry slow.
//
//   - In an environment declared isolated (`isolated: true`), it is asked
//     before the database pass, whose statement window times the system's
//     own traffic: an isolated environment declares there is none beyond
//     Culprit's. probe.db.statements_per_request is placed on the slow
//     route, as the latency probe is, with `at` from that route's
//     response_items_max budget when one is declared. A statement run per
//     item roots there, and the database pass is not run.
//   - In any other environment it is not asked. There is no n_plus_one
//     hypothesis, and one sentence of the diagnosis says why. It is not a
//     partial: the diagnosis is as complete as the other passes make it.
//
// The join (decision 7):
//   - supported: the reading names a statement run per item;
//   - ruled out: it passes, saw at least one statement, and names none;
//   - unexplored: it passes having seen no statement at all, which is not
//     evidence (the route was served without the database, or under
//     Culprit's own role, which the bracket cannot see); or it is
//     inconclusive or refused, with its reason.

// perItemFinding is what the N+1 step established.
type perItemFinding struct {
	route   string // the slow route: the root
	reading string // the per-item reading's id
	latency string // the latency reading that found the route slow
	// The first statement named: its queryid, its text when kept, its calls,
	// and the item count.
	queryID string
	text    string
	calls   int64
	items   int64
}

// perItemStep asks, of the entry's slow route, whether it runs a statement
// per item. It does nothing unless the latency pass found the entry's own
// route over its budget.
func (w *Walk) perItemStep(ctx context.Context, entry string, found *located) {
	if found.entrySlow == "" || found.latency != "component" || len(found.path) != 1 || found.path[0] != entry {
		return
	}
	slow := w.readingByID(found.entrySlow)
	kind, parts, err := model.ParseSubject(slow.Target)
	if err != nil || kind != model.KindHTTP || parts["method"] != "GET" {
		return
	}
	route := slow.Target
	if !w.options.Isolated {
		found.perItemUnasked = fmt.Sprintf(
			"Whether %s runs one statement per item was not asked: this walk does not run in an "+
				"environment declared isolated (isolated: true in culprit.yaml, which the production agent "+
				"never applies), so another client's statements could not be told from the request's.",
			describe(route))
		return
	}

	w.addHypothesis(KindNPlusOne, route)
	h := w.hypothesis(KindNPlusOne, route)
	if h == nil {
		return
	}
	if reason := w.outOfBudget(); reason != "" {
		w.markUnexplored(h, reason, "")
		found.partial = append(found.partial, couldNotCheck(*h))
		return
	}
	var reasons []string
	id := ""
	for _, manifest := range w.discriminators(KindNPlusOne) {
		inputs, reason := w.placement.Inputs(manifest, model.Hypothesis{Kind: KindNPlusOne, Subject: route})
		if reason != "" {
			reasons = append(reasons, fmt.Sprintf("%s on %s: %s", manifest.ID, describe(route), reason))
			continue
		}
		if at, declared := w.listAt(route); declared {
			if inputs == nil {
				inputs = map[string]any{}
			}
			inputs["at"] = at
		}
		id = w.run(ctx, Request{ProbeID: manifest.ID, Target: route, Inputs: inputs})
		break
	}
	if id == "" {
		if len(reasons) == 0 {
			reasons = append(reasons, "no probe in the catalogue can test for "+kindPhrase(KindNPlusOne))
		}
		w.markUnexplored(h, "no probe could be placed: "+strings.Join(reasons, "; "), "")
		found.partial = append(found.partial, couldNotCheck(*h))
		return
	}

	reading := w.readingByID(id)
	if reading.Verdict != model.VerdictPass {
		w.markUnexplored(h, fmt.Sprintf("%s on %s was %s: %s", reading.ProbeID, describe(route), reading.Verdict, reading.Reason), id)
		found.partial = append(found.partial, couldNotCheck(*h))
		return
	}
	named := perItemNamed(reading)
	if len(named) == 0 {
		if len(perItemStatements(reading)) == 0 {
			database, _ := reading.Measured["database"].(string)
			w.markUnexplored(h, fmt.Sprintf(
				"the request made no statement Culprit could see on %s: the route was served without it, "+
					"or under Culprit's own role, which the measurement leaves out, so this reading is not "+
					"evidence either way", databaseName(database)), id)
			found.partial = append(found.partial, couldNotCheck(*h))
			return
		}
		h.Status, h.Reason, h.Readings = model.HypothesisRuledOut, "", append(h.Readings, id)
		return
	}
	h.Status, h.Reason, h.Readings = model.HypothesisSupported, "", append(h.Readings, id, found.entrySlow)
	first := named[0]
	finding := &perItemFinding{route: route, reading: id, latency: found.entrySlow, queryID: first.queryID,
		text: first.text, calls: first.calls, items: wholeOf(reading.Measured["items"])}
	found.perItem = finding

	// The root is the route. Reproduced is asked of the reading that found
	// it slow: the per-item reading is evidence, and passes either way.
	found.root, found.rootReading = route, found.entrySlow
	if recorded, ok := w.requests[found.entrySlow]; ok {
		request := recorded.Request
		found.rootRequest = &request
	}
	found.latency = ""
}

// namedStatement is one statement a per-item reading names.
type namedStatement struct {
	queryID, text string
	calls         int64
}

// perItemStatements are a per-item reading's statements, as kept.
func perItemStatements(reading model.Reading) []map[string]any {
	var out []map[string]any
	switch raw := reading.Measured["statements"].(type) {
	case []any:
		for _, item := range raw {
			if statement, ok := item.(map[string]any); ok {
				out = append(out, statement)
			}
		}
	case []map[string]any:
		out = append(out, raw...)
	}
	return out
}

// perItemNamed are the statements a per-item reading names, in its order.
func perItemNamed(reading model.Reading) []namedStatement {
	statements := map[string]map[string]any{}
	for _, statement := range perItemStatements(reading) {
		if queryID, ok := statement["queryid"].(string); ok {
			statements[queryID] = statement
		}
	}
	var named []namedStatement
	for _, queryID := range stringsOf(reading.Measured["per_item"]) {
		statement := statements[queryID]
		text, _ := statement["text"].(string)
		named = append(named, namedStatement{queryID: queryID, text: text, calls: wholeOf(statement["calls"])})
	}
	return named
}

// listAt is where the route's response_items_max budget says its list is,
// when one is declared.
func (w *Walk) listAt(route string) (string, bool) {
	for _, fact := range w.facts {
		if fact.Plane != model.PlaneIntent || fact.Subject != route || !model.ListBudgetPredicates[fact.Predicate] {
			continue
		}
		if _, at, ok := model.ListBudget(fact.Value); ok {
			return at, true
		}
	}
	return "", false
}

func databaseName(database string) string {
	if database == "" {
		return "the route's database"
	}
	return database
}

// statementPhrase is a named statement in words: its text when kept,
// with its queryid.
func (f *perItemFinding) statementPhrase() string {
	if f.text == "" || strings.HasPrefix(f.text, "text not kept") {
		return "statement " + f.queryID
	}
	return fmt.Sprintf("statement %s (%s)", f.queryID, f.text)
}

// perItemTree adds the N+1 finding's edge: the entry is caused by the
// route, cited by the per-item reading and the latency reading that found
// it slow.
func perItemTree(finding *perItemFinding, entry string, add func(from, to string, relation model.Relation, ids ...string)) {
	entrySubject := model.MustBuildSubject(model.KindComponent, model.Parts{"name": entry})
	add(entrySubject, finding.route, model.RelationCausedBy, finding.reading, finding.latency)
}

// perItemDiagnosis writes the statement and the remediation of an N+1
// finding. The recommendation is deterministic (decision 8).
func perItemDiagnosis(diagnosis *model.Diagnosis, found *located, entry string) {
	finding := found.perItem
	route := describe(finding.route)
	evidence := fmt.Sprintf("%s ran %d times for the %d items one request returned", finding.statementPhrase(),
		finding.calls, finding.items)
	if len(found.partial) > 0 {
		diagnosis.Statement = fmt.Sprintf(
			"The walk stopped at %s: it is slower than the latency budget declared for it, and it runs "+
				"one statement per item: %s. It could not check every alternative: %s.",
			route, evidence, strings.Join(found.partial, "; "))
		return
	}
	diagnosis.Statement = fmt.Sprintf(
		"%s is slow because %s runs one statement per item it returns: %s. The route is over the latency "+
			"budget declared for it, and nothing it calls on the request path is slow.",
		entry, route, evidence)
	diagnosis.Remediation = fmt.Sprintf(
		"Load the relation for every item in one statement, a join or one query over the items' keys, in "+
			"place of %s run once per item. Verification, not this recommendation, decides whether a "+
			"change worked.", finding.statementPhrase())
	diagnosis.Complete = true
}
