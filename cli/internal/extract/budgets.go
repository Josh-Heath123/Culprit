package extract

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Budgets — Phase 36 part 1 (docs/PERFORMANCE_PLAN.md P1).
//
// A latency with nothing to compare it to has no INTENT to diverge from:
// "usually 120 ms, now 400 ms" is the baseline-as-truth mistake. So how
// fast a subject must be is declared, in `budgets:`, and each entry becomes
// an INTENT fact at rank 100 beside `invariants:`. An OpenAPI operation's
// `x-culprit-budget` is the same fact at rank 80 (openapi.go). Two sources
// declaring different budgets for one subject go through the comparator as
// an `intent_conflict`, like any other fact (D7) — nothing here compares.
//
// Culprit never chooses a threshold on the user's behalf (§4): a subject
// with no budget is listed as unbudgeted, never given one.

// Budget is one `budgets:` entry.
//
//	budgets:
//	  - subject: "http:inventory-service/GET /ready"
//	    predicate: latency_p95_ms
//	    value: 400
//	    why: the route the walk asks at inventory-service
type Budget struct {
	Subject   string `yaml:"subject"`
	Predicate string `yaml:"predicate"`
	// Value is whole milliseconds.
	Value any `yaml:"value"`
	// Why is required, as for an invariant: a budget nobody explained is
	// one nobody can safely change.
	Why string `yaml:"why"`
}

// BudgetExtractor is the provenance extractor of a culprit.yaml budget.
const BudgetExtractor = "culprit.yaml budgets"

// BudgetSkipWant is the `want` of a skip reporting an `x-culprit-budget`
// that is not a budget. Its own name, not http_routes: a skip under a want
// says that want was not extracted, and the routes were.
const BudgetSkipWant = "budgets"

// budgetValue is a budget's whole, positive number of milliseconds.
func budgetValue(value any) (int, bool) {
	switch typed := value.(type) {
	case int:
		return typed, typed > 0
	case int64:
		return int(typed), typed > 0
	case uint64:
		return int(typed), typed > 0 && typed < 1<<31
	case float64:
		whole := int(typed)
		return whole, typed > 0 && float64(whole) == typed && typed < 1<<31
	}
	return 0, false
}

// validateBudgets refuses a `budgets:` entry that cannot be measured
// against. Refused rather than warned, like every other check-time section:
// a budget that half-loads is a route silently never held to it.
func (m *Manifest) validateBudgets() error {
	for index, budget := range m.Budgets {
		where := fmt.Sprintf("budgets[%d]", index)
		if strings.TrimSpace(budget.Why) == "" {
			return &PolicyError{Message: where +
				": `why` is required. A budget nobody explained is one nobody can safely change."}
		}
		if _, known := model.BudgetPredicates[budget.Predicate]; !known {
			return &PolicyError{Message: fmt.Sprintf(
				"%s: predicate %q is not one of %s", where, budget.Predicate,
				strings.Join(budgetPredicateNames(), ", "))}
		}
		if _, ok := budgetValue(budget.Value); !ok {
			return &PolicyError{Message: where +
				": `value` must be a whole, positive number of milliseconds"}
		}
		if strings.HasSuffix(budget.Subject, "*") {
			return &PolicyError{Message: where +
				": a budget names one subject; a pattern is not something a measurement can be about"}
		}
		if err := checkSubject(where, budget.Subject); err != nil {
			return err
		}
	}
	return nil
}

func budgetPredicateNames() []string {
	names := make([]string, 0, len(model.BudgetPredicates))
	for name := range model.BudgetPredicates {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// BudgetFacts converts a manifest's budgets into rank-100 INTENT facts,
// stamped with the run's capture, as InvariantFacts does.
func BudgetFacts(
	manifest *Manifest, artefact string, capturedAt time.Time, captureID string,
) ([]model.Fact, error) {
	if manifest == nil || len(manifest.Budgets) == 0 {
		return []model.Fact{}, nil
	}
	facts := make([]model.Fact, 0, len(manifest.Budgets))
	for index, budget := range manifest.Budgets {
		value, _ := budgetValue(budget.Value)
		fact := model.Fact{
			Plane:     model.PlaneIntent,
			Subject:   budget.Subject,
			Predicate: budget.Predicate,
			Value:     value,
			Provenance: model.Provenance{
				SourceKind:     model.SourceAssertion,
				Extractor:      BudgetExtractor,
				Artefact:       artefact,
				Locator:        fmt.Sprintf("budgets[%d]", index),
				ConfidenceRank: model.RankDeveloperAssertion,
			},
			CapturedAt: capturedAt,
			CaptureID:  captureID,
		}
		if err := fact.Validate(); err != nil {
			return nil, &PolicyError{Message: fmt.Sprintf(
				"budgets[%d] (%s): %s", index, budget.Subject, err)}
		}
		facts = append(facts, fact)
	}
	return facts, nil
}
