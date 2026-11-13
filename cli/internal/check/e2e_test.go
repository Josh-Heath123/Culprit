package check_test

import (
	"context"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/check"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// End to end, over two real source trees, through the real extractors.
//
// The fault corpus next door is hermetic: it feeds committed fact bundles
// to the engine and asserts the findings exactly. That is the right shape
// for an eval, and it leaves one thing unproven — that a real FastAPI app
// and a real React frontend, read by the real Python and Node extractors,
// produce subjects that actually meet.
//
// This test closes that gap by running the whole pipeline over
// `cli/testdata/demo`. Two of its components are the Phase 28 extraction
// fixtures, reused unmodified; the third, `billing`, is a small service
// with two faults planted in it on purpose, because the other two are
// correct and a corpus of correct fixtures cannot show that the tool
// finds anything.
//
// Between them they demonstrate all four of the phase's detection
// criteria by execution rather than by assertion:
//
//   - "detects a frontend calling a route the backend does not expose"
//   - "detects an ORM model whose column is absent from the migration head"
//   - "detects a config key read in code and absent from `.env.example`"
//   - "detects openapi.json disagreeing with the live route table"
//
// It needs `uv` and `node` on PATH, and it skips loudly rather than
// silently when they are absent — a skipped test that says nothing is
// indistinguishable from a passing one.
func TestTheDemoRepositoryProducesTheExpectedFindings(t *testing.T) {
	requireTool(t, "uv")
	requireTool(t, "node")

	manifest, err := filepath.Abs("../../testdata/demo/culprit.yaml")
	if err != nil {
		t.Fatal(err)
	}

	// Generous: the first run resolves a uv environment. The point of the
	// bound is that a hung extractor fails the test rather than the suite.
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Minute)
	defer cancel()

	report, err := check.Run(ctx, check.Options{
		ManifestPath: manifest,
		Now:          evalClock,
		Version:      "test",
	})
	if err != nil {
		t.Fatalf("check: %v", err)
	}

	byKey := map[string]model.Divergence{}
	for _, finding := range report.Result.Divergences {
		byKey[finding.Subject+" | "+finding.Predicate] = finding
	}

	t.Run("a route the frontend calls and the backend does not serve", func(t *testing.T) {
		// `/api/v2/orders/search` exists in the React fixture's call
		// sites and in no route the FastAPI app registers.
		finding, ok := byKey["http:orders-api/GET /api/v2/orders/search | calls"]
		if !ok {
			t.Fatalf("not found among:\n%s", list(report.Result.Divergences))
		}
		if finding.Severity != model.SeverityBreaksRequestPath {
			t.Errorf("severity is %s (%s)", finding.Severity, finding.SeverityReason)
		}
		// The finding has to name the file the developer should open, by
		// its **full** repo-relative path.
		//
		// This was `strings.Contains(..., "orders.ts")` and that was too
		// weak: it passed while the path carried the wrong component's
		// prefix, so a SARIF annotation pointing at a file that does not
		// exist looked fine here. A substring check on a path asserts
		// almost nothing about the part that has to be right.
		// Unprefixed here, and correctly so: this component's root is
		// `../fixtures/react-web`, outside the manifest directory, so no
		// repo-relative prefix exists and inventing a `../` one would be
		// worse than none. The prefixing itself is asserted on `billing`
		// below, and the cross-component case that broke it has its own
		// unit test in extract (TestRebaseTargetKeysOffTheProducingComponent).
		const expected = "src/api/orders.ts"
		if got := finding.Left.Provenance.Artefact; got != expected {
			t.Errorf("the call site is %q, expected %q — a path that does not "+
				"resolve produces no pull-request annotation, and no error "+
				"either", got, expected)
		}
	})

	t.Run("openapi.json disagreeing with the live route table", func(t *testing.T) {
		finding, ok := byKey["http:orders-api/GET /api/v1/orders/{} | status_codes"]
		if !ok {
			t.Fatalf("not found among:\n%s", list(report.Result.Divergences))
		}
		// The committed spec loses to the running application: rank 80
		// against rank 90. Which side is the reference decides which file
		// the report tells the reader to change, so it is asserted.
		if finding.Left.Provenance.ConfidenceRank <= finding.Right.Provenance.ConfidenceRank {
			t.Errorf("the reference side is rank %d, the other rank %d — "+
				"the higher-confidence source should be the reference",
				finding.Left.Provenance.ConfidenceRank,
				finding.Right.Provenance.ConfidenceRank)
		}
	})

	t.Run("an ORM column absent from the migration head", func(t *testing.T) {
		// `billing/models.py` declares invoices.total_cents; the two
		// migrations create id, created_at and reference and nothing else.
		finding, ok := byKey["schema:billing-db/public.invoices | columns"]
		if !ok {
			t.Fatalf("not found among:\n%s", list(report.Result.Divergences))
		}
		columns, isList := finding.Left.Value.([]any)
		if !isList {
			t.Fatalf("the reference side is not a column list: %#v", finding.Left.Value)
		}
		var found bool
		for _, column := range columns {
			if column == "total_cents" {
				found = true
			}
		}
		if !found {
			// If the models side does not name the column, the finding is
			// about something else and this test is passing by accident.
			t.Errorf("the models side does not list total_cents: %v", columns)
		}
		if finding.Left.Provenance.ConfidenceRank != 90 {
			t.Errorf("the ORM side is rank %d, expected 90",
				finding.Left.Provenance.ConfidenceRank)
		}
	})

	t.Run("a config key read in code and absent from .env.example", func(t *testing.T) {
		finding, ok := byKey["config:billing-api/BILLING_WEBHOOK_SECRET | read_by"]
		if !ok {
			t.Fatalf("not found among:\n%s", list(report.Result.Divergences))
		}
		if finding.Severity != model.SeverityBreaksRequestPath {
			// No default in code: `os.environ["BILLING_WEBHOOK_SECRET"]`
			// raises on import, so an unset key really does break the
			// request path. The two keys in Culprit's own repository that
			// *do* have defaults rank `degrades`, and the difference is
			// the whole point of the rule.
			t.Errorf("severity is %s (%s)", finding.Severity, finding.SeverityReason)
		}
	})

	t.Run("an in-tree component's paths gain its root as a prefix", func(t *testing.T) {
		// `billing` lives under the manifest directory, so its facts must
		// come back as `billing/...` — the form that resolves from the
		// repository root, which is the only form GitHub will annotate.
		finding, ok := byKey["config:billing-api/BILLING_WEBHOOK_SECRET | read_by"]
		if !ok {
			t.Fatalf("not found among:\n%s", list(report.Result.Divergences))
		}
		for _, side := range []model.Fact{finding.Left, finding.Right} {
			if !strings.HasPrefix(side.Provenance.Artefact, "billing/") {
				t.Errorf("%q is not rebased onto the component root",
					side.Provenance.Artefact)
			}
		}
	})

	t.Run("no rendered finding contains a config value", func(t *testing.T) {
		// The billing fixture's `.env.example` carries a placeholder
		// password. It must not survive into any side of any finding.
		for _, finding := range report.Result.Divergences {
			for _, side := range []model.Fact{finding.Left, finding.Right} {
				if text, isText := side.Value.(string); isText {
					if strings.Contains(text, "changeme") {
						t.Errorf("%s carries a config value: %q", finding.ID(), text)
					}
				}
			}
		}
	})

	t.Run("every finding explains itself", func(t *testing.T) {
		for _, finding := range report.Result.Divergences {
			if strings.TrimSpace(finding.Explanation) == "" {
				t.Errorf("%s has no explanation", finding.ID())
			}
			if strings.TrimSpace(finding.SeverityReason) == "" {
				t.Errorf("%s has no severity reason", finding.ID())
			}
		}
	})

	t.Run("gaps are reported as gaps", func(t *testing.T) {
		// `orders-db` has no source of its own, and the report must say
		// so by name rather than quietly returning fewer facts. This is
		// the Phase 28 honesty rule, and it is what keeps a report with
		// nine gaps in it from reading like a clean system.
		var named bool
		for _, skip := range report.Bundle.Skipped {
			if skip.Component == "orders-db" {
				named = true
			}
			if strings.TrimSpace(skip.Reason) == "" {
				t.Errorf("a skip for %s/%s has no reason", skip.Component, skip.Want)
			}
		}
		if !named {
			t.Error("orders-db has no source root and was not reported as a gap")
		}
	})
}

func requireTool(t *testing.T, name string) {
	t.Helper()
	if _, err := exec.LookPath(name); err != nil {
		t.Skipf("%s is not on PATH, so the end-to-end check cannot run "+
			"(the hermetic fault corpus in the same package still did)", name)
	}
}
