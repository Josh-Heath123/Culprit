package isolate

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The second pass: the walk sees slow (docs/PERFORMANCE_PLAN.md, Phase 36
// part 2).
//
// It runs only when the error pass found nothing — no root, and no
// component below the entry shown to fail. Errors are cheaper and more
// fundamental: a latency run is at least twenty spaced requests, and a
// failing request has no latency worth judging.
//
// # What a pass rules out
//
// For errors, a passing request at X rules out everything below X,
// because the request exercised it. A budgeted route need not call what is
// below it (`/ready` calls nothing), so a latency pass rules out X's own
// latency alone. The pass therefore descends the whole request-path tree,
// depth first, rather than bisecting it; the tree is small, and the walk's
// probe and wall-clock limits still bound it.
//
// # The root
//
// The root is the deepest slow component whose callees keep their
// budgets — every component below it, not only the direct callees, since
// a callee's pass rules out its own latency alone. A slow component with
// anything slow below it is propagation, an edge of the tree, never the
// root. A slow component with something below it that could not be
// measured — unbudgeted, refused or inconclusive — is a partial diagnosis
// that names it.
//
// # Hop or component
//
// From the same reading, with no new request: its connection setup alone,
// and the server's own time (each answer less its setup), each judged by
// the same rule against the same budget (model.SplitLatency). Setup alone
// over, with this agent inside X's caller, roots at the connection; the
// server's time alone over roots at X; anything else is partial and names
// both. From outside every component, slow setup is "reaching X from this
// agent", which is not a connection of the system.

type latencyState int

const (
	latencyUnbudgeted latencyState = iota
	latencyFast
	latencySlow
	latencyUnknown
)

// measurableBudgets are, per component, the routes with a budget a GET
// can measure: INTENT budget facts on `http:<component>/GET <path>`, in
// subject order. A budget on a route that is not GET cannot be measured
// read-only (part 1), so it does not give its component the hypothesis.
func (w *Walk) measurableBudgets() map[string][]string {
	routes := map[string]map[string]bool{}
	for _, fact := range w.facts {
		if fact.Plane != model.PlaneIntent {
			continue
		}
		if _, isBudget := model.BudgetPredicates[fact.Predicate]; !isBudget {
			continue
		}
		kind, parts, err := model.ParseSubject(fact.Subject)
		if err != nil || kind != model.KindHTTP || parts["method"] != "GET" {
			continue
		}
		if routes[parts["component"]] == nil {
			routes[parts["component"]] = map[string]bool{}
		}
		routes[parts["component"]][fact.Subject] = true
	}
	measurable := map[string][]string{}
	for component, set := range routes {
		measurable[component] = sortedKeys(set)
	}
	return measurable
}

// latencyPass asks, of every component reached from entry, whether it is
// slower than its budget, and pins the root.
func (w *Walk) latencyPass(ctx context.Context, entry string, found *located) {
	budgets := w.measurableBudgets()
	state := map[string]latencyState{}
	slowReading := map[string]string{}
	parent := map[string]string{}
	var order []string

	var visit func(name string)
	visit = func(name string) {
		order = append(order, name)
		state[name] = latencyUnbudgeted
		if routes := budgets[name]; len(routes) > 0 && w.components[name].Kind != "database" {
			subject := model.MustBuildSubject(model.KindComponent, model.Parts{"name": name})
			w.addHypothesis(KindLatencyBudgetExceeded, subject)
			if h := w.hypothesis(KindLatencyBudgetExceeded, subject); h != nil {
				state[name], slowReading[name] = w.testLatency(ctx, h, routes)
			}
		}
		for _, edge := range w.children[name] {
			parent[edge.To] = name
			visit(edge.To)
		}
	}
	visit(entry)

	// Candidates: slow, with nothing slow anywhere below. Below, not only
	// the direct callees: a callee that kept its budget rules out its own
	// latency and nothing under it. The first in depth-first order is the
	// root; any other is said, not dropped.
	var roots []string
	for _, name := range order {
		if state[name] != latencySlow {
			continue
		}
		propagated := false
		for _, below := range w.below(name) {
			propagated = propagated || state[below] == latencySlow
		}
		if !propagated {
			roots = append(roots, name)
		}
	}

	if len(roots) == 0 {
		var unbudgeted []string
		for _, name := range order {
			switch state[name] {
			case latencyUnbudgeted:
				unbudgeted = append(unbudgeted, name)
			case latencyUnknown:
				h := w.hypothesis(KindLatencyBudgetExceeded, model.MustBuildSubject(model.KindComponent, model.Parts{"name": name}))
				found.partial = append(found.partial, couldNotCheck(*h))
			}
		}
		switch {
		case len(unbudgeted) == len(order):
			found.partial = append(found.partial, fmt.Sprintf(
				"no latency budget a GET request can measure is declared for %s, so whether the "+
					"request is slow was not asked; Culprit does not choose a budget", joinNames(unbudgeted)))
		case len(unbudgeted) > 0:
			found.partial = append(found.partial, fmt.Sprintf(
				"no latency budget a GET request can measure is declared for %s, so whether %s slow "+
					"is not known", joinNames(unbudgeted), isOrAre(len(unbudgeted))))
		}
		found.latencyKept = len(found.partial) == 0
		return
	}

	root := roots[0]
	for _, other := range roots[1:] {
		found.partial = append(found.partial, fmt.Sprintf(
			"%s is slower than its latency budget too (%s), on another branch", other, slowReading[other]))
	}
	for _, below := range w.below(root) {
		switch state[below] {
		case latencyUnbudgeted:
			found.partial = append(found.partial, fmt.Sprintf(
				"whether %s, which %s calls, is slower than a budget is not known: no budget a GET "+
					"request can measure is declared for it", below, root))
		case latencyUnknown:
			h := w.hypothesis(KindLatencyBudgetExceeded, model.MustBuildSubject(model.KindComponent, model.Parts{"name": below}))
			found.partial = append(found.partial, couldNotCheck(*h))
		}
	}

	// The path from the entry down to the root. A component on it that kept
	// its budget, or has none, is cited by the root's reading: a request
	// through it reaches the slow one.
	var path []string
	for name := root; ; name = parent[name] {
		path = append([]string{name}, path...)
		if name == entry {
			break
		}
	}
	evidence := slowReading[root]
	cite := func(name string) string {
		if state[name] == latencySlow {
			return slowReading[name]
		}
		return evidence
	}

	hop, verdict := w.hopOrComponent(root, parent[root], evidence)
	switch verdict {
	case "component":
		found.latency = "component"
	case "hop":
		connection := model.MustBuildSubject(model.KindConnection, model.Parts{
			"from_component": parent[root], "to_component": root})
		w.addHypothesis(KindLatencyBudgetExceeded, connection)
		if h := w.hypothesis(KindLatencyBudgetExceeded, connection); h != nil {
			h.Status, h.Reason, h.Readings = model.HypothesisSupported, "", []string{evidence}
		}
		recorded := w.requests[evidence].Request
		found.root, found.rootReading, found.rootRequest = connection, evidence, &recorded
		found.latency = "hop"
		path = path[:len(path)-1] // the tree ends at the caller, caused_by the connection
	default:
		found.partial = append(found.partial, hop)
	}

	found.path, found.fail = nil, map[string]string{}
	for _, name := range path {
		found.path = append(found.path, name)
		if name == entry && state[name] != latencySlow {
			found.fail[name] = "" // the symptom is its evidence
			continue
		}
		found.fail[name] = cite(name)
	}
}

// below is every component under name in the request-path tree, depth
// first.
func (w *Walk) below(name string) []string {
	var out []string
	var collect func(name string)
	collect = func(name string) {
		for _, edge := range w.children[name] {
			out = append(out, edge.To)
			collect(edge.To)
		}
	}
	collect(name)
	return out
}

// testLatency runs probe.http.latency on each of a component's measurable
// budgets, in subject order, and moves h: supported when one fails (the
// rest are not run), ruled out when all pass, unexplored with the probe's
// reason otherwise. It returns the state and, when slow, the failing
// reading.
func (w *Walk) testLatency(ctx context.Context, h *model.Hypothesis, routes []string) (latencyState, string) {
	var reasons, cited []string
	for _, route := range routes {
		if reason := w.outOfBudget(); reason != "" {
			reasons = append(reasons, reason)
			break
		}
		placed := false
		for _, manifest := range w.discriminators(h.Kind) {
			inputs, reason := w.placement.Inputs(manifest, model.Hypothesis{Kind: h.Kind, Subject: route})
			if reason != "" {
				reasons = append(reasons, fmt.Sprintf("%s on %s: %s", manifest.ID, describe(route), reason))
				continue
			}
			placed = true
			ids := w.runSet(ctx, Request{ProbeID: manifest.ID, Target: route, Inputs: inputs})
			cited = append(cited, ids...)
			for _, id := range ids {
				reading := w.readingByID(id)
				switch reading.Verdict {
				case model.VerdictFail:
					h.Status, h.Reason, h.Readings = model.HypothesisSupported, "", append(h.Readings, cited...)
					return latencySlow, id
				case model.VerdictPass:
				default:
					reasons = append(reasons, fmt.Sprintf("%s on %s was %s: %s",
						manifest.ID, describe(route), reading.Verdict, reading.Reason))
				}
			}
			break
		}
		if !placed && len(w.discriminators(h.Kind)) == 0 {
			reasons = append(reasons, "no probe in the catalogue can test for "+kindPhrase(h.Kind))
		}
	}
	if len(reasons) == 0 && len(cited) > 0 {
		h.Status, h.Reason, h.Readings = model.HypothesisRuledOut, "", append(h.Readings, cited...)
		return latencyFast, ""
	}
	if len(reasons) == 0 {
		reasons = append(reasons, "no probe could be placed")
	}
	h.Status, h.Reason = model.HypothesisUnexplored, strings.Join(reasons, "; ")
	h.Readings = append(h.Readings, cited...)
	return latencyUnknown, ""
}

// hopOrComponent splits the slow reading at root: "component" or "hop"
// when one side alone is over the budget and can be named, or the partial
// diagnosis's sentence otherwise.
func (w *Walk) hopOrComponent(root, caller, readingID string) (string, string) {
	reading := w.readingByID(readingID)
	inCaller := caller != "" && w.placement != nil && w.placement.Vantage() == caller
	hop := fmt.Sprintf("reaching %s from this agent", root)
	if inCaller {
		hop = describe(model.MustBuildSubject(model.KindConnection, model.Parts{
			"from_component": caller, "to_component": root}))
	}
	split, err := model.SplitLatency(reading.Measured, reading.Expected)
	if err != nil {
		return fmt.Sprintf("%s is slower than its latency budget (%s), and the reading does not say how "+
			"long connection setup took, so %s and %s itself cannot be told apart", root, readingID, hop, root), ""
	}
	setupOver, serverOver := split.Setup == model.VerdictFail, split.Server == model.VerdictFail
	switch {
	case serverOver && !setupOver:
		return "", "component"
	case setupOver && !serverOver && inCaller:
		return "", "hop"
	case setupOver && !serverOver:
		return fmt.Sprintf("%s is slower than %s's latency budget: connection setup alone is over it "+
			"(%s), which is not a connection of the system, so whether %s itself is slow from "+
			"inside its callers is not known", hop, root, readingID, root), ""
	case setupOver && serverOver:
		return fmt.Sprintf("%s is slower than its latency budget (%s), and both connection setup alone "+
			"and %s's own time are over it, so %s and %s itself are both named", root, readingID, root, hop, root), ""
	}
	return fmt.Sprintf("%s is slower than its latency budget (%s), but neither connection setup alone "+
		"nor %s's own time is over it, so %s and %s itself cannot be told apart", root, readingID, root, hop, root), ""
}

// unbudgetedNote names, after a complete latency diagnosis, the components
// on the request path that declare no budget a GET can measure: said, not
// implied.
func (w *Walk) unbudgetedNote(found *located) string {
	budgets := w.measurableBudgets()
	var unbudgeted []string
	for name := range w.reachedFrom(found) {
		if len(budgets[name]) == 0 {
			unbudgeted = append(unbudgeted, name)
		}
	}
	if len(unbudgeted) == 0 {
		return ""
	}
	sort.Strings(unbudgeted)
	return fmt.Sprintf(" No latency budget a GET request can measure is declared for %s, so %s "+
		"latency was not asked.", joinNames(unbudgeted), theirOrIts(len(unbudgeted)))
}

// reachedFrom is every component in the request-path tree.
func (w *Walk) reachedFrom(found *located) map[string]bool {
	reached := map[string]bool{}
	if len(found.path) == 0 {
		return reached
	}
	var collect func(name string)
	collect = func(name string) {
		reached[name] = true
		for _, edge := range w.children[name] {
			collect(edge.To)
		}
	}
	collect(found.path[0])
	return reached
}

func joinNames(names []string) string {
	switch len(names) {
	case 0:
		return ""
	case 1:
		return names[0]
	}
	return strings.Join(names[:len(names)-1], ", ") + " or " + names[len(names)-1]
}

func isOrAre(n int) string {
	if n == 1 {
		return "it is"
	}
	return "they are"
}

func theirOrIts(n int) string {
	if n == 1 {
		return "its"
	}
	return "their"
}
