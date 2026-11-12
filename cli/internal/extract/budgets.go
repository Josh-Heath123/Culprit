package extract

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"gopkg.in/yaml.v3"

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

	// literalProblem is why value, as written, is not plain decimal digits
	// (model.BudgetLiteralProblem), or "". Set when the entry is read from
	// YAML; validateBudgets refuses the entry when it is set.
	literalProblem string
}

// UnmarshalYAML reads an entry and keeps how its value was written: the
// two YAML readers of culprit.yaml read `0454`, `1e3`, `0o454` and
// `300_000` as different numbers or as strings, so the form is checked,
// not the number it decoded to (Phase 36 part 2).
func (b *Budget) UnmarshalYAML(node *yaml.Node) error {
	type fields Budget
	var decoded fields
	if err := node.Decode(&decoded); err != nil {
		return err
	}
	*b = Budget(decoded)
	if node.Kind != yaml.MappingNode {
		return nil
	}
	for index := 0; index+1 < len(node.Content); index += 2 {
		if node.Content[index].Tag == "!!merge" || node.Content[index].Value == "<<" {
			// A merge key carries fields from elsewhere, where the value's
			// form cannot be checked (the Phase 36 part 2 audit: `<<:
			// {value: 0454}` loaded 300). Python refuses it too.
			b.literalProblem = model.BudgetMergeProblem
			return nil
		}
		if node.Content[index].Value != "value" {
			continue
		}
		value := node.Content[index+1]
		// Style 0 is plain: not quoted, not a block scalar, and with no
		// explicit tag (yaml.TaggedStyle is a style bit). An alias is not
		// a scalar.
		// An anchor (`&v 300`) is not plain either: Python reads it so.
		plain := value.Kind == yaml.ScalarNode && value.Style == 0 && value.Anchor == ""
		b.literalProblem = model.BudgetLiteralProblem(value.Value, plain)
	}
	return nil
}

// BudgetExtractor is the provenance extractor of a culprit.yaml budget.
const BudgetExtractor = "culprit.yaml budgets"

// BudgetSkipWant is the `want` of a skip reporting an `x-culprit-budget`
// that is not a budget. Its own name, not http_routes: a skip under a want
// says that want was not extracted, and the routes were.
const BudgetSkipWant = "budgets"

// budgetValue is a budget's whole number of milliseconds, 1 to
// model.MaxBudgetMS — the same bounds culprit_model.latency.Budget holds,
// so a manifest `culprit check` accepts is one `apply-model` accepts.
func budgetValue(value any) (int, bool) {
	var whole int
	switch typed := value.(type) {
	case int:
		whole = typed
	case int64:
		if typed > model.MaxBudgetMS || typed < 1 {
			return 0, false
		}
		whole = int(typed)
	case uint64:
		if typed > model.MaxBudgetMS {
			return 0, false
		}
		whole = int(typed)
	case float64:
		if typed < 1 || typed > model.MaxBudgetMS || typed != float64(int(typed)) {
			return 0, false
		}
		whole = int(typed)
	default:
		return 0, false
	}
	return whole, whole >= 1 && whole <= model.MaxBudgetMS
}

// validateBudgets refuses a `budgets:` entry that cannot be measured
// against. Refused rather than warned, like every other check-time section:
// a budget that half-loads is a route silently never held to it.
func (m *Manifest) validateBudgets() error {
	first := map[string]int{}
	for index, budget := range m.Budgets {
		where := fmt.Sprintf("budgets[%d]", index)
		// Two entries for one subject and predicate in one file are one
		// source saying two things: the comparator sees one extractor and
		// no conflict, and the probe would measure one and drop the other
		// without a word (Phase 36 phase audit).
		key := budget.Subject + "\x00" + budget.Predicate
		if earlier, repeated := first[key]; repeated {
			return &PolicyError{Message: fmt.Sprintf(
				"%s repeats budgets[%d]: one subject and predicate may have one budget in a file",
				where, earlier)}
		}
		first[key] = index
		if strings.TrimSpace(budget.Why) == "" {
			return &PolicyError{Message: where +
				": `why` is required. A budget nobody explained is one nobody can safely change."}
		}
		if _, known := model.BudgetPredicates[budget.Predicate]; !known {
			return &PolicyError{Message: fmt.Sprintf(
				"%s: predicate %q is not one of %s", where, budget.Predicate,
				strings.Join(budgetPredicateNames(), ", "))}
		}
		if budget.literalProblem != "" {
			return &PolicyError{Message: where + ": `value`: " + budget.literalProblem}
		}
		if _, ok := budgetValue(budget.Value); !ok {
			return &PolicyError{Message: where +
				fmt.Sprintf(": `value` must be a whole number of milliseconds, 1 to %d", model.MaxBudgetMS)}
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
