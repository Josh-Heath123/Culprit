package check_test

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/check"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/report"
)

// Bundle budgets in `culprit check` (Phase 38 part 1), on the recorded
// build in cli/testdata/build/vite: an entry over its budget is a finding
// of severity degrades in every format, naming its three largest files;
// at or under it nothing is reported; a missing manifest and a budgeted
// entry the build lacks are each a "Not checked" line.

// The three largest files of index.html's initial download, by gzipped size.
var indexLargest = []string{"assets/index-a1b2.js", "assets/shared-c3d4.js", "assets/index-9f8e.css"}

func writeBuildProject(t *testing.T, viteManifest, budgets string) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.CopyFS(filepath.Join(dir, "web"), os.DirFS(filepath.Join("..", "..", "testdata", "build", "vite"))); err != nil {
		t.Fatal(err)
	}
	manifest := "version: 1\ncomponents:\n  - name: web\n    kind: frontend\n    build:\n      vite_manifest: " +
		viteManifest + "\n" + budgets
	path := filepath.Join(dir, "culprit.yaml")
	if err := os.WriteFile(path, []byte(manifest), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func bundleBudget(entry string, value int) string {
	return "budgets:\n  - subject: \"bundle:web/" + entry + "\"\n    predicate: bundle_gzip_bytes_max\n    value: " +
		itoa(value) + "\n    why: the first page waits on it\n"
}

func itoa(n int) string {
	var digits []byte
	for n > 0 || len(digits) == 0 {
		digits = append([]byte{byte('0' + n%10)}, digits...)
		n /= 10
	}
	return string(digits)
}

func renderAll(t *testing.T, result check.Report) map[string]string {
	t.Helper()
	out := map[string]string{}
	for _, format := range []string{"text", "json", "sarif", "junit"} {
		var buffer bytes.Buffer
		if err := report.Render(&buffer, format, report.Input{
			Result: result.Result, Bundle: result.Bundle, Version: "test", Root: result.BaseDir,
		}); err != nil {
			t.Fatalf("%s: %v", format, err)
		}
		out[format] = buffer.String()
	}
	return out
}

func TestAnEntryOverItsBudgetIsAFindingInEveryFormat(t *testing.T) {
	result := runBudgetCheck(t, writeBuildProject(t, "web/out/.vite/manifest.json", bundleBudget("index.html", 1000)))
	if len(result.Result.Bundles) != 1 {
		t.Fatalf("bundles over budget: %+v", result.Result.Bundles)
	}
	finding := result.Result.Bundles[0]
	if finding.Severity != model.SeverityDegrades || finding.Subject != "bundle:web/index.html" {
		t.Errorf("finding: %s %s", finding.Severity, finding.Subject)
	}
	var largest []string
	for _, chunk := range finding.Largest {
		largest = append(largest, chunk.File)
	}
	if strings.Join(largest, ",") != strings.Join(indexLargest, ",") {
		t.Errorf("largest: %v, want %v", largest, indexLargest)
	}
	for format, rendered := range renderAll(t, result) {
		for _, want := range append([]string{"bundle:web/index.html"}, indexLargest...) {
			if !strings.Contains(rendered, want) {
				t.Errorf("%s does not name %s:\n%s", format, want, rendered)
			}
		}
		if strings.Contains(rendered, "lazy-e5f6.js") {
			t.Errorf("%s names the dynamically imported chunk", format)
		}
	}
	if got := check.CountFailing(result.Result, model.SeverityDegrades); got != 1 {
		t.Errorf("--fail-on degrades counts %d, want 1", got)
	}
	if got := check.CountFailing(result.Result, model.SeverityBreaksRequestPath); got != 0 {
		t.Errorf("--fail-on breaks_request_path counts %d, want 0", got)
	}
	if len(result.Result.Divergences) != 0 {
		t.Errorf("a bundle over budget was also a divergence: %+v", result.Result.Divergences)
	}
}

func TestAnEntryWithinItsBudgetReportsNothing(t *testing.T) {
	result := runBudgetCheck(t, writeBuildProject(t, "web/out/.vite/manifest.json",
		bundleBudget("index.html", 1_000_000)))
	if len(result.Result.Bundles) != 0 || len(result.Result.BuildNotChecked) != 0 {
		t.Fatalf("bundles %+v, not checked %+v", result.Result.Bundles, result.Result.BuildNotChecked)
	}
	for format, rendered := range renderAll(t, result) {
		if strings.Contains(rendered, "over budget") || strings.Contains(rendered, "bundles_over_budget") ||
			strings.Contains(rendered, "bundle_over_budget") {
			t.Errorf("%s reports a bundle within its budget:\n%s", format, rendered)
		}
	}
	if got := check.CountFailing(result.Result, model.SeverityCosmetic); got != 0 {
		t.Errorf("--fail-on any counts %d", got)
	}
	// The unbudgeted surface is routes no latency budget holds to a time;
	// a bundle budget alone does not switch it on.
	if result.Result.Budgets.Declared {
		t.Error("a bundle budget alone switched on the unbudgeted surface")
	}
}

// TestAnEntryAtItsBudgetIsWithinIt: over is strictly greater.
func TestAnEntryAtItsBudgetIsWithinIt(t *testing.T) {
	first := runBudgetCheck(t, writeBuildProject(t, "web/out/.vite/manifest.json", bundleBudget("index.html", 1000)))
	measured := first.Result.Bundles[0].Measured.Value
	exact := 0
	switch value := measured.(type) {
	case int64:
		exact = int(value)
	default:
		t.Fatalf("measured value of type %T", measured)
	}
	at := runBudgetCheck(t, writeBuildProject(t, "web/out/.vite/manifest.json", bundleBudget("index.html", exact)))
	if len(at.Result.Bundles) != 0 {
		t.Errorf("an entry at its budget (%d) was reported", exact)
	}
	over := runBudgetCheck(t, writeBuildProject(t, "web/out/.vite/manifest.json", bundleBudget("index.html", exact-1)))
	if len(over.Result.Bundles) != 1 {
		t.Errorf("an entry one byte over its budget was not reported")
	}
}

func TestAMissingManifestOrEntryIsNotChecked(t *testing.T) {
	for name, setup := range map[string]struct{ manifest, entry, want string }{
		"no manifest": {"web/dist/.vite/manifest.json", "index.html", "no build manifest at web/dist/.vite/manifest.json"},
		"no entry":    {"web/out/.vite/manifest.json", "checkout.html", "which the build does not have"},
	} {
		t.Run(name, func(t *testing.T) {
			result := runBudgetCheck(t, writeBuildProject(t, setup.manifest, bundleBudget(setup.entry, 1000)))
			if len(result.Result.Bundles) != 0 {
				t.Errorf("bundles: %+v", result.Result.Bundles)
			}
			for format, rendered := range renderAll(t, result) {
				if !strings.Contains(rendered, setup.want) || (name == "no entry" && !strings.Contains(rendered, setup.entry)) {
					t.Errorf("%s has no Not checked line saying %q:\n%s", format, setup.want, rendered)
				}
			}
		})
	}
}
