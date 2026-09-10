package check_test

import (
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/check"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The Phase 30 eval corpus: `culprit diff` on committed captures.
//
// Same contract as the Phase 29 corpus in eval_test.go, extended to the
// CONFIGURED plane. Each fixture under cli/testdata/envdiff/ is a
// culprit.yaml, an INTENT bundle, one CONFIGURED capture per environment,
// and the **exact** set of findings that must come out — matched on
// subject, predicate, kind and, for a finding about one environment,
// which environment. Anything extra is a false positive against a
// baseline of zero.
//
// `clean-environments` is the fixture this corpus exists for. Two
// environments configured correctly still differ — their URLs name
// different hosts, one reads a secret by reference, both carry variables
// the code never mentions — and a diff that reported any of that would be
// turned off by the end of its first week.

const envdiffDir = "../../testdata/envdiff"

type envExpectation struct {
	Description string `json:"description"`
	Expected    []struct {
		Subject     string `json:"subject"`
		Predicate   string `json:"predicate"`
		Kind        string `json:"kind"`
		Environment string `json:"environment"`
		Severity    string `json:"severity"`
	} `json:"expected"`
	FalsePositives int `json:"false_positives"`
}

func TestEnvironmentDiffCorpus(t *testing.T) {
	entries, err := os.ReadDir(envdiffDir)
	if err != nil {
		t.Fatalf("the envdiff corpus is missing: %v", err)
	}
	found := 0
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		found++
		t.Run(entry.Name(), func(t *testing.T) {
			runEnvFixture(t, filepath.Join(envdiffDir, entry.Name()))
		})
	}
	if found == 0 {
		t.Fatal("the envdiff corpus is empty")
	}
}

func runEnvFixture(t *testing.T, directory string) {
	t.Helper()
	manifest, err := extract.LoadManifest(filepath.Join(directory, "culprit.yaml"))
	if err != nil {
		t.Fatalf("culprit.yaml: %v", err)
	}
	var intent model.CaptureBundle
	readJSON(t, filepath.Join(directory, "intent.json"), &intent)
	var want envExpectation
	readJSON(t, filepath.Join(directory, "expected.json"), &want)

	var captures []model.CaptureBundle
	files, _ := filepath.Glob(filepath.Join(directory, "*.json"))
	sort.Strings(files)
	for _, file := range files {
		base := filepath.Base(file)
		if base == "intent.json" || base == "expected.json" {
			continue
		}
		var capture model.CaptureBundle
		readJSON(t, file, &capture)
		if capture.Plane != model.PlaneConfigured {
			t.Fatalf("%s is not a CONFIGURED capture", base)
		}
		for index, fact := range capture.Facts {
			if err := fact.Validate(); err != nil {
				t.Fatalf("%s facts.%d: %v", base, index, err)
			}
		}
		captures = append(captures, capture)
	}

	invariants, err := extract.InvariantFacts(manifest, "culprit.yaml", evalClock, intent.CaptureID)
	if err != nil {
		t.Fatalf("invariants: %v", err)
	}
	intent.Facts = append(intent.Facts, invariants...)
	result := check.Compare(manifest, intent, captures, evalClock)

	// Identity first, for the same reason as the Phase 29 corpus: two
	// findings sharing an identity overwrite each other on upload.
	produced := map[string]model.Divergence{}
	for _, finding := range result.Divergences {
		if existing, clash := produced[finding.ID()]; clash {
			t.Errorf("two findings share an identity:\n  %s\n  %s", describe(existing), describe(finding))
		}
		produced[finding.ID()] = finding
	}

	for _, expected := range want.Expected {
		signature := strings.Join([]string{
			expected.Subject, expected.Predicate, expected.Kind, expected.Environment}, " | ")
		matched := ""
		for id, finding := range produced {
			if finding.Subject != expected.Subject || finding.Predicate != expected.Predicate ||
				string(finding.Kind) != expected.Kind {
				continue
			}
			if expected.Environment != "" && finding.Right.Environment != expected.Environment {
				continue
			}
			matched = id
			break
		}
		if matched == "" {
			t.Errorf("MISSED: %s\n  the fixture is: %s\n  produced instead:\n%s",
				signature, want.Description, list(result.Divergences))
			continue
		}
		finding := produced[matched]
		delete(produced, matched)
		if expected.Severity != "" && string(finding.Severity) != expected.Severity {
			t.Errorf("%s: severity %s, expected %s (%s)",
				signature, finding.Severity, expected.Severity, finding.SeverityReason)
		}
		if strings.TrimSpace(finding.Explanation) == "" || strings.TrimSpace(finding.SeverityReason) == "" {
			t.Errorf("%s: a finding must explain itself and its severity", signature)
		}
	}

	if len(produced) != want.FalsePositives {
		names := make([]string, 0, len(produced))
		for _, finding := range produced {
			names = append(names, "  "+describe(finding)+" ["+string(finding.Kind)+"]")
		}
		sort.Strings(names)
		t.Errorf("false positives: %d, baseline is %d\n%s\n"+
			"Do not raise the baseline to make this pass - see testdata/faults/README.md.",
			len(produced), want.FalsePositives, strings.Join(names, "\n"))
	}
}
