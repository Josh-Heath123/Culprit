// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package check_test

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/check"
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

// TestTheUnboundedSurfaceNamesExactlyTheArrayRoutesWithNoBound is the
// criterion (as amended in "How Phase 38 is run"): over the recorded spec,
// with GET /tags budgeted, the unbounded surface is GET /orders alone —
// GET /products is bounded by maxItems, GET /tags by its budget, and
// /report, /health and /errors answer no list the rule can name. It is a
// coverage statement: no divergence, nothing --fail-on counts.
func TestTheUnboundedSurfaceNamesExactlyTheArrayRoutesWithNoBound(t *testing.T) {
	report := runBudgetCheck(t, writeListProject(t, `budgets:
  - subject: "http:shop/GET /tags"
    predicate: response_items_max
    value: 100
    at: /tags
    why: the tag picker shows them all
`))
	got := report.Result.Budgets.Unbounded
	if len(got) != 1 || got[0] != "http:shop/GET /orders" {
		t.Fatalf("unbounded: %v, want [http:shop/GET /orders]", got)
	}
	if failing := check.CountFailing(report.Result, model.SeverityCosmetic); failing != 0 {
		t.Errorf("--fail-on any counts %d: the unbounded surface is not a finding", failing)
	}
	for _, divergence := range report.Result.Divergences {
		if divergence.Predicate == model.PredicateResponseList || divergence.Predicate == "response_items_max" {
			t.Errorf("a list is a divergence: %+v", divergence)
		}
	}
	rendered := renderAll(t, report)
	if !strings.Contains(rendered["text"], "Unbounded surface (1)") ||
		!strings.Contains(rendered["text"], "http:shop/GET /orders") {
		t.Errorf("text:\n%s", rendered["text"])
	}
	var decoded struct {
		Unbounded []string `json:"unbounded"`
	}
	if err := json.Unmarshal([]byte(rendered["json"]), &decoded); err != nil || len(decoded.Unbounded) != 1 {
		t.Errorf("json unbounded: %v %v", decoded.Unbounded, err)
	}
	for _, format := range []string{"sarif", "junit"} {
		if strings.Contains(rendered[format], "GET /orders") {
			t.Errorf("%s reports the unbounded surface as a finding", format)
		}
	}
}

// TestNoBudgetsNoUnboundedSurface: as for the unbudgeted surface, a
// project that declares no budgets is not told every list is unbounded.
func TestNoBudgetsNoUnboundedSurface(t *testing.T) {
	report := runBudgetCheck(t, writeListProject(t, ""))
	if report.Result.Budgets.Declared || len(report.Result.Budgets.Unbounded) != 0 {
		t.Fatalf("unbounded with no budgets: %v", report.Result.Budgets.Unbounded)
	}
}

// TestAListBudgetDoesNotDeclareItsRoute: a latency budget on a route no
// source declares is still pointing at nothing when a list budget names
// the same route.
func TestAListBudgetDoesNotDeclareItsRoute(t *testing.T) {
	report := runBudgetCheck(t, writeListProject(t, `budgets:
  - subject: "http:shop/GET /typo"
    predicate: latency_p95_ms
    value: 100
    why: a mistyped route
  - subject: "http:shop/GET /typo"
    predicate: response_items_max
    value: 10
    why: a mistyped route
`))
	if len(report.Result.Budgets.Unmatched) != 1 || report.Result.Budgets.Unmatched[0].Subject != "http:shop/GET /typo" {
		t.Fatalf("unmatched: %+v", report.Result.Budgets.Unmatched)
	}
}
