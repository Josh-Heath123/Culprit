package check_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Lists in `culprit check` (Phase 38 part 2), over the recorded spec in
// testdata/lists: the Go OpenAPI reader's response_list facts.

func writeListProject(t *testing.T, budgets string) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.CopyFS(dir, os.DirFS(filepath.Join("..", "..", "testdata", "lists"))); err != nil {
		t.Fatal(err)
	}
	manifest := "version: 1\ncomponents:\n  - name: shop\nextract:\n  components:\n    shop:\n      root: shop\n" + budgets
	path := filepath.Join(dir, "culprit.yaml")
	if err := os.WriteFile(path, []byte(manifest), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestTheSpecsListsAreRead(t *testing.T) {
	report := runBudgetCheck(t, writeListProject(t, ""))
	lists := map[string]any{}
	for _, fact := range report.Bundle.Facts {
		if fact.Predicate != model.PredicateResponseList {
			continue
		}
		if fact.Plane != model.PlaneIntent || fact.Provenance.ConfidenceRank != model.RankCommittedSpec {
			t.Errorf("%s: plane %s rank %d", fact.Subject, fact.Plane, fact.Provenance.ConfidenceRank)
		}
		value, _ := fact.Value.(map[string]any)
		lists[fact.Subject] = value["max_items"]
	}
	want := map[string]any{
		"http:shop/GET /products": 50,  // an envelope, through a $ref, maxItems 50
		"http:shop/GET /orders":   nil, // a top-level array, no maxItems
		"http:shop/GET /tags":     nil, // an envelope, inline
	}
	if len(lists) != len(want) {
		t.Errorf("lists: %v, want %v (two arrays, no array, no JSON and a non-2xx list are not lists)", lists, want)
	}
	for subject, bound := range want {
		got, found := lists[subject]
		if !found || !model.ValuesEqual(got, bound) {
			t.Errorf("%s: max_items %v (found %v), want %v", subject, got, found, bound)
		}
	}
}
