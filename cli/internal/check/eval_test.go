package check_test

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/diverge"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/severity"
)

// The eval suite (Phase 29 field 13).
//
// # What this is
//
// A corpus under `cli/testdata/faults/`. Each fixture is a `culprit.yaml`,
// a committed `bundle.json` of the facts extraction would have produced,
// and an `expected.json` naming exactly the divergences that must come
// out — plus a `false_positives` baseline, which is `0` everywhere and
// is meant to stay there.
//
// The assertion is **exact**, in both directions. A missing expected
// finding fails, and so does an unexpected one. That second half is the
// one that matters: field 13 asks for the false-positive rate to be
// tracked per fixture, and a corpus that only checks for the findings it
// wants would let the tool grow noisy indefinitely without a single test
// going red. Noise is how a CI tool dies.
//
// # What it does not test, said plainly
//
// The bundles are committed inputs, not the output of running three
// language toolchains over a fixture repository. So this evaluates the
// *divergence engine* — comparison, severity, suppression, invariants —
// given facts, and it does not evaluate extraction.
//
// Extraction has its own corpus: `cli/testdata/fixtures/` with golden
// capture bundles (Phase 28), plus the Python and Node extractors' own
// test suites. The seam between the two is the subject URI, and that is
// held by a conformance fixture both languages read. Splitting the evals
// this way keeps them hermetic and fast enough to run on every commit,
// which a corpus that needed `uv` and `npx` per fixture would not be.
//
// The bundles are written to match what those extractors actually emit —
// same predicates, same confidence ranks, same provenance shape. If an
// extractor changes what it emits, this corpus goes stale silently, and
// that is the real risk here. It is written down in `docs/LIMITS.md`.

type expectation struct {
	Description string `json:"description"`
	Expected    []struct {
		Subject   string `json:"subject"`
		Predicate string `json:"predicate"`
		Severity  string `json:"severity"`
		Status    string `json:"status"`
	} `json:"expected"`
	FalsePositives int `json:"false_positives"`
}

const faultsDir = "../../testdata/faults"

// evalClock pins the run so a suppression's `expires` behaves the same
// on every machine and in every year the corpus is run in.
var evalClock = time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)

func TestFaultCorpus(t *testing.T) {
	entries, err := os.ReadDir(faultsDir)
	if err != nil {
		t.Fatalf("the fault corpus is missing: %v", err)
	}

	found := 0
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		found++
		t.Run(entry.Name(), func(t *testing.T) {
			runFixture(t, filepath.Join(faultsDir, entry.Name()))
		})
	}
	if found == 0 {
		t.Fatal("the fault corpus is empty")
	}
}

func runFixture(t *testing.T, directory string) {
	t.Helper()

	manifest, err := extract.LoadManifest(filepath.Join(directory, "culprit.yaml"))
	if err != nil {
		t.Fatalf("culprit.yaml: %v", err)
	}

	var bundle model.CaptureBundle
	readJSON(t, filepath.Join(directory, "bundle.json"), &bundle)

	var want expectation
	readJSON(t, filepath.Join(directory, "expected.json"), &want)

	// The same six steps `check.Run` performs, minus extraction — which
	// is the one step a committed bundle replaces.
	invariants, err := extract.InvariantFacts(manifest, "culprit.yaml", evalClock, bundle.CaptureID)
	if err != nil {
		t.Fatalf("invariants: %v", err)
	}
	bundle.Facts = append(bundle.Facts, invariants...)

	result := diverge.Compare(bundle, diverge.Options{Now: evalClock})
	severity.NewClassifier(manifest, bundle).Apply(result.Divergences)
	manifest.ApplySuppressions(result.Divergences, evalClock)

	compare(t, want, result)
}

// compare asserts the produced set against the expected set exactly.
func compare(t *testing.T, want expectation, result diverge.Result) {
	t.Helper()

	// Keyed by identity, not by (subject, predicate).
	//
	// It was (subject, predicate) first, and that made this gate unable
	// to see the thing it exists to see: a second divergence on a pair
	// already named in expected.json overwrote the first in the map and
	// was never counted as a false positive. The suite whose whole point
	// is "exact in both directions" was silently exact in one.
	//
	// It is also the gate that should have caught the identity collision
	// in Divergence.ID(), and could not, for the same reason — two
	// findings about one (subject, predicate) collapsing into one entry
	// is exactly the bug, reproduced in the test that was supposed to
	// detect it.
	produced := map[string]model.Divergence{}
	for _, finding := range result.Divergences {
		if existing, clash := produced[finding.ID()]; clash {
			t.Errorf("two findings share an identity, so one would silently "+
				"overwrite the other on upload:\n  %s\n  %s\n  id: %s",
				describe(existing), describe(finding), finding.ID())
		}
		produced[finding.ID()] = finding
	}

	// Expected entries name a (subject, predicate); resolve each to the
	// finding that matches, so a fixture stays readable without having to
	// spell out both provenances.
	find := func(subject, predicate string) (model.Divergence, string, bool) {
		for id, finding := range produced {
			if finding.Subject == subject && finding.Predicate == predicate {
				return finding, id, true
			}
		}
		return model.Divergence{}, "", false
	}

	for _, expected := range want.Expected {
		signature := expected.Subject + " | " + expected.Predicate
		finding, id, ok := find(expected.Subject, expected.Predicate)
		if !ok {
			t.Errorf("MISSED: %s\n  the fixture is %s\n  produced instead:\n%s",
				signature, want.Description, list(result.Divergences))
			continue
		}
		delete(produced, id)

		if expected.Severity != "" && string(finding.Severity) != expected.Severity {
			t.Errorf("%s: severity is %s, expected %s (%s)",
				signature, finding.Severity, expected.Severity, finding.SeverityReason)
		}
		status := expected.Status
		if status == "" {
			status = string(model.StatusOpen)
		}
		if string(finding.Status) != status {
			t.Errorf("%s: status is %s, expected %s",
				signature, finding.Status, status)
		}
		if strings.TrimSpace(finding.Explanation) == "" {
			// A finding with no explanation is a finding nobody can act
			// on, which is worse than no finding at all.
			t.Errorf("%s: no explanation", signature)
		}
	}

	// Everything left over is a false positive.
	if len(produced) != want.FalsePositives {
		names := make([]string, 0, len(produced))
		for _, finding := range produced {
			names = append(names, "  "+describe(finding))
		}
		sort.Strings(names)
		t.Errorf("false positives: %d, baseline is %d\n%s\n"+
			"A finding this fixture did not ask for is noise. Either the "+
			"comparator got something wrong, or the fixture is now a "+
			"legitimate example of a fault it does not document — and if "+
			"it is the second, say so in expected.json rather than raising "+
			"the baseline.",
			len(produced), want.FalsePositives, strings.Join(names, "\n"))
	}
}

// describe renders one finding with both its sources, because a false
// positive that names only the subject leaves the reader guessing which
// two things the comparator thought disagreed.
func describe(finding model.Divergence) string {
	return fmt.Sprintf("%s | %s [%s] %s (%s vs %s)",
		finding.Subject, finding.Predicate, finding.Severity, finding.Explanation,
		source(finding.Left), source(finding.Right))
}

func source(fact model.Fact) string {
	if fact.Provenance.Artefact != "" {
		return fact.Provenance.Extractor + ":" + fact.Provenance.Artefact
	}
	return fact.Provenance.Extractor
}

func list(divergences []model.Divergence) string {
	if len(divergences) == 0 {
		return "    (nothing)"
	}
	lines := make([]string, 0, len(divergences))
	for _, finding := range divergences {
		lines = append(lines, fmt.Sprintf("    %s | %s [%s]",
			finding.Subject, finding.Predicate, finding.Severity))
	}
	sort.Strings(lines)
	return strings.Join(lines, "\n")
}

func readJSON(t *testing.T, path string, into any) {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("%s: %v", path, err)
	}
	if err := json.Unmarshal(data, into); err != nil {
		t.Fatalf("%s: %v", path, err)
	}
}
