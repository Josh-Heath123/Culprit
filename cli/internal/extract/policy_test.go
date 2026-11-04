package extract

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// TestASuppressionStopsWorkingOnItsExpiryDate is the whole point of the
// optional `expires` field: it turns "we will fix this later" into
// something that says so out loud on a date, instead of a line in
// `culprit.yaml` that silences a real fault forever.
func TestASuppressionStopsWorkingOnItsExpiryDate(t *testing.T) {
	suppression := Suppression{
		Subject: "http:orders-api/GET /orders",
		Reason:  "ships next sprint",
		Expires: "2026-06-30",
	}

	for _, testCase := range []struct {
		day    string
		active bool
	}{
		{"2026-06-29", true},
		{"2026-06-30", true}, // inclusive: it is still good on the day itself
		{"2026-07-01", false},
	} {
		day, err := time.Parse("2006-01-02", testCase.day)
		if err != nil {
			t.Fatal(err)
		}
		if got := suppression.Active(day); got != testCase.active {
			t.Errorf("on %s: active=%v, expected %v", testCase.day, got, testCase.active)
		}
	}

	forever := Suppression{Subject: "http:orders-api/GET /orders", Reason: "by design"}
	if !forever.Active(time.Now().AddDate(50, 0, 0)) {
		t.Error("a suppression with no expiry should not expire")
	}
}

// TestAnEmptySuppressionSilencesNothing.
//
// The failure direction matters. A malformed entry that matched
// everything would hide the whole report, and nobody would notice,
// because the report would say there was nothing to see.
func TestAnEmptySuppressionSilencesNothing(t *testing.T) {
	empty := Suppression{Reason: "malformed"}
	if empty.Matches("http:orders-api/GET /orders", "exists") {
		t.Error("a suppression with no subject matched a finding")
	}

	prefix := Suppression{Subject: "http:orders-api/*", Reason: "the whole surface"}
	if !prefix.Matches("http:orders-api/GET /orders", "exists") {
		t.Error("a prefix pattern did not match")
	}
	if prefix.Matches("http:billing-api/GET /invoices", "exists") {
		t.Error("a prefix pattern matched another component")
	}

	predicated := Suppression{
		Subject: "http:orders-api/*", Predicate: "status_codes", Reason: "x"}
	if predicated.Matches("http:orders-api/GET /orders", "exists") {
		t.Error("a predicate-scoped suppression silenced a different predicate")
	}
}

// TestApplySuppressionsMarksRatherThanRemoves.
//
// A suppressed finding keeps its severity and gains the reason somebody
// gave. Deleting it here would make the suppression list unauditable from
// the tool's own output, which is the failure `reason` is required to
// prevent.
func TestApplySuppressionsMarksRatherThanRemoves(t *testing.T) {
	manifest := &Manifest{Suppress: []Suppression{{
		Subject: "http:orders-api/GET /orders",
		Reason:  "the route is behind a feature flag",
	}}}
	findings := []model.Divergence{
		{Subject: "http:orders-api/GET /orders", Predicate: "exists",
			Severity: model.SeverityBreaksRequestPath, Status: model.StatusOpen},
		{Subject: "http:orders-api/POST /orders", Predicate: "exists",
			Severity: model.SeverityDegrades, Status: model.StatusOpen},
	}

	if count := manifest.ApplySuppressions(findings, time.Now()); count != 1 {
		t.Fatalf("suppressed %d findings, expected 1", count)
	}
	if len(findings) != 2 {
		t.Fatalf("a finding was removed; there should still be 2")
	}
	if findings[0].Status != model.StatusSuppressed {
		t.Error("the matching finding was not marked suppressed")
	}
	if findings[0].Severity != model.SeverityBreaksRequestPath {
		t.Error("suppression changed the severity; it should record what it would have been")
	}
	if findings[0].SuppressedBy == "" {
		t.Error("the reason did not travel with the finding")
	}
	if findings[1].Status != model.StatusOpen {
		t.Error("a non-matching finding was suppressed")
	}
}

// TestRebaseTargetKeysOffTheProducingComponent.
//
// SARIF annotations are matched by GitHub against repo-relative paths,
// and a path that does not match is not an error — the annotation is
// silently dropped. So an extractor's component-relative path has to
// gain the right prefix, and "the right prefix" is the one belonging to
// the component that *produced* the fact.
//
// The first version of this looked the prefix up by the **subject's**
// component, and the first version of this test passed because every
// fixture fact had `subject.component == producing component`. The one
// case that breaks is a client call — the whole of acceptance criterion
// 1 — where a `web` fact carries an `orders-api` subject and was
// prefixed with the backend's root, producing `api/src/lib/api.ts` for a
// file that lives at `frontend/src/lib/api.ts`.
//
// Hence the case below is the cross-component one, and it is asserted on
// the full path rather than a substring: a substring check on
// "api.ts" passes with a wrong prefix, which is exactly how the defect
// survived its own test.
func TestRebaseTargetKeysOffTheProducingComponent(t *testing.T) {
	// Produced by `web`, but naming a route on `orders-api`.
	facts := []model.Fact{
		{
			Subject:    "http:orders-api/GET /orders",
			Predicate:  model.PredicateCalls,
			Provenance: model.Provenance{Artefact: "src/lib/api.ts", Locator: "L246"},
		},
		{
			Subject:    "http:web/GET /dashboard",
			Provenance: model.Provenance{Artefact: "src/routes/App.tsx"},
		},
		{
			Subject:    "component:web",
			Provenance: model.Provenance{Artefact: ""},
		},
	}

	rebaseTarget(facts, Target{Component: "web", Root: filepath.Join("C:", "repo", "frontend")},
		filepath.Join("C:", "repo"))

	if got := facts[0].Provenance.Artefact; got != "frontend/src/lib/api.ts" {
		t.Errorf("a cross-component fact was rebased to %q, expected "+
			"frontend/src/lib/api.ts — the prefix must come from the component "+
			"that produced the fact, not from the one its subject names", got)
	}
	if got := facts[1].Provenance.Artefact; got != "frontend/src/routes/App.tsx" {
		t.Errorf("got %q, expected frontend/src/routes/App.tsx", got)
	}
	if got := facts[2].Provenance.Artefact; got != "" {
		t.Errorf("a fact with no artefact gained one: %q", got)
	}
}

// TestRebaseTargetLeavesOutsidePathsAlone.
//
// A component root outside the manifest directory would produce a `..`
// path, which GitHub certainly cannot resolve — worse than no prefix,
// because it looks like one.
func TestRebaseTargetLeavesOutsidePathsAlone(t *testing.T) {
	facts := []model.Fact{{
		Subject:    "http:vendor/GET /x",
		Provenance: model.Provenance{Artefact: "app/main.py"},
	}}

	rebaseTarget(facts, Target{Component: "vendor", Root: filepath.Join("C:", "elsewhere", "vendor")},
		filepath.Join("C:", "repo"))

	if got := facts[0].Provenance.Artefact; got != "app/main.py" {
		t.Errorf("an out-of-tree root produced a prefix: %q", got)
	}
}

// TestAnInvariantMayNotCarryAConfigValue.
//
// `culprit.yaml` is a file people commit. A tool that let somebody assert
// the expected value of a config key in it would be handing them a
// footgun with a straight face — architecture point 18, applied to the
// one place a human writes facts by hand.
func TestAnInvariantMayNotCarryAConfigValue(t *testing.T) {
	manifest := &Manifest{Invariants: []Invariant{{
		Subject:   "config:orders-api/DATABASE_URL",
		Predicate: "value",
		Value:     "postgresql://orders:hunter2@db/orders",
		Why:       "this is how it is set in production",
	}}}
	_, err := InvariantFacts(manifest, "culprit.yaml", time.Now(), "capture")
	if err == nil {
		t.Fatal("an invariant asserted a literal config value and was accepted")
	}
	if got := err.Error(); strings.Contains(got, "hunter2") {
		t.Errorf("the refusal echoed the value it refused: %s", got)
	}
}

// TestABareInvariantAssertsExistence — the common case, and the one that
// has to be one line in YAML or nobody will write it.
func TestABareInvariantAssertsExistence(t *testing.T) {
	manifest := &Manifest{Invariants: []Invariant{{
		Subject: "http:orders-api/GET /orders",
		Why:     "the mobile client cannot be updated remotely",
	}}}
	facts, err := InvariantFacts(manifest, "culprit.yaml", time.Now(), "capture")
	if err != nil {
		t.Fatal(err)
	}
	if len(facts) != 1 {
		t.Fatalf("got %d facts", len(facts))
	}
	if facts[0].Predicate != model.PredicateExists {
		t.Errorf("predicate is %q, expected %q", facts[0].Predicate, model.PredicateExists)
	}
	if facts[0].Provenance.ConfidenceRank != model.RankDeveloperAssertion {
		t.Errorf("rank is %d, expected %d — a human's assertion is the top of §2.4",
			facts[0].Provenance.ConfidenceRank, model.RankDeveloperAssertion)
	}
	if facts[0].Provenance.SourceKind != model.SourceAssertion {
		// Load-bearing: `diverge.enumerates` reads this to keep a
		// single hand-written line out of a component's reference set.
		t.Errorf("source_kind is %q, expected %q",
			facts[0].Provenance.SourceKind, model.SourceAssertion)
	}
}

// TestACatchAllSuppressionIsRefused.
//
// One line with one `reason` must not be able to turn the whole tool
// off. A `subject: "*"` would have matched every finding there is, and
// the result would be invisible: a report that says "0 divergences" and
// means "I was told not to look".
func TestACatchAllSuppressionIsRefused(t *testing.T) {
	for _, pattern := range []string{"*", "http*"} {
		if err := checkSubject("suppress[0]", pattern); err == nil {
			t.Errorf("%q was accepted as a suppression pattern", pattern)
		}
	}
	// A pattern that names a kind and a component is a reviewable
	// decision and stays allowed.
	for _, pattern := range []string{"http:orders-api/*", "config:orders-api/STRIPE_*"} {
		if err := checkSubject("suppress[0]", pattern); err != nil {
			t.Errorf("%q should be a valid pattern: %v", pattern, err)
		}
	}
}

// Phase 32.1: every culprit.yaml this repository ships loads under the
// closed connection-kind set. The root one said `queue` for Redis until
// this phase; nothing caught it, because only `just intent` read it and
// the Go loader accepted any kind.
func TestEveryShippedManifestLoads(t *testing.T) {
	for _, path := range []string{
		filepath.Join("..", "..", "..", "culprit.yaml"),
		filepath.Join("..", "..", "..", "demo-services", "culprit.yaml"),
	} {
		if _, err := LoadManifest(path); err != nil {
			t.Errorf("%s does not load: %v", path, err)
		}
	}
}

func TestAnUnknownConnectionKindIsRefused(t *testing.T) {
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	body := "components:\n  - name: a\n    connections:\n      - to: b\n        kind: queue\n  - name: b\n"
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	_, err := LoadManifest(path)
	if err == nil || !strings.Contains(err.Error(), `"queue"`) {
		t.Fatalf("a connection of kind queue loaded (err=%v); the kind set is closed", err)
	}
}
