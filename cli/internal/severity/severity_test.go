package severity_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/severity"
)

const manifest = `version: 1
components:
  - name: web
    kind: frontend
    connections:
      - to: orders-api
        kind: http
        criticality: on_request_path
  - name: orders-api
    kind: service
    connections:
      - to: search-indexer
        kind: queue
        criticality: background
  - name: search-indexer
    kind: worker
`

func load(t *testing.T, text string) *extract.Manifest {
	t.Helper()
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	loaded, err := extract.LoadManifest(path)
	if err != nil {
		t.Fatalf("culprit.yaml: %v", err)
	}
	return loaded
}

func subject(t *testing.T, kind model.SubjectKind, parts model.Parts) string {
	t.Helper()
	built, err := model.BuildSubject(kind, parts)
	if err != nil {
		t.Fatal(err)
	}
	return built
}

// TestSeverityComesFromTheGraph is §2.5's rule, checked case by case.
//
// Each row is a sentence from the plan made executable: a subject on a
// known request path breaks requests, one behind a `background` edge
// degrades, an unreferenced config key is cosmetic.
func TestSeverityComesFromTheGraph(t *testing.T) {
	loaded := load(t, manifest)

	route := subject(t, model.KindHTTP, model.Parts{
		"component": "orders-api", "method": "GET", "path": "/orders"})
	indexerRoute := subject(t, model.KindHTTP, model.Parts{
		"component": "search-indexer", "method": "POST", "path": "/reindex"})
	readKey := subject(t, model.KindConfig, model.Parts{
		"component": "orders-api", "key": "DATABASE_URL"})
	unreadKey := subject(t, model.KindConfig, model.Parts{
		"component": "orders-api", "key": "LEGACY_FEATURE_FLAG"})
	dependency := subject(t, model.KindDep, model.Parts{
		"component": "orders-api", "dependency": "pydantic"})
	unknownComponent := subject(t, model.KindHTTP, model.Parts{
		"component": "billing-api", "method": "GET", "path": "/invoices"})

	// The classifier learns which config keys are read from the capture,
	// so the bundle it is built with is part of the input, not decoration.
	bundle := model.CaptureBundle{Facts: []model.Fact{{
		Plane: model.PlaneIntent, Subject: readKey, Predicate: model.PredicateReadBy,
		Value: true,
	}}}
	classifier := severity.NewClassifier(loaded, bundle)

	for _, testCase := range []struct {
		name     string
		subject  string
		expected model.Severity
	}{
		{"a route on the request path", route, model.SeverityBreaksRequestPath},
		{"a route behind a background edge", indexerRoute, model.SeverityDegrades},
		{"a config key the code reads", readKey, model.SeverityBreaksRequestPath},
		{"a config key nothing reads", unreadKey, model.SeverityCosmetic},
		{"a declared dependency version", dependency, model.SeverityCosmetic},
		{"a component not in the model", unknownComponent, model.SeverityUnknown},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			got, reason := classifier.Classify(model.Divergence{Subject: testCase.subject})
			if got != testCase.expected {
				t.Errorf("got %s, expected %s (%s)", got, testCase.expected, reason)
			}
			if reason == "" {
				// A severity nobody can trace back to their own manifest is
				// a severity nobody will trust, and the first thing anyone
				// does with a tool that fails their build is ask why.
				t.Error("no reason given")
			}
		})
	}
}

// TestBackgroundEdgesAreNotFollowed is the over-reporting guard.
//
// `criticality: background` is the author saying "a request does not wait
// on this". Following such an edge would classify every async consumer as
// request-breaking, which is exactly what the field exists to prevent —
// and a tool that calls everything critical has said nothing.
func TestBackgroundEdgesAreNotFollowed(t *testing.T) {
	graph := severity.BuildGraph(load(t, manifest))
	if !graph.OnRequestPath("orders-api") {
		t.Error("orders-api is reachable from web along an on_request_path edge")
	}
	if graph.OnRequestPath("search-indexer") {
		t.Error("search-indexer sits behind a background edge and must not be on the path")
	}
}

// TestASeverityOverrideWins is field 10's escape hatch.
//
// The graph does not know everything — a config key it thinks is cosmetic
// may be the one that takes payments down — so the manifest can say
// otherwise, with a reason.
func TestASeverityOverrideWins(t *testing.T) {
	key := subject(t, model.KindConfig, model.Parts{
		"component": "orders-api", "key": "LEGACY_FEATURE_FLAG"})

	loaded := load(t, manifest+`
severity_overrides:
  - subject: "`+key+`"
    severity: breaks_request_path
    reason: >-
      Read by the payments reconciliation cron, which no extractor sees
      because it is configured in the scheduler, not in code.
`)
	classifier := severity.NewClassifier(loaded, model.CaptureBundle{})
	got, reason := classifier.Classify(model.Divergence{Subject: key})
	if got != model.SeverityBreaksRequestPath {
		t.Fatalf("the override was ignored: got %s", got)
	}
	if reason == "" {
		t.Error("an override with no reason in the report is unauditable")
	}
}

// TestAnOverrideWithoutAReasonIsRefused, and the same for a suppression.
//
// Field 8 states it directly. Refused at load, not warned about: a
// warning in a CI tool is read once and then never again, and a
// suppression nobody can audit is how a suppression list stops being a
// record of decisions and becomes a place bugs go.
func TestPolicyEntriesWithoutReasonsAreRefused(t *testing.T) {
	key := subject(t, model.KindConfig, model.Parts{
		"component": "orders-api", "key": "LEGACY_FEATURE_FLAG"})

	for _, testCase := range []struct{ name, section string }{
		{"a suppression", "\nsuppress:\n  - subject: \"" + key + "\"\n"},
		{"an override", "\nseverity_overrides:\n  - subject: \"" + key +
			"\"\n    severity: cosmetic\n"},
		{"an invariant", "\ninvariants:\n  - subject: \"" + key +
			"\"\n    predicate: exists\n"},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "culprit.yaml")
			if err := os.WriteFile(path, []byte(manifest+testCase.section), 0o600); err != nil {
				t.Fatal(err)
			}
			if _, err := extract.LoadManifest(path); err == nil {
				t.Error("loaded a policy entry with no reason")
			}
		})
	}
}
