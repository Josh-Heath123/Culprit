// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package extract

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Phase 38 part 2: a response_items_max budget, with `at:` or without, as
// the loader reads it and as the INTENT fact the probe is judged against.
// The corpus holds both readers to the same outcomes; this holds the fact.

func loadListManifest(t *testing.T, budgets string) (*Manifest, error) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	text := "version: 1\ncomponents:\n  - name: shop\n    kind: service\nbudgets:\n" + budgets
	if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
	return LoadManifest(path)
}

func TestAListBudgetIsOneFactWithItsPointer(t *testing.T) {
	manifest, err := loadListManifest(t, `  - subject: "http:shop/GET /items"
    predicate: response_items_max
    value: 50
    at: /items
    why: one page
  - subject: "http:shop/GET /tags"
    predicate: response_items_max
    value: 20
    why: one page
`)
	if err != nil {
		t.Fatal(err)
	}
	facts, err := BudgetFacts(manifest, "culprit.yaml", time.Unix(0, 0).UTC(), "c1")
	if err != nil {
		t.Fatal(err)
	}
	if len(facts) != 2 {
		t.Fatalf("facts: %+v", facts)
	}
	for index, want := range []struct {
		bound int
		at    string
	}{{50, "/items"}, {20, ""}} {
		bound, at, ok := model.ListBudget(facts[index].Value)
		if !ok || bound != want.bound || at != want.at || facts[index].Plane != model.PlaneIntent {
			t.Errorf("fact %d: %#v, want %d at %q", index, facts[index].Value, want.bound, want.at)
		}
	}
}

func TestAListBudgetIsRefusedWhereNothingCouldCountIt(t *testing.T) {
	for name, entry := range map[string]string{
		"on a POST route":  "  - subject: \"http:shop/POST /items\"\n    predicate: response_items_max\n    value: 5\n    why: x\n",
		"at not a pointer": "  - subject: \"http:shop/GET /items\"\n    predicate: response_items_max\n    value: 5\n    at: items\n    why: x\n",
		"at a number":      "  - subject: \"http:shop/GET /items\"\n    predicate: response_items_max\n    value: 5\n    at: 5\n    why: x\n",
		"at on a latency":  "  - subject: \"http:shop/GET /items\"\n    predicate: latency_p95_ms\n    value: 5\n    at: /items\n    why: x\n",
		"past its bound":   "  - subject: \"http:shop/GET /items\"\n    predicate: response_items_max\n    value: 1000001\n    why: x\n",
		"a bad escape":     "  - subject: \"http:shop/GET /items\"\n    predicate: response_items_max\n    value: 5\n    at: /a~2\n    why: x\n",
		"on a component":   "  - subject: \"component:shop\"\n    predicate: response_items_max\n    value: 5\n    why: x\n",
	} {
		if _, err := loadListManifest(t, entry); err == nil {
			t.Errorf("%s: loaded", name)
		} else if strings.Contains(err.Error(), "items\n") {
			t.Errorf("%s: the refusal quotes the value: %v", name, err)
		}
	}
}
