package check_test

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/check"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Budgets in `culprit check` (Phase 36 part 1): two sources declaring
// different budgets for one route are an intent_conflict through the
// generic comparator; a budget on a route nothing else declares is
// reported; the unbudgeted surface is listed only when `budgets:` is
// declared; an unknown predicate is refused at load.

const budgetSpec = `{
  "openapi": "3.0.0",
  "paths": {
    "/items": {"get": {"responses": {"200": {}}, "x-culprit-budget": {"latency_p95_ms": 500}}},
    "/other": {"get": {"responses": {"200": {}}}},
    "/bad": {"get": {"responses": {"200": {}}, "x-culprit-budget": {"latency_p99_ms": 5}}}
  }
}`

func writeBudgetProject(t *testing.T, budgets string) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(dir, "shop"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "shop", "openapi.json"), []byte(budgetSpec), 0o644); err != nil {
		t.Fatal(err)
	}
	manifest := "version: 1\ncomponents:\n  - name: shop\nextract:\n  components:\n    shop:\n      root: shop\n" + budgets
	path := filepath.Join(dir, "culprit.yaml")
	if err := os.WriteFile(path, []byte(manifest), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func runBudgetCheck(t *testing.T, path string) check.Report {
	t.Helper()
	report, err := check.Run(context.Background(), check.Options{
		ManifestPath: path, Now: evalClock, Version: "test", SkipPlugins: true,
	})
	if err != nil {
		t.Fatalf("check: %v", err)
	}
	return report
}

const twoBudgets = `budgets:
  - subject: "http:shop/GET /items"
    predicate: latency_p95_ms
    value: 300
    why: the listing page waits on it
  - subject: "http:shop/GET /nowhere"
    predicate: latency_p50_ms
    value: 100
    why: a route that was renamed
`

func TestTwoSourcesWithDifferentBudgetsAreAnIntentConflict(t *testing.T) {
	report := runBudgetCheck(t, writeBudgetProject(t, twoBudgets))
	var found *model.Divergence
	for index, finding := range report.Result.Divergences {
		if finding.Subject == "http:shop/GET /items" && finding.Predicate == "latency_p95_ms" {
			found = &report.Result.Divergences[index]
		}
	}
	if found == nil {
		t.Fatalf("no budget conflict among %d divergences", len(report.Result.Divergences))
	}
	if found.Kind != model.KindIntentConflict {
		t.Errorf("kind %s, want intent_conflict", found.Kind)
	}
	if found.Left.Provenance.Extractor != extract.BudgetExtractor ||
		found.Left.Provenance.ConfidenceRank != model.RankDeveloperAssertion ||
		found.Right.Provenance.ConfidenceRank != model.RankCommittedSpec {
		t.Errorf("the culprit.yaml budget (rank 100) is not the reference against the spec's (rank 80): %+v / %+v",
			found.Left.Provenance, found.Right.Provenance)
	}
	if !model.ValuesEqual(found.Left.Value, 300) || !model.ValuesEqual(found.Right.Value, 500) {
		t.Errorf("values %v and %v, want 300 and 500", found.Left.Value, found.Right.Value)
	}
}

func TestABudgetOnARouteNothingDeclaresIsReported(t *testing.T) {
	report := runBudgetCheck(t, writeBudgetProject(t, twoBudgets))
	unmatched := report.Result.Budgets.Unmatched
	if len(unmatched) != 1 || unmatched[0].Subject != "http:shop/GET /nowhere" ||
		unmatched[0].Locator != "budgets[1]" {
		t.Fatalf("unmatched budgets: %+v", unmatched)
	}
	// /items is declared by the spec, so its budget points at something.
	for _, entry := range unmatched {
		if entry.Subject == "http:shop/GET /items" {
			t.Error("a budget on a declared route was reported as pointing at nothing")
		}
	}
}

func TestTheUnbudgetedSurfaceIsListedOnlyWhenBudgetsAreDeclared(t *testing.T) {
	report := runBudgetCheck(t, writeBudgetProject(t, twoBudgets))
	got := strings.Join(report.Result.Budgets.Unbudgeted, ", ")
	if got != "http:shop/GET /bad, http:shop/GET /other" {
		t.Errorf("unbudgeted surface %q", got)
	}

	quiet := runBudgetCheck(t, writeBudgetProject(t, ""))
	if quiet.Result.Budgets.Declared || len(quiet.Result.Budgets.Unbudgeted) != 0 {
		t.Errorf("a project that declares no budgets:\n was told its routes lack them: %+v",
			quiet.Result.Budgets)
	}
}

func TestAnXCulpritBudgetThatIsNotABudgetIsASkipNotAFact(t *testing.T) {
	report := runBudgetCheck(t, writeBudgetProject(t, ""))
	for _, fact := range report.Bundle.Facts {
		if fact.Predicate == "latency_p99_ms" {
			t.Fatalf("an unknown budget predicate became a fact: %+v", fact)
		}
	}
	found := false
	for _, skip := range report.Bundle.Skipped {
		if skip.Want == extract.BudgetSkipWant && strings.Contains(skip.Reason, "latency_p99_ms") {
			found = true
		}
		if skip.Want == string(model.WantHTTPRoutes) && strings.Contains(skip.Reason, "x-culprit-budget") {
			t.Error("a bad budget was skipped under http_routes, which says the routes were not read")
		}
	}
	if !found {
		t.Errorf("no skip names the bad x-culprit-budget: %+v", report.Bundle.Skipped)
	}
}

// TestABudgetLoadsOnlyWhenWrittenAsPlainDecimalDigits holds the Go loader
// to the shared fixture's budget_literals (Phase 36 part 2). Part 1
// accepted a whole float (`300.0`), as the API's model then did; the
// review of part 1 decided both readers refuse every form but plain
// decimal digits, because the two YAML readers read `0454`, `1e3`, `0o454`
// and `300_000` as different numbers or as strings.
func TestABudgetLoadsOnlyWhenWrittenAsPlainDecimalDigits(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "shared", "tests", "latency_conformance.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Literals []struct {
			Literal string `json:"literal"`
			Plain   bool   `json:"plain"`
			Refused bool   `json:"refused"`
			Reason  string `json:"reason"`
		} `json:"budget_literals"`
	}
	if err := json.Unmarshal(raw, &fixture); err != nil || len(fixture.Literals) == 0 {
		t.Fatalf("the fixture's budget_literals: %v", err)
	}
	for _, c := range fixture.Literals {
		value := c.Literal
		if !c.Plain {
			value = `"` + c.Literal + `"`
		}
		budgets := "budgets:\n  - subject: \"http:shop/GET /items\"\n    predicate: latency_p95_ms\n" +
			"    value: " + value + "\n    why: w\n"
		_, err := extract.LoadManifest(writeBudgetProject(t, budgets))
		switch {
		case c.Refused && err == nil:
			t.Errorf("value: %s loaded, want refused", value)
		case c.Refused && !strings.Contains(err.Error(), c.Reason):
			t.Errorf("value: %s refused, but not for the fixture's reason: %v", value, err)
		case !c.Refused && err != nil:
			t.Errorf("value: %s refused: %v", value, err)
		}
	}
	// An alias and an explicit tag are not plain, whatever they resolve to.
	for name, budgets := range map[string]string{
		"an alias": "x-ms: &ms 300\nbudgets:\n  - {subject: \"http:shop/GET /items\", predicate: latency_p95_ms, value: *ms, why: w}\n",
		"a tag":    "budgets:\n  - {subject: \"http:shop/GET /items\", predicate: latency_p95_ms, value: !!int 300, why: w}\n",
	} {
		if _, err := extract.LoadManifest(writeBudgetProject(t, budgets)); err == nil {
			t.Errorf("%s loaded, want refused", name)
		}
	}
}

func TestABudgetIsRefusedAtLoadUnlessItIsWellFormed(t *testing.T) {
	cases := map[string]string{
		"unknown predicate": "budgets:\n  - {subject: \"http:shop/GET /items\", predicate: latency_p99_ms, value: 300, why: w}\n",
		"no why":            "budgets:\n  - {subject: \"http:shop/GET /items\", predicate: latency_p95_ms, value: 300}\n",
		"zero":              "budgets:\n  - {subject: \"http:shop/GET /items\", predicate: latency_p95_ms, value: 0, why: w}\n",
		"fraction":          "budgets:\n  - {subject: \"http:shop/GET /items\", predicate: latency_p95_ms, value: 2.5, why: w}\n",
		"text":              "budgets:\n  - {subject: \"http:shop/GET /items\", predicate: latency_p95_ms, value: fast, why: w}\n",
		"pattern":           "budgets:\n  - {subject: \"http:shop/*\", predicate: latency_p95_ms, value: 300, why: w}\n",
		"not canonical":     "budgets:\n  - {subject: \"http:Shop/get /items\", predicate: latency_p95_ms, value: 300, why: w}\n",
		"over the bound":    "budgets:\n  - {subject: \"http:shop/GET /items\", predicate: latency_p95_ms, value: 60001, why: w}\n",
		"huge":              "budgets:\n  - {subject: \"http:shop/GET /items\", predicate: latency_p95_ms, value: 5000000000000, why: w}\n",
		"repeated": "budgets:\n  - {subject: \"http:shop/GET /items\", predicate: latency_p95_ms, value: 300, why: w}\n" +
			"  - {subject: \"http:shop/GET /items\", predicate: latency_p95_ms, value: 900, why: w}\n",
	}
	for name, budgets := range cases {
		if _, err := extract.LoadManifest(writeBudgetProject(t, budgets)); err == nil {
			t.Errorf("%s: loaded, want refused", name)
		} else if name == "unknown predicate" && !strings.Contains(err.Error(), "latency_p99_ms") {
			t.Errorf("unknown predicate: the error does not name it: %v", err)
		}
	}
}

// TestABudgetValueIsNeverEchoed: error text is output (invariant 7). A
// value written where a budget goes is refused without the value in the
// error, so a credential pasted there does not reach stderr (the Phase 36
// part 2 invariant audit: it did).
func TestABudgetValueIsNeverEchoed(t *testing.T) {
	for _, secret := range []string{"postgres://u:hunter2@db/x", "ghp_0123456789abcdefghijklmnopqrstuvwxyzAB", "0o454"} {
		budgets := "budgets:\n  - subject: \"http:shop/GET /items\"\n    predicate: latency_p95_ms\n" +
			"    value: " + secret + "\n    why: w\n"
		_, err := extract.LoadManifest(writeBudgetProject(t, budgets))
		if err == nil {
			t.Fatalf("value: %s loaded", secret)
		}
		if strings.Contains(err.Error(), secret) || strings.Contains(err.Error(), "hunter2") {
			t.Errorf("the error echoes the value: %v", err)
		}
	}
}

// TestABudgetEntryWithAMergeKeyIsRefused: the shared fixture's
// budget_entries. A merge key brought `value: 0454` in past the form check
// and the Go loader read 300 (the Phase 36 part 2 audit).
func TestABudgetEntryWithAMergeKeyIsRefused(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "shared", "tests", "latency_conformance.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Entries []struct {
			Why    string `json:"why"`
			Entry  string `json:"entry"`
			Reason string `json:"reason"`
		} `json:"budget_entries"`
	}
	if err := json.Unmarshal(raw, &fixture); err != nil || len(fixture.Entries) == 0 {
		t.Fatalf("the fixture's budget_entries: %v", err)
	}
	for _, c := range fixture.Entries {
		_, err := extract.LoadManifest(writeBudgetProject(t, "budgets:\n"+c.Entry))
		if err == nil || !strings.Contains(err.Error(), c.Reason) {
			t.Errorf("%s: %v, want refused with %q", c.Why, err, c.Reason)
		}
		if c.Reason != model.BudgetMergeProblem {
			t.Errorf("%s: the fixture's reason is not model.BudgetMergeProblem", c.Why)
		}
	}
}
