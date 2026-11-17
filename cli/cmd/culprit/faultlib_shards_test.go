package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"testing"
)

// The fault library runs in faultLibraryShards CI jobs (Phase 37 part 3):
// with the database fault it passed fifteen minutes in one. Each case is
// in exactly one shard, by a rule over the library, and
// TestTheFaultLibraryShardsCoverEveryCaseOnce proves it without Docker.

// faultLibraryShards is how many shards the CI job's matrix runs.
const faultLibraryShards = 2

// mcpLoops are the audience fault's loop through `culprit mcp` (Phase 35
// part 1).
var mcpLoops = []struct{ name, apply, verdict, reason string }{
	{name: "auth-audience", verdict: "verified"},
	{name: "wrong-fix", apply: "remint-wrong-audience", verdict: "not_resolved", reason: "probe.auth.token_shape"},
}

// libraryCases are every case the library runs, by its subtest name: each
// fault, each scenario (verify/<name>) and each MCP loop (mcp/<name>).
func libraryCases(library faultLibrary) []string {
	var cases []string
	for _, fault := range library.Faults {
		cases = append(cases, fault.Name)
	}
	for _, scenario := range library.Scenarios {
		cases = append(cases, "verify/"+scenario.Name)
	}
	for _, loop := range mcpLoops {
		cases = append(cases, "mcp/"+loop.name)
	}
	return cases
}

// shardOf is the shard a case runs in. The database's cases — walked from
// inventory-service, each with a statement window per reading — take
// shard 2; every other case, shard 1. Each shard then stays well under
// fifteen minutes.
func shardOf(library faultLibrary, name string) int {
	fault := strings.TrimPrefix(name, "verify/")
	for _, scenario := range library.Scenarios {
		if "verify/"+scenario.Name == name {
			fault = scenario.Fault
		}
	}
	for _, each := range library.Faults {
		if each.Name == fault && each.Environment == "faults-inventory" {
			return 2
		}
	}
	return 1
}

// shardFromEnvironment reads CULPRIT_FAULT_LIBRARY_SHARD: "" is every
// case (0), and k is shard k of faultLibraryShards.
func shardFromEnvironment(value string) (int, error) {
	if value == "" {
		return 0, nil
	}
	shard, err := strconv.Atoi(value)
	if err != nil || shard < 1 || shard > faultLibraryShards {
		return 0, fmt.Errorf("CULPRIT_FAULT_LIBRARY_SHARD=%q: want 1 to %d", value, faultLibraryShards)
	}
	return shard, nil
}

// mergeShardResults is the results file a shard writes: its own cases'
// entries as it found them, and the committed entry for every other case,
// in the library's order.
func mergeShardResults(library faultLibrary, shard int, ran faultResults, committed []byte) (faultResults, error) {
	var kept faultResults
	if err := json.Unmarshal(committed, &kept); err != nil {
		return faultResults{}, fmt.Errorf("the committed results: %w", err)
	}
	pick := func(name, caseName string, fresh, old []faultResult) (faultResult, bool) {
		from := old
		if shardOf(library, caseName) == shard {
			from = fresh
		}
		for _, result := range from {
			if result.Name == name {
				return result, true
			}
		}
		return faultResult{}, false
	}
	merged := faultResults{Why: ran.Why}
	for _, fault := range library.Faults {
		if result, ok := pick(fault.Name, fault.Name, ran.Faults, kept.Faults); ok {
			merged.Faults = append(merged.Faults, result)
		}
	}
	for _, scenario := range library.Scenarios {
		if result, ok := pick(scenario.Name, "verify/"+scenario.Name, ran.Scenarios, kept.Scenarios); ok {
			merged.Scenarios = append(merged.Scenarios, result)
		}
	}
	return merged, nil
}

func readLibrary(t *testing.T) faultLibrary {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "..", "testdata", "faultlib", "expected.json"))
	if err != nil {
		t.Fatal(err)
	}
	var library faultLibrary
	if err := json.Unmarshal(raw, &library); err != nil {
		t.Fatal(err)
	}
	return library
}

// TestTheFaultLibraryShardsCoverEveryCaseOnce: every case in expected.json,
// and every MCP loop, runs in exactly one shard; no shard is empty; and the
// CI job's matrix runs exactly shards 1 to faultLibraryShards.
func TestTheFaultLibraryShardsCoverEveryCaseOnce(t *testing.T) {
	library := readLibrary(t)
	cases := libraryCases(library)
	if len(cases) == 0 {
		t.Fatal("the library has no cases")
	}
	count := map[string]int{}
	for shard := 1; shard <= faultLibraryShards; shard++ {
		inShard := 0
		for _, name := range cases {
			if shardOf(library, name) == shard {
				count[name]++
				inShard++
			}
		}
		if inShard == 0 {
			t.Errorf("shard %d runs no case", shard)
		}
	}
	for _, name := range cases {
		if count[name] != 1 {
			t.Errorf("case %s runs in %d shards, want exactly 1", name, count[name])
		}
	}
	// Every scenario names a fault the library has, so its shard is the
	// fault's.
	for _, scenario := range library.Scenarios {
		found := false
		for _, fault := range library.Faults {
			found = found || fault.Name == scenario.Fault
		}
		if !found {
			t.Errorf("scenario %s names fault %s, which the library does not have", scenario.Name, scenario.Fault)
		}
	}

	workflow, err := os.ReadFile(filepath.Join(repoRoot, ".github", "workflows", "ci-cd.yml"))
	if err != nil {
		t.Fatal(err)
	}
	text := strings.ReplaceAll(string(workflow), "\r\n", "\n")
	start := strings.Index(text, "\n  fault-library:\n")
	if start < 0 {
		t.Fatal("the CI workflow has no fault-library job")
	}
	job := text[start+1:]
	if end := regexp.MustCompile(`\n  [a-z][a-z0-9-]*:\n`).FindStringIndex(job[1:]); end != nil {
		job = job[:end[0]+1]
	}
	matrix := regexp.MustCompile(`(?m)^\s+shard: \[([0-9, ]+)\]$`).FindStringSubmatch(job)
	if matrix == nil {
		t.Fatal("the fault-library job has no shard matrix")
	}
	var want []string
	for shard := 1; shard <= faultLibraryShards; shard++ {
		want = append(want, strconv.Itoa(shard))
	}
	if got := strings.ReplaceAll(matrix[1], " ", ""); got != strings.Join(want, ",") {
		t.Errorf("the job's matrix runs shards [%s], want [%s]", got, strings.Join(want, ","))
	}
	if !strings.Contains(job, "CULPRIT_FAULT_LIBRARY_SHARD=${{ matrix.shard }}") {
		t.Error("the fault-library job does not pass its shard to the test")
	}
}

// TestAShardKeepsTheOtherShardsResults: a shard's results file is its own
// cases as it found them and the committed entries for every other case.
func TestAShardKeepsTheOtherShardsResults(t *testing.T) {
	library := readLibrary(t)
	committed, err := os.ReadFile(filepath.Join("..", "..", "testdata", "faultlib", "results.json"))
	if err != nil {
		t.Fatal(err)
	}
	var kept faultResults
	if err := json.Unmarshal(committed, &kept); err != nil {
		t.Fatal(err)
	}
	// Every shard, faults and scenarios alike (Phase 38 part 1: it covered
	// shard 1's faults only). Each shard's fresh results are marked, and
	// only that shard's cases may carry the mark after the merge.
	for shard := 1; shard <= faultLibraryShards; shard++ {
		mark := fmt.Sprintf("changed-by-shard-%d", shard)
		ran := faultResults{Why: kept.Why}
		for _, result := range kept.Faults {
			if shardOf(library, result.Name) == shard {
				result.Verdict = mark
				ran.Faults = append(ran.Faults, result)
			}
		}
		for _, result := range kept.Scenarios {
			if shardOf(library, "verify/"+result.Name) == shard {
				result.Verdict = mark
				ran.Scenarios = append(ran.Scenarios, result)
			}
		}
		if len(ran.Faults)+len(ran.Scenarios) == 0 {
			t.Fatalf("shard %d has no committed result to merge", shard)
		}
		merged, err := mergeShardResults(library, shard, ran, committed)
		if err != nil {
			t.Fatal(err)
		}
		if len(merged.Faults) != len(kept.Faults) || len(merged.Scenarios) != len(kept.Scenarios) {
			t.Fatalf("shard %d merged %d faults and %d scenarios, committed %d and %d", shard,
				len(merged.Faults), len(merged.Scenarios), len(kept.Faults), len(kept.Scenarios))
		}
		for index, result := range merged.Faults {
			if result.Name != kept.Faults[index].Name {
				t.Errorf("shard %d: fault %d is %s, want %s: the library's order", shard, index, result.Name, kept.Faults[index].Name)
			}
			if changed := result.Verdict == mark; changed != (shardOf(library, result.Name) == shard) {
				t.Errorf("shard %d: fault %s: this shard's result kept = %v", shard, result.Name, changed)
			}
		}
		for index, result := range merged.Scenarios {
			if result.Name != kept.Scenarios[index].Name {
				t.Errorf("shard %d: scenario %d is %s, want %s: the library's order", shard, index, result.Name, kept.Scenarios[index].Name)
			}
			if changed := result.Verdict == mark; changed != (shardOf(library, "verify/"+result.Name) == shard) {
				t.Errorf("shard %d: scenario %s: this shard's result kept = %v", shard, result.Name, changed)
			}
		}
	}
	if _, err := shardFromEnvironment(strconv.Itoa(faultLibraryShards + 1)); err == nil {
		t.Error("a shard past faultLibraryShards is accepted")
	}
}

// TestTheLibrarysRoutesHaveTheirBudgets: the routes the library times are
// found in the demo's culprit.yaml by subject, without Docker.
func TestTheLibrarysRoutesHaveTheirBudgets(t *testing.T) {
	for _, route := range []budgetedRoute{readyRoute, productsRoute} {
		if locator := latencyBudgetLocator(t, route.subject); !strings.HasPrefix(locator, "budgets[") {
			t.Errorf("%s: locator %q", route.subject, locator)
		}
	}
	// Phase 38 part 2: and the list route its list budget.
	if locator := budgetLocator(t, productsRoute.subject, "response_items_max"); !strings.HasPrefix(locator, "budgets[") {
		t.Errorf("GET /products: list budget locator %q", locator)
	}
}
