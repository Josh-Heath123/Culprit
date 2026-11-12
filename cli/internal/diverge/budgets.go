package diverge

import (
	"fmt"
	"sort"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Budget coverage — Phase 36 part 1.
//
// Two coverage statements about budgets, kept beside the unverifiable
// surface and out of the divergence list, because neither says something
// is wrong with the system:
//
//   - **A budget that points at nothing.** A budget whose subject no other
//     INTENT source declares — most often a mistyped route — would never be
//     measured, and nothing else would say so.
//   - **The unbudgeted surface.** Routes INTENT declares with no budget.
//     Listed only when the manifest declares `budgets:` at all, so a project
//     that has not opted in is not told that every route lacks one. Culprit
//     never chooses a budget for them (§4).
//
// Generic over predicates like the rest of this package: it knows the
// closed set of budget predicates and the existence predicate, nothing
// about what a route is for.

// BudgetCoverage is what Budgets found.
type BudgetCoverage struct {
	// Declared is whether the manifest declares `budgets:`.
	Declared bool `json:"declared"`
	// Unmatched are budgets whose subject nothing else declares.
	Unmatched []Unverifiable `json:"unmatched"`
	// Unbudgeted are declared routes with no budget, when Declared.
	Unbudgeted []string `json:"unbudgeted,omitempty"`
}

// IsBudgetPredicate reports whether a predicate declares a budget.
func IsBudgetPredicate(predicate string) bool {
	_, isBudget := model.BudgetPredicates[predicate]
	return isBudget
}

// Budgets computes budget coverage over one INTENT capture's facts.
func Budgets(facts []model.Fact, declared bool) BudgetCoverage {
	coverage := BudgetCoverage{Declared: declared, Unmatched: []Unverifiable{}}
	declaredSubjects := map[string]bool{}
	budgeted := map[string]bool{}
	var budgets []model.Fact
	routes := map[string]bool{}
	for _, fact := range facts {
		if fact.Plane != model.PlaneIntent {
			continue
		}
		if IsBudgetPredicate(fact.Predicate) {
			budgets = append(budgets, fact)
			budgeted[fact.Subject] = true
			continue
		}
		declaredSubjects[fact.Subject] = true
		if fact.Predicate != model.PredicateExists {
			continue
		}
		if kind, parts, err := model.ParseSubject(fact.Subject); err == nil &&
			kind == model.KindHTTP && parts["aspect"] == "" {
			routes[fact.Subject] = true
		}
	}

	reported := map[string]bool{}
	for _, budget := range budgets {
		if declaredSubjects[budget.Subject] || reported[budget.Subject] {
			continue
		}
		reported[budget.Subject] = true
		coverage.Unmatched = append(coverage.Unmatched, Unverifiable{
			Subject:  budget.Subject,
			Source:   budget.Provenance.Extractor,
			Artefact: budget.Provenance.Artefact,
			Locator:  budget.Provenance.Locator,
			Reason: fmt.Sprintf(
				"%s budgets %s, which no other source declares: nothing would ever measure it",
				budget.Provenance.Extractor, budget.Subject),
		})
	}
	sort.Slice(coverage.Unmatched, func(i, j int) bool {
		return coverage.Unmatched[i].Subject < coverage.Unmatched[j].Subject
	})

	if declared {
		for route := range routes {
			if !budgeted[route] {
				coverage.Unbudgeted = append(coverage.Unbudgeted, route)
			}
		}
		sort.Strings(coverage.Unbudgeted)
		if coverage.Unbudgeted == nil {
			coverage.Unbudgeted = []string{}
		}
	}
	return coverage
}
