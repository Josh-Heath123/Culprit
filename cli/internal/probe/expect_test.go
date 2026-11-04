package probe

import (
	"context"
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Phase 31.1 field 13: "A test that `expected_source` is set whenever a
// matching INTENT fact exists, and that the probe returns `inconclusive`
// with a reason when none does."

// intentFact is an INTENT fact as an extractor would emit it.
func intentFact(subject, predicate string, value any, artefact string, rank int) model.Fact {
	return model.Fact{
		Plane: model.PlaneIntent, Subject: subject, Predicate: predicate, Value: value,
		Provenance: model.Provenance{
			SourceKind: model.SourceSpec, Extractor: "test-extractor@1",
			Artefact: artefact, Locator: "L1", ConfidenceRank: rank,
		},
	}
}

type expectationCase struct {
	probeID string
	target  string
	inputs  map[string]any
	deps    Deps
	// fact is the declaration this request should resolve to.
	fact model.Fact
}

// expectationCases are the four probes that take their expectation from
// extraction. Each request is one a user would actually type; each fact
// is what the matching extractor actually emits for it (subject and
// predicate checked against `culprit intent` on this repository).
func expectationCases() []expectationCase {
	clock := fixedClock()
	return []expectationCase{
		{
			probeID: "probe.http.route_conformance",
			target:  "connection:order-service->inventory-service",
			inputs:  map[string]any{"url": "http://inventory.internal/stock/42"},
			deps:    Deps{HTTP: &fakeHTTP{response: HTTPResponse{Status: 200}}, Now: clock},
			fact: intentFact(
				model.MustBuildSubject(model.KindHTTP, model.Parts{
					"component": "inventory-service", "method": "GET", "path": "/stock/{sku}"}),
				model.PredicateExists, map[string]any{"method": "GET", "path": "/stock/{sku}"},
				"openapi.json", 80),
		},
		{
			probeID: "probe.db.schema_conformance",
			target: model.MustBuildSubject(model.KindSchema, model.Parts{
				"database": "orders-db", "namespace": "public", "table": "orders"}),
			deps: Deps{Database: fakeDatabase{columns: []TableColumn{
				{Name: "id"}, {Name: "total_cents"}}}, Now: clock},
			fact: intentFact(
				model.MustBuildSubject(model.KindSchema, model.Parts{
					"database": "orders-db", "namespace": "public", "table": "orders"}),
				model.PredicateColumns, []any{"id", "total_cents"}, "migrations/versions", 80),
		},
		{
			probeID: "probe.config.present",
			target:  "component:inventory-service",
			inputs:  map[string]any{"key": "JWT_SECRET_KEY"},
			deps:    Deps{Config: fakeConfig{present: true}, Now: clock},
			fact: intentFact(
				model.MustBuildSubject(model.KindConfig, model.Parts{
					"component": "inventory-service", "key": "JWT_SECRET_KEY"}),
				model.PredicateRequired, true, "app/config.py", 60),
		},
		{
			probeID: "probe.dep.version",
			target:  "component:inventory-service",
			inputs:  map[string]any{"package": "stripe"},
			deps:    Deps{Packages: fakePackages{version: "7.1.0", found: true}, Now: clock},
			fact: intentFact(
				model.MustBuildSubject(model.KindDep, model.Parts{
					"component": "inventory-service", "dependency": "stripe"}),
				model.PredicateVersion, "==7.1.0", "pyproject.toml", 80),
		},
	}
}

func runWith(t *testing.T, expectations *Expectations, testCase expectationCase) model.Reading {
	t.Helper()
	runner := NewRunner(Options{
		Ledger: grantEverything(t), Deps: testCase.deps, Expectations: expectations,
	})
	readings := runner.Run(context.Background(), []Request{{
		ProbeID: testCase.probeID, Target: testCase.target, Environment: "staging",
		Inputs: testCase.inputs,
	}})
	if err := readings[0].Validate(); err != nil {
		t.Fatalf("reading does not validate: %v", err)
	}
	return readings[0]
}

func TestExpectedSourceIsSetWheneverAMatchingIntentFactExists(t *testing.T) {
	for _, testCase := range expectationCases() {
		t.Run(testCase.probeID, func(t *testing.T) {
			// Noise the resolver must not pick: another component's fact on
			// the same predicate, and a CONFIGURED fact on the same subject.
			noise := intentFact("config:payments-service/JWT_SECRET_KEY",
				testCase.fact.Predicate, true, "elsewhere", 100)
			configured := testCase.fact
			configured.Plane = model.PlaneConfigured
			configured.Provenance.Artefact = "a-capture"

			reading := runWith(t,
				NewExpectations([]model.Fact{noise, testCase.fact, configured}), testCase)

			if reading.Verdict != model.VerdictPass {
				t.Errorf("verdict = %q (reason %q); this request conforms to its declaration",
					reading.Verdict, reading.Reason)
			}
			if reading.ExpectedSource == nil {
				t.Fatal("a matching INTENT fact exists but expected_source is null")
			}
			if reading.ExpectedSource.Artefact != testCase.fact.Provenance.Artefact {
				t.Errorf("expected_source names %q, want the declaring artefact %q",
					reading.ExpectedSource.Artefact, testCase.fact.Provenance.Artefact)
			}
		})
	}
}

func TestWithoutADeclarationTheProbeIsInconclusiveAndSaysWhatItLookedFor(t *testing.T) {
	for _, testCase := range expectationCases() {
		t.Run(testCase.probeID, func(t *testing.T) {
			// The same request, against an extraction that declares nothing
			// about this subject.
			reading := runWith(t, NewExpectations(nil), testCase)

			if reading.Verdict != model.VerdictInconclusive {
				t.Errorf("verdict = %q, want inconclusive: a measurement with no "+
					"reference is not a conformance verdict", reading.Verdict)
			}
			if reading.ExpectedSource != nil {
				t.Errorf("expected_source is set with nothing declared: %+v", reading.ExpectedSource)
			}
			// The reason names the subject *measured* — for a concrete URL
			// that is /stock/42, not the template it would have matched —
			// and the predicate it looked for.
			for _, want := range []string{"no INTENT fact declares ", " " + testCase.fact.Predicate} {
				if !strings.Contains(reading.Reason, want) {
					t.Errorf("reason %q does not say what it looked for (%q)", reading.Reason, want)
				}
			}
		})
	}
}

// TestTheHighestRankWinsAndTheLoserIsNamed is §0.3: rank picks a default,
// it never discards.
func TestTheHighestRankWinsAndTheLoserIsNamed(t *testing.T) {
	testCase := expectationCases()[1] // db.schema_conformance
	introspected := testCase.fact
	introspected.Provenance.Artefact = "app.main:app"
	introspected.Provenance.ConfidenceRank = 90
	migrations := testCase.fact
	migrations.Value = []any{"id"} // the migrations disagree
	migrations.Provenance.ConfidenceRank = 80

	reading := runWith(t, NewExpectations([]model.Fact{migrations, introspected}), testCase)

	if reading.ExpectedSource == nil || reading.ExpectedSource.Artefact != "app.main:app" {
		t.Fatalf("expected_source = %+v, want the rank-90 source", reading.ExpectedSource)
	}
	var conflict string
	for _, item := range reading.Evidence {
		if item.Kind == EvidenceIntentConflict {
			conflict = item.Value
		}
	}
	if conflict == "" {
		t.Fatal("two declarations disagreed and the reading does not say so")
	}
	for _, needle := range []string{"migrations/versions", "rank 80", "rank 90"} {
		if !strings.Contains(conflict, needle) {
			t.Errorf("conflict evidence %q does not name %q", conflict, needle)
		}
	}

	// Two sources that agree are not a conflict.
	agreeing := migrations
	agreeing.Value = introspected.Value
	reading = runWith(t, NewExpectations([]model.Fact{agreeing, introspected}), testCase)
	for _, item := range reading.Evidence {
		if item.Kind == EvidenceIntentConflict {
			t.Errorf("agreeing sources reported as a conflict: %s", item.Value)
		}
	}
}

func TestAConcreteURLMatchesTheMostSpecificDeclaredRoute(t *testing.T) {
	route := func(path, artefact string) model.Fact {
		return intentFact(model.MustBuildSubject(model.KindHTTP, model.Parts{
			"component": "orders", "method": "GET", "path": path}),
			model.PredicateExists, nil, artefact, 80)
	}
	expectations := NewExpectations([]model.Fact{
		route("/orders/{id}", "template"),
		route("/orders/latest", "literal"),
		route("/orders/{id}/lines", "deeper"),
	})
	manifest := httpRouteConformance{}.Manifest()

	for url, want := range map[string]string{
		"http://orders/orders/latest":   "literal",
		"http://orders/orders/42":       "template",
		"http://orders/orders/42/lines": "deeper",
		"http://orders/orders":          "",
	} {
		resolution := expectations.Resolve(manifest, Request{
			Target: "component:orders", Inputs: map[string]any{"url": url},
		})
		got := ""
		if resolution.Fact != nil {
			got = resolution.Fact.Provenance.Artefact
		}
		if got != want {
			t.Errorf("%s resolved to %q, want %q (%s)", url, got, want, resolution.Missing)
		}
	}
}

// TestConfiguredExpectationsComeOnlyFromTheNamedEnvironment: a manifest
// measured against CONFIGURED takes its expectation from a capture of the
// environment the reading is about, never from another environment's.
func TestConfiguredExpectationsComeOnlyFromTheNamedEnvironment(t *testing.T) {
	fact := model.Fact{
		Plane:       model.PlaneConfigured,
		Subject:     "connection:orders->orders-db",
		Predicate:   "database_connects",
		Value:       true,
		Environment: "staging",
		Provenance:  model.Provenance{SourceKind: model.SourceObservation, Artefact: "capture", ConfidenceRank: 80},
	}
	expectations := NewExpectations([]model.Fact{fact})
	manifest := dbConnect{}.Manifest()

	for environment, found := range map[string]bool{"staging": true, "production": false} {
		resolution := expectations.Resolve(manifest, Request{
			Target: "connection:orders->orders-db", Environment: environment,
		})
		if (resolution.Fact != nil) != found {
			t.Errorf("environment %s: resolved %v, want found=%v", environment, resolution.Fact, found)
		}
	}
}

// TestAReadingCitesOnlyADeclarationItWasMeasuredAgainst is the reverse of
// the test above, and the regression test for a defect the Phase 31.1
// invariant audit found: the runner stamped expected_source whenever a
// matching fact was *found*, so a reading taken with an explicit
// `--input expect_columns=id` cited the migration it had ignored, and a
// probe that never reads its expectation cited one anyway.
func TestAReadingCitesOnlyADeclarationItWasMeasuredAgainst(t *testing.T) {
	// An explicit expectation overrides the declaration, and then no
	// declaration is cited — nor is a conflict with one.
	schemaCase := expectationCases()[1]
	schemaCase.inputs = map[string]any{"expect_columns": []any{"id"}}
	disagreeing := schemaCase.fact
	disagreeing.Value = []any{"id", "total_cents", "currency"}
	disagreeing.Provenance.ConfidenceRank = 60
	reading := runWith(t, NewExpectations([]model.Fact{schemaCase.fact, disagreeing}), schemaCase)
	if reading.ExpectedSource != nil {
		t.Errorf("measured against --input expect_columns, but cites %+v", reading.ExpectedSource)
	}
	for _, item := range reading.Evidence {
		if item.Kind == EvidenceIntentConflict {
			t.Errorf("a conflict between declarations the reading did not use: %s", item.Value)
		}
	}

	versionCase := expectationCases()[3]
	versionCase.inputs = map[string]any{"package": "stripe", "expect_version": "7.1.0"}
	if reading := runWith(t, NewExpectations([]model.Fact{versionCase.fact}), versionCase); reading.ExpectedSource != nil {
		t.Errorf("measured against --input expect_version, but cites %+v", reading.ExpectedSource)
	}

	// A probe that compares only against its inputs cites nothing, even
	// with a fact on exactly the subject and predicate it produces.
	manifest := authTokenShape{}.Manifest()
	kind, parts, reason := MeasuredSubject(manifest.Produces[0].SubjectTemplate,
		Request{Target: authTarget})
	if reason != "" {
		t.Fatalf("subject: %s", reason)
	}
	fact := intentFact(model.MustBuildSubject(kind, parts), manifest.Produces[0].Predicate,
		"inventory-service", "culprit.yaml", 100)
	authCase := expectationCases()[0]
	authCase.probeID, authCase.target = manifest.ID, authTarget
	authCase.inputs = map[string]any{"token": goodToken, "expect_audience": "inventory-service"}
	authCase.deps = Deps{Now: fixedClock()}
	if reading := runWith(t, NewExpectations([]model.Fact{fact}), authCase); reading.ExpectedSource != nil {
		t.Errorf("%s never reads its expectation, but cites %+v", manifest.ID, reading.ExpectedSource)
	}
}
