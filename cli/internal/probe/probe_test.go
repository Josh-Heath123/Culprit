package probe

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/capability"
	"github.com/josh-heath123/culprit/cli/internal/capture"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The probe catalogue's fixture set.
//
// Field 13: "Each probe gets a fixture where it must return `pass`, one
// where it must return `fail`, and one where it must return
// `inconclusive`. The inconclusive case is mandatory — a probe that
// cannot admit uncertainty is a probe that guesses."
//
// That requirement is enforced structurally by
// TestEveryProbeHasAllThreeVerdictFixtures rather than by counting cases
// by hand: adding a fourteenth probe without its three fixtures fails the
// build. A checklist in a comment is not a gate.

type probeCase struct {
	name    string
	probeID string
	target  string
	inputs  map[string]any
	deps    Deps
	want    model.Verdict
	// expectation is the INTENT fact this reading is measured against.
	// Probes that would otherwise assert "this is declared" return
	// inconclusive without one, so the fail fixtures for those probes
	// must supply it — which is also the realistic case, since a route
	// nobody declared is not a route anybody is missing.
	expectation *model.Fact
}

// declared is an INTENT fact standing in for "something says this should
// exist", so a fail fixture tests the failure rather than the absence of
// an expectation.
func declared(subject, predicate string) *model.Fact {
	return &model.Fact{
		Plane: model.PlaneIntent, Subject: subject, Predicate: predicate,
		Provenance: model.Provenance{
			SourceKind: model.SourceAssertion, Extractor: "test-fixture",
			Artefact: "culprit.yaml", ConfidenceRank: 100,
		},
	}
}

// declaredAs is declared with a value, for the probes that compare
// against what the declaration says rather than only that it exists.
func declaredAs(subject, predicate string, value any) *model.Fact {
	fact := declared(subject, predicate)
	fact.Value = value
	return fact
}

// grantEverything is the ledger used for the verdict fixtures. What
// happens when a grant is *missing* is tested separately, in
// TestAnUngrantedProbeIsRefusedWithoutDialling.
func grantEverything(t *testing.T) *capability.Ledger {
	t.Helper()
	raw := map[string]capability.Raw{}
	for _, name := range []string{
		"net.dns.resolve", "net.tcp.connect", "net.tls.inspect",
		"net.http.outbound", "db.metadata.read", "config.read.names",
		"repo.read", "telemetry.metrics.read", "db.stats.read", "db.plan.read",
	} {
		enabled := true
		raw[name] = capability.Raw{Enabled: &enabled}
	}
	grants, err := capability.Parse(raw)
	if err != nil {
		t.Fatalf("building grants: %v", err)
	}
	return capability.NewLedger(grants)
}

const (
	connectionTarget = "connection:order-service->inventory-service"
	componentTarget  = "component:inventory-service"
	authTarget       = "auth:order-service->inventory-service/audience"
)

// A JWT whose payload decodes to aud=inventory-service, iss=auth.internal,
// exp far in the future. The signature segment is nonsense on purpose:
// nothing in this package verifies a signature, and a real one in a test
// fixture is a credential in the repository.
const goodToken = "eyJhbGciOiJIUzI1NiJ9." +
	"eyJhdWQiOiJpbnZlbnRvcnktc2VydmljZSIsImlzcyI6ImF1dGguaW50ZXJuYWwiLCJleHAiOjQxMDI0NDQ4MDB9." +
	"bm90LWEtcmVhbC1zaWduYXR1cmU"

// The same token with aud=wrong-service.
const wrongAudienceToken = "eyJhbGciOiJIUzI1NiJ9." +
	"eyJhdWQiOiJ3cm9uZy1zZXJ2aWNlIiwiaXNzIjoiYXV0aC5pbnRlcm5hbCIsImV4cCI6NDEwMjQ0NDgwMH0." +
	"bm90LWEtcmVhbC1zaWduYXR1cmU"

func cases() []probeCase {
	clock := fixedClock()

	return []probeCase{
		// --- probe.net.dns_resolve ---
		{"dns resolves", "probe.net.dns_resolve", componentTarget,
			map[string]any{"host": "inventory.internal"},
			Deps{Network: fakeNetwork{addresses: []string{"10.0.0.4"}}, Now: clock},
			model.VerdictPass, nil},
		{"dns does not resolve", "probe.net.dns_resolve", componentTarget,
			map[string]any{"host": "inventory.internal"},
			Deps{Network: fakeNetwork{addresses: nil}, Now: clock},
			model.VerdictFail, nil},
		{"dns has no host to look up", "probe.net.dns_resolve", componentTarget,
			map[string]any{},
			Deps{Network: fakeNetwork{}, Now: clock},
			model.VerdictInconclusive, nil},

		// --- probe.net.tcp_connect ---
		{"tcp connects", "probe.net.tcp_connect", connectionTarget,
			map[string]any{"host": "inventory.internal", "port": 8080},
			Deps{Network: fakeNetwork{}, Now: clock},
			model.VerdictPass, nil},
		{"tcp refused", "probe.net.tcp_connect", connectionTarget,
			map[string]any{"host": "inventory.internal", "port": 8080},
			Deps{Network: fakeNetwork{dialErr: errBoom}, Now: clock},
			model.VerdictFail, nil},
		{"tcp times out, which proves nothing", "probe.net.tcp_connect", connectionTarget,
			map[string]any{"host": "inventory.internal", "port": 8080},
			Deps{Network: fakeNetwork{dialErr: errTimeout}, Now: clock},
			model.VerdictInconclusive, nil},
		{"tcp has no endpoint", "probe.net.tcp_connect", connectionTarget,
			map[string]any{"host": "inventory.internal"},
			Deps{Network: fakeNetwork{}, Now: clock},
			model.VerdictInconclusive, nil},

		// --- probe.net.tls_validity ---
		{"tls valid", "probe.net.tls_validity", componentTarget,
			map[string]any{"host": "inventory.internal", "port": 443},
			Deps{Network: fakeNetwork{tlsStatus: TLSValid}, Now: clock},
			model.VerdictPass, nil},
		{"tls expired", "probe.net.tls_validity", componentTarget,
			map[string]any{"host": "inventory.internal", "port": 443},
			Deps{Network: fakeNetwork{tlsStatus: TLSExpired}, Now: clock},
			model.VerdictFail, nil},
		{"tls handshake never completed", "probe.net.tls_validity", componentTarget,
			map[string]any{"host": "inventory.internal", "port": 443},
			Deps{Network: fakeNetwork{tlsStatus: TLSHandshakeError, tlsErr: errBoom}, Now: clock},
			model.VerdictInconclusive, nil},

		// --- probe.http.reachable ---
		{"http healthy", "probe.http.reachable", componentTarget,
			map[string]any{"url": "http://inventory.internal/health"},
			Deps{HTTP: &fakeHTTP{response: HTTPResponse{Status: 200}}, Now: clock},
			model.VerdictPass, nil},
		{"http failing", "probe.http.reachable", componentTarget,
			map[string]any{"url": "http://inventory.internal/health"},
			Deps{HTTP: &fakeHTTP{response: HTTPResponse{Status: 503}}, Now: clock},
			model.VerdictFail, nil},
		{"http 404 may be the wrong path", "probe.http.reachable", componentTarget,
			map[string]any{"url": "http://inventory.internal/health"},
			Deps{HTTP: &fakeHTTP{response: HTTPResponse{Status: 404}}, Now: clock},
			model.VerdictInconclusive, nil},

		// --- probe.http.route_conformance ---
		{"declared route is served", "probe.http.route_conformance", componentTarget,
			map[string]any{"url": "http://inventory.internal/stock", "method": "GET"},
			Deps{HTTP: &fakeHTTP{response: HTTPResponse{Status: 200}}, Now: clock},
			model.VerdictPass,
			declared("http:inventory-service/GET /stock", "exists")},
		{"declared route answers 404", "probe.http.route_conformance", componentTarget,
			map[string]any{"url": "http://inventory.internal/stock", "method": "GET"},
			Deps{HTTP: &fakeHTTP{response: HTTPResponse{Status: 404}}, Now: clock},
			model.VerdictFail,
			declared("http:inventory-service/GET /stock", "exists")},
		{"a served route nobody declared conforms to nothing", "probe.http.route_conformance",
			componentTarget,
			map[string]any{"url": "http://inventory.internal/stock", "method": "GET"},
			Deps{HTTP: &fakeHTTP{response: HTTPResponse{Status: 200}}, Now: clock},
			model.VerdictInconclusive, nil},
		{"an undeclared route answering 404 is not a finding", "probe.http.route_conformance",
			componentTarget,
			map[string]any{"url": "http://inventory.internal/stock", "method": "GET"},
			Deps{HTTP: &fakeHTTP{response: HTTPResponse{Status: 404}}, Now: clock},
			model.VerdictInconclusive, nil},
		{"route unknowable behind a 500", "probe.http.route_conformance", componentTarget,
			map[string]any{"url": "http://inventory.internal/stock", "method": "GET"},
			Deps{HTTP: &fakeHTTP{response: HTTPResponse{Status: 500}}, Now: clock},
			model.VerdictInconclusive, nil},

		// --- probe.http.schema_conformance ---
		{"response has declared fields", "probe.http.schema_conformance", componentTarget,
			map[string]any{"url": "http://inventory.internal/stock",
				"expect_fields": []any{"sku", "quantity"}},
			Deps{HTTP: &fakeHTTP{response: HTTPResponse{
				Status: 200, BodyKind: "object", BodyKeys: []string{"quantity", "sku"}}}, Now: clock},
			model.VerdictPass, nil},
		{"response is missing a declared field", "probe.http.schema_conformance", componentTarget,
			map[string]any{"url": "http://inventory.internal/stock",
				"expect_fields": []any{"sku", "quantity"}},
			Deps{HTTP: &fakeHTTP{response: HTTPResponse{
				Status: 200, BodyKind: "object", BodyKeys: []string{"sku"}}}, Now: clock},
			model.VerdictFail, nil},
		{"nothing declared to conform to", "probe.http.schema_conformance", componentTarget,
			map[string]any{"url": "http://inventory.internal/stock"},
			Deps{HTTP: &fakeHTTP{response: HTTPResponse{Status: 200}}, Now: clock},
			model.VerdictInconclusive, nil},

		// --- probe.auth.token_shape ---
		{"token has the right audience", "probe.auth.token_shape", authTarget,
			map[string]any{"token": goodToken, "expect_audience": "inventory-service"},
			Deps{Now: clock},
			model.VerdictPass, nil},
		{"token has the wrong audience", "probe.auth.token_shape", authTarget,
			map[string]any{"token": wrongAudienceToken, "expect_audience": "inventory-service"},
			Deps{Now: clock},
			model.VerdictFail, nil},
		{"token is well-formed but nothing was expected", "probe.auth.token_shape", authTarget,
			map[string]any{"token": goodToken},
			Deps{Now: clock},
			model.VerdictInconclusive, nil},
		{"a token_env read without config.inspect.values", "probe.auth.token_shape", authTarget,
			map[string]any{"token_env": "ORDER_TOKEN"},
			Deps{Secrets: &fakeSecrets{}, Now: clock},
			model.VerdictRefused, nil},

		// --- probe.auth.propagation ---
		{"credential survives the hop", "probe.auth.propagation", authTarget,
			map[string]any{"url": "http://inventory.internal/stock", "token": goodToken},
			Deps{HTTP: &fakeHTTP{response: HTTPResponse{Status: 200}}, Now: clock},
			model.VerdictPass, nil},
		{"credential rejected downstream", "probe.auth.propagation", authTarget,
			map[string]any{"url": "http://inventory.internal/stock", "token": goodToken},
			Deps{HTTP: &fakeHTTP{response: HTTPResponse{Status: 401}}, Now: clock},
			model.VerdictFail, nil},
		{"propagation unknowable behind a 500", "probe.auth.propagation", authTarget,
			map[string]any{"url": "http://inventory.internal/stock", "token": goodToken},
			Deps{HTTP: &fakeHTTP{response: HTTPResponse{Status: 502}}, Now: clock},
			model.VerdictInconclusive, nil},

		// --- probe.db.connect ---
		{"database accepts a read-only connection", "probe.db.connect", connectionTarget,
			map[string]any{},
			Deps{Database: fakeDatabase{}, Now: clock},
			model.VerdictPass, nil},
		{"database refuses the connection", "probe.db.connect", connectionTarget,
			map[string]any{},
			Deps{Database: fakeDatabase{connectErr: errBoom}, Now: clock},
			model.VerdictFail, nil},
		{"no connection string to try", "probe.db.connect", connectionTarget,
			map[string]any{},
			Deps{Database: fakeDatabase{connectErr: &UnavailableError{
				Reason: "ORDERS_DSN is not set in the environment culprit is running in"}}, Now: clock},
			model.VerdictInconclusive, nil},

		// --- probe.db.schema_conformance ---
		{"live table has the mapped columns", "probe.db.schema_conformance", connectionTarget,
			map[string]any{"table": "orders",
				"expect_columns": []any{"id", "total_cents"}},
			Deps{Database: fakeDatabase{columns: []TableColumn{
				{Name: "id"}, {Name: "total_cents"}}}, Now: clock},
			model.VerdictPass, nil},
		{"live table is missing a mapped column", "probe.db.schema_conformance", connectionTarget,
			map[string]any{"table": "orders",
				"expect_columns": []any{"id", "total_cents"}},
			Deps{Database: fakeDatabase{columns: []TableColumn{{Name: "id"}}}, Now: clock},
			model.VerdictFail, nil},
		{"live columns could not be read", "probe.db.schema_conformance", connectionTarget,
			map[string]any{"table": "orders",
				"expect_columns": []any{"id"}},
			Deps{Database: fakeDatabase{columnsErr: errBoom}, Now: clock},
			model.VerdictInconclusive, nil},

		// --- probe.db.statement_budget (Phase 37 part 2) ---
		{"statements within their budget", "probe.db.statement_budget", componentTarget, nil,
			Deps{Statements: fakeStatements{window: capture.StatementWindow{Statements: []capture.StatementStats{
				{QueryID: 7, Calls: 5, TotalMicros: 200000, Text: "SELECT 1", TextKept: true}}}}, Now: clock},
			model.VerdictPass, declaredAs(componentTarget, "query_mean_ms_max", 50)},
		{"a statement over its budget", "probe.db.statement_budget", componentTarget, nil,
			Deps{Statements: fakeStatements{window: capture.StatementWindow{Statements: []capture.StatementStats{
				{QueryID: 7, Calls: 5, TotalMicros: 260000}}}}, Now: clock},
			model.VerdictFail, declaredAs(componentTarget, "query_mean_ms_max", 50)},
		{"statistics reset during the window", "probe.db.statement_budget", componentTarget, nil,
			Deps{Statements: fakeStatements{window: capture.StatementWindow{Reset: true, Statements: []capture.StatementStats{
				{QueryID: 7, Calls: 5, TotalMicros: 260000}}}}, Now: clock},
			model.VerdictInconclusive, declaredAs(componentTarget, "query_mean_ms_max", 50)},
		{"no pg_stat_statements", "probe.db.statement_budget", componentTarget, nil,
			Deps{Statements: fakeStatements{window: capture.StatementWindow{
				Unavailable: "pg_stat_statements is not installed in this database"}}, Now: clock},
			model.VerdictInconclusive, declaredAs(componentTarget, "query_mean_ms_max", 50)},

		// --- probe.db.plan (Phase 37 part 2): evidence, no fail ---
		{"a generic plan", "probe.db.plan", componentTarget, map[string]any{"queryid": "7"},
			Deps{Statements: fakeStatements{plan: capture.StatementPlan{PlanJSON: seqScanPlan,
				TableColumns: map[string][]string{"public.products": {"id", "category", "name"}}}}, Now: clock},
			model.VerdictPass, nil},
		{"a server before PostgreSQL 16", "probe.db.plan", componentTarget, map[string]any{"queryid": "7"},
			Deps{Statements: fakeStatements{plan: capture.StatementPlan{
				Unavailable: "PostgreSQL 15 is before 16"}}, Now: clock},
			model.VerdictInconclusive, nil},

		// --- probe.config.present ---
		{"required key is set", "probe.config.present", componentTarget,
			map[string]any{"key": "JWT_SECRET_KEY"},
			Deps{Config: fakeConfig{present: true}, Now: clock},
			model.VerdictPass,
			declaredAs("config:inventory-service/JWT_SECRET_KEY", "required", true)},
		{"required key is missing", "probe.config.present", componentTarget,
			map[string]any{"key": "JWT_SECRET_KEY"},
			Deps{Config: fakeConfig{present: false}, Now: clock},
			model.VerdictFail,
			declaredAs("config:inventory-service/JWT_SECRET_KEY", "required", true)},
		{"an unset key with a default is the default in use", "probe.config.present",
			componentTarget,
			map[string]any{"key": "LOG_LEVEL"},
			Deps{Config: fakeConfig{present: false}, Now: clock},
			model.VerdictPass,
			declaredAs("config:inventory-service/LOG_LEVEL", "required", false)},
		{"an unset key nobody declared is not a finding", "probe.config.present",
			componentTarget,
			map[string]any{"key": "SOME_OPTIONAL_FLAG"},
			Deps{Config: fakeConfig{present: false}, Now: clock},
			model.VerdictInconclusive, nil},
		{"no key was named", "probe.config.present", componentTarget,
			map[string]any{},
			Deps{Config: fakeConfig{}, Now: clock},
			model.VerdictInconclusive, nil},

		// --- probe.dep.version ---
		{"installed version matches", "probe.dep.version", componentTarget,
			map[string]any{"package": "stripe", "expect_version": "7.1.0"},
			Deps{Packages: fakePackages{version: "7.1.0", found: true}, Now: clock},
			model.VerdictPass, nil},
		{"installed version differs", "probe.dep.version", componentTarget,
			map[string]any{"package": "stripe", "expect_version": "7.1.0"},
			Deps{Packages: fakePackages{version: "6.0.0", found: true}, Now: clock},
			model.VerdictFail, nil},
		{"no expected version declared", "probe.dep.version", componentTarget,
			map[string]any{"package": "stripe"},
			Deps{Packages: fakePackages{version: "7.1.0", found: true}, Now: clock},
			model.VerdictInconclusive, nil},
		{"declared exact pin differs from what is installed", "probe.dep.version",
			componentTarget,
			map[string]any{"package": "stripe"},
			Deps{Packages: fakePackages{version: "6.0.0", found: true}, Now: clock},
			model.VerdictFail,
			declaredAs("dep:inventory-service/stripe", "version", "==7.1.0")},
		{"a declared range is reported, not judged", "probe.dep.version", componentTarget,
			map[string]any{"package": "stripe"},
			Deps{Packages: fakePackages{version: "7.1.0", found: true}, Now: clock},
			model.VerdictInconclusive,
			declaredAs("dep:inventory-service/stripe", "version", ">=7.0")},

		// --- probe.edge.impedance ---
		{"connection behaving normally", "probe.edge.impedance", connectionTarget,
			map[string]any{},
			Deps{Metrics: fakeMetrics{found: true, sample: ImpedanceSample{
				Deviation: 0.4, Metric: "latency_ms", Samples: 500}}, Now: clock},
			model.VerdictPass, nil},
		{"connection far from its own history", "probe.edge.impedance", connectionTarget,
			map[string]any{},
			Deps{Metrics: fakeMetrics{found: true, sample: ImpedanceSample{
				Deviation: 7.8, Metric: "latency_ms", Samples: 500}}, Now: clock},
			model.VerdictFail, nil},
		// --- probe.http.latency (Phase 36) ---
		{"twenty fast answers against a 300 ms p50", "probe.http.latency", componentTarget,
			map[string]any{"url": "http://inventory.internal/ready"},
			Deps{HTTP: &fakeTimer{timings: []Timing{{Status: 200, Total: 5 * time.Millisecond}}}, Now: clock},
			model.VerdictPass,
			declaredAs("http:inventory-service/GET /ready", "latency_p50_ms", 300)},
		{"twenty slow answers against a 300 ms p50", "probe.http.latency", componentTarget,
			map[string]any{"url": "http://inventory.internal/ready"},
			Deps{HTTP: &fakeTimer{timings: []Timing{{Status: 200, Total: 900 * time.Millisecond}}}, Now: clock},
			model.VerdictFail,
			declaredAs("http:inventory-service/GET /ready", "latency_p50_ms", 300)},
		{"every request refused with 401", "probe.http.latency", componentTarget,
			map[string]any{"url": "http://inventory.internal/ready"},
			Deps{HTTP: &fakeTimer{timings: []Timing{{Status: 401, Total: time.Millisecond}}}, Now: clock},
			model.VerdictInconclusive,
			declaredAs("http:inventory-service/GET /ready", "latency_p50_ms", 300)},
		{"no budget declared, nothing sent", "probe.http.latency", componentTarget,
			map[string]any{"url": "http://inventory.internal/ready"},
			Deps{HTTP: &fakeTimer{timings: []Timing{{Status: 200}}}, Now: clock},
			model.VerdictInconclusive, nil},
		{"too little history to say", "probe.edge.impedance", connectionTarget,
			map[string]any{},
			Deps{Metrics: fakeMetrics{found: true, sample: ImpedanceSample{
				Deviation: 7.8, Metric: "latency_ms", Samples: 4}}, Now: clock},
			model.VerdictInconclusive, nil},
	}
}

func TestProbeVerdicts(t *testing.T) {
	for _, testCase := range cases() {
		t.Run(testCase.name, func(t *testing.T) {
			runner := NewRunner(Options{
				Ledger: grantEverything(t),
				Deps:   testCase.deps,
			})
			readings := runner.Run(context.Background(), []Request{{
				ProbeID:     testCase.probeID,
				Target:      testCase.target,
				Environment: "staging",
				Inputs:      testCase.inputs,
				Expectation: testCase.expectation,
			}})
			if len(readings) != 1 {
				t.Fatalf("expected one reading, got %d", len(readings))
			}
			reading := readings[0]
			if reading.Verdict != testCase.want {
				t.Errorf("verdict = %q, want %q (reason: %s)",
					reading.Verdict, testCase.want, reading.Reason)
			}
			if err := reading.Validate(); err != nil {
				t.Errorf("reading does not validate: %v", err)
			}
		})
	}
}

// refusedCases is a refused fixture for every probe whose manifest needs a
// capability: the runner refuses it, before running it, when the ledger
// grants nothing. Generated from the manifests rather than written per
// probe, because the refusal is the runner's, the same for every probe; a
// probe that declares refused without a capability (token_shape, refused
// by its secret source) has its own fixture in cases().
func refusedCases() []probeCase {
	var refused []probeCase
	for _, manifest := range BuiltIn().Manifests() {
		if len(manifest.Capabilities) == 0 {
			continue
		}
		refused = append(refused, probeCase{
			name: manifest.ID + " with nothing granted", probeID: manifest.ID,
			target: "component:inventory-service", inputs: map[string]any{},
			deps: Deps{Now: fixedClock()}, want: model.VerdictRefused,
		})
	}
	return refused
}

func TestEveryProbeIsRefusedWithNothingGranted(t *testing.T) {
	grants, err := capability.Parse(map[string]capability.Raw{})
	if err != nil {
		t.Fatal(err)
	}
	for _, testCase := range refusedCases() {
		runner := NewRunner(Options{Ledger: capability.NewLedger(grants), Deps: testCase.deps})
		readings := runner.Run(context.Background(), []Request{{
			ProbeID: testCase.probeID, Target: testCase.target, Environment: "staging",
			Inputs: testCase.inputs,
		}})
		if len(readings) != 1 || readings[0].Verdict != model.VerdictRefused {
			t.Errorf("%s: %+v", testCase.name, readings)
		}
	}
}

// TestEveryDeclaredVerdictHasAFixture is field 13 as a gate rather than a
// checklist, keyed on what each probe declares (Q31, 2026-11-13): one
// fixture for each verdict a probe's manifest lists, and no fixture for a
// verdict it does not. No probe is named here. Every probe declares
// inconclusive (model.ProbeManifest.Validate), so the inconclusive fixture
// stays mandatory: a probe that cannot admit uncertainty is a probe that
// guesses.
func TestEveryDeclaredVerdictHasAFixture(t *testing.T) {
	covered := map[string]map[model.Verdict]bool{}
	for _, testCase := range append(cases(), refusedCases()...) {
		if covered[testCase.probeID] == nil {
			covered[testCase.probeID] = map[model.Verdict]bool{}
		}
		covered[testCase.probeID][testCase.want] = true
	}
	for _, manifest := range BuiltIn().Manifests() {
		for _, verdict := range manifest.Verdicts {
			if !covered[manifest.ID][verdict] {
				t.Errorf("probe %s declares %s but has no %s fixture", manifest.ID, verdict, verdict)
			}
		}
		for verdict := range covered[manifest.ID] {
			if !manifest.Declares(verdict) {
				t.Errorf("a fixture expects %s from probe %s, which does not declare it", verdict, manifest.ID)
			}
		}
	}
}

// failingEvidence is a probe that declares no fail and returns one anyway.
type failingEvidence struct{}

func (failingEvidence) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID: "probe.test.failing_evidence", Version: 1, Verdicts: evidenceVerdicts,
		Effect: model.EffectObserve, Capabilities: []string{}, TimeoutMS: 1000,
	}
}

func (failingEvidence) Run(context.Context, Request, Deps) Outcome {
	return fail(map[string]any{}, "a fail this probe did not declare")
}

// TestAnUndeclaredVerdictNeverLeavesTheRunner: a probe that returns a
// verdict its manifest does not list produces an inconclusive reading
// naming the bug, never the verdict.
func TestAnUndeclaredVerdictNeverLeavesTheRunner(t *testing.T) {
	catalogue := NewCatalogue()
	if err := catalogue.register(failingEvidence{}); err != nil {
		t.Fatal(err)
	}
	runner := NewRunner(Options{Catalogue: catalogue, Ledger: grantEverything(t), Deps: Deps{Now: fixedClock()}})
	readings := runner.Run(context.Background(), []Request{{
		ProbeID: "probe.test.failing_evidence", Target: "component:inventory-service", Environment: "staging",
	}})
	if len(readings) != 1 || readings[0].Verdict != model.VerdictInconclusive ||
		!strings.Contains(readings[0].Reason, "declares only") {
		t.Fatalf("%+v", readings)
	}
}

func TestBuiltInCatalogueRegistersEveryCoreProbe(t *testing.T) {
	catalogue := BuiltIn()
	want := []string{
		"probe.auth.propagation", "probe.auth.token_shape", "probe.config.present",
		"probe.db.connect", "probe.db.plan", "probe.db.schema_conformance",
		"probe.db.statement_budget", "probe.dep.version",
		"probe.edge.impedance", "probe.http.latency", "probe.http.reachable",
		"probe.http.route_conformance", "probe.http.schema_conformance",
		"probe.net.dns_resolve", "probe.net.tcp_connect", "probe.net.tls_validity",
	}
	got := catalogue.IDs()
	if len(got) != len(want) {
		t.Fatalf("catalogue has %d probes, expected %d: %v", len(got), len(want), got)
	}
	for index, id := range want {
		if got[index] != id {
			t.Errorf("catalogue[%d] = %q, want %q", index, got[index], id)
		}
	}
}

// TestNoProbeInTheCatalogueMutates is §2.6 checked against what actually
// shipped, not against the validator in isolation.
func TestNoProbeInTheCatalogueMutates(t *testing.T) {
	for _, manifest := range BuiltIn().Manifests() {
		if manifest.Effect == model.EffectMutate {
			t.Errorf("probe %s declares effect: mutate", manifest.ID)
		}
		for _, name := range manifest.Capabilities {
			if strings.HasSuffix(name, ".write") {
				t.Errorf("probe %s names a write capability %q", manifest.ID, name)
			}
			if !capability.Known(name) {
				t.Errorf("probe %s names unknown capability %q", manifest.ID, name)
			}
		}
	}
}

// TestAnUngrantedProbeIsRefusedWithoutDialling is the permission model's
// central claim: what is not granted is a recorded refusal, never an
// omission and never a silent success.
func TestAnUngrantedProbeIsRefusedWithoutDialling(t *testing.T) {
	grants, err := capability.Parse(map[string]capability.Raw{})
	if err != nil {
		t.Fatalf("building empty grants: %v", err)
	}
	ledger := capability.NewLedger(grants)

	// A network that fails loudly if it is ever touched. The point is not
	// that the verdict is `refused` but that nothing was dialled to reach
	// it.
	network := fakeNetwork{dialErr: errBoom}
	runner := NewRunner(Options{
		Ledger: ledger,
		Deps:   Deps{Network: network, Now: fixedClock()},
	})

	readings := runner.Run(context.Background(), []Request{{
		ProbeID:     "probe.net.tcp_connect",
		Target:      connectionTarget,
		Environment: "prod",
		Inputs:      map[string]any{"host": "inventory.internal", "port": 8080},
	}})

	reading := readings[0]
	if reading.Verdict != model.VerdictRefused {
		t.Fatalf("verdict = %q, want refused", reading.Verdict)
	}
	if !strings.Contains(reading.Reason, "net.tcp.connect") {
		t.Errorf("a refusal must name the missing capability, got %q", reading.Reason)
	}
	if len(reading.GrantsUsed) != 0 {
		t.Errorf("a refused reading used no grants, got %v", reading.GrantsUsed)
	}
	if len(ledger.Refusals()) == 0 {
		t.Error("the refusal was not recorded on the ledger, so it would not " +
			"appear in a report — an omission, which is the failure mode the " +
			"capability model exists to prevent")
	}
}

// TestAuthProbesNeverEmitTokenMaterial is field 12's required test.
//
// It runs both auth probes against a fixture token and greps the entire
// serialised reading for the token, for each of its segments, and for the
// signature alone. The token is genuinely sent on the wire (asserted via
// the fake's recorded headers), so this is not passing by never using it.
func TestAuthProbesNeverEmitTokenMaterial(t *testing.T) {
	segments := strings.Split(goodToken, ".")
	http := &fakeHTTP{response: HTTPResponse{Status: 200}}

	runner := NewRunner(Options{
		Ledger: grantEverything(t),
		Deps:   Deps{HTTP: http, Now: fixedClock()},
	})

	readings := runner.Run(context.Background(), []Request{
		{ProbeID: "probe.auth.token_shape", Target: authTarget, Environment: "staging",
			Inputs: map[string]any{"token": goodToken, "expect_audience": "inventory-service"}},
		{ProbeID: "probe.auth.propagation", Target: authTarget, Environment: "staging",
			Inputs: map[string]any{"url": "http://inventory.internal/stock", "token": goodToken}},
		// A malformed token is the case where the input is most likely to
		// be a real credential pasted by hand, so it is checked too.
		{ProbeID: "probe.auth.token_shape", Target: authTarget, Environment: "staging",
			Inputs: map[string]any{"token": "sk-live-not-a-jwt-but-definitely-a-secret"}},
	})

	if http.lastHeaders["Authorization"] != "Bearer "+goodToken {
		t.Fatal("the propagation probe did not send the token, so this test " +
			"would pass for the wrong reason")
	}

	serialised, err := json.Marshal(readings)
	if err != nil {
		t.Fatalf("serialising readings: %v", err)
	}
	output := string(serialised)

	forbidden := map[string]string{
		goodToken:   "the whole token",
		segments[2]: "the signature",
		segments[1]: "the payload segment",
		"sk-live-not-a-jwt-but-definitely-a-secret": "a malformed token",
	}
	for needle, what := range forbidden {
		if strings.Contains(output, needle) {
			t.Errorf("%s appears in the readings output; auth probes inspect "+
				"token structure and never log token material (field 12)", what)
		}
	}
}

// TestReadingsAreOrderedDeterministically guards a property people rely
// on without being told: `culprit` output is diffed.
func TestReadingsAreOrderedDeterministically(t *testing.T) {
	requests := []Request{
		{ProbeID: "probe.net.tcp_connect", Target: connectionTarget, Environment: "s",
			Inputs: map[string]any{"host": "h", "port": 1}},
		{ProbeID: "probe.config.present", Target: componentTarget, Environment: "s",
			Inputs: map[string]any{"key": "A"}},
		{ProbeID: "probe.net.dns_resolve", Target: componentTarget, Environment: "s",
			Inputs: map[string]any{"host": "h"}},
	}
	deps := Deps{
		Network: fakeNetwork{addresses: []string{"10.0.0.1"}},
		Config:  fakeConfig{present: true},
		Now:     fixedClock(),
	}

	var first []string
	for run := 0; run < 5; run++ {
		runner := NewRunner(Options{Ledger: grantEverything(t), Deps: deps})
		readings := runner.Run(context.Background(), requests)
		var order []string
		for _, reading := range readings {
			order = append(order, reading.ProbeID+" "+reading.Target)
		}
		if run == 0 {
			first = order
			continue
		}
		if strings.Join(order, "|") != strings.Join(first, "|") {
			t.Fatalf("run %d ordered readings differently:\n %v\n %v", run, first, order)
		}
	}
}

func TestAnUnknownProbeIsInconclusiveNotASilentSuccess(t *testing.T) {
	runner := NewRunner(Options{Ledger: grantEverything(t), Deps: Deps{Now: fixedClock()}})
	readings := runner.Run(context.Background(), []Request{{
		ProbeID: "probe.net.does_not_exist", Target: componentTarget, Environment: "s",
	}})
	if readings[0].Verdict != model.VerdictInconclusive {
		t.Errorf("verdict = %q, want inconclusive", readings[0].Verdict)
	}
}

func TestADisabledProbeSaysSoRatherThanVanishing(t *testing.T) {
	disabled := false
	runner := NewRunner(Options{
		Ledger:    grantEverything(t),
		Deps:      Deps{Network: fakeNetwork{addresses: []string{"10.0.0.1"}}, Now: fixedClock()},
		Overrides: map[string]Override{"probe.net.dns_resolve": {Enabled: &disabled}},
	})
	readings := runner.Run(context.Background(), []Request{{
		ProbeID: "probe.net.dns_resolve", Target: componentTarget, Environment: "s",
		Inputs: map[string]any{"host": "h"},
	}})
	if readings[0].Verdict != model.VerdictInconclusive {
		t.Fatalf("verdict = %q, want inconclusive", readings[0].Verdict)
	}
	if !strings.Contains(readings[0].Reason, "disabled") {
		t.Errorf("reason should say it was disabled, got %q", readings[0].Reason)
	}
}

// TestAProbeMayNotWriteItsOwnGrantsUsed guards the audit trail: the
// runner stamps grants_used, not the probe.
func TestAProbeMayNotWriteItsOwnGrantsUsed(t *testing.T) {
	runner := NewRunner(Options{
		Ledger: grantEverything(t),
		Deps:   Deps{Network: fakeNetwork{addresses: []string{"10.0.0.1"}}, Now: fixedClock()},
	})
	readings := runner.Run(context.Background(), []Request{{
		ProbeID: "probe.net.dns_resolve", Target: componentTarget, Environment: "s",
		Inputs: map[string]any{"host": "h"},
	}})
	if len(readings[0].GrantsUsed) != 1 || readings[0].GrantsUsed[0] != "net.dns.resolve" {
		t.Errorf("grants_used = %v, want exactly the manifest's declared capability",
			readings[0].GrantsUsed)
	}
}

// TestNoReadingCarriesACredentialInAnyField is the regression test for a
// real defect found by the Phase 31 invariant audit.
//
// Redaction was first applied in the text renderer only, so
// `culprit probe --format json` printed a password in `measured.url` and
// in `reason`. The earlier JSON test missed it because its probe was
// *refused*, so the credential never reached a measurement — which is
// exactly the kind of test that looks like coverage and is not.
//
// This runs probes that genuinely succeed and fail with credential-
// bearing inputs, and greps the serialised readings, which is the
// artefact a CI job uploads and a developer attaches to a bug report.
func TestNoReadingCarriesACredentialInAnyField(t *testing.T) {
	const password = "hunter2"
	const dsn = "postgresql://admin:" + password + "@db.internal:5432/orders"
	const url = "https://admin:" + password + "@orders.internal/health"

	runner := NewRunner(Options{
		Ledger: grantEverything(t),
		Deps: Deps{
			HTTP:     &fakeHTTP{response: HTTPResponse{Status: 503}},
			Database: fakeDatabase{connectErr: errBoom},
			Now:      fixedClock(),
		},
	})

	readings := runner.Run(context.Background(), []Request{
		// Fails, so the URL lands in both `measured` and `reason`.
		{ProbeID: "probe.http.reachable", Target: componentTarget, Environment: "prod",
			Inputs: map[string]any{"url": url}},
		// Passes through a different code path.
		{ProbeID: "probe.http.route_conformance", Target: componentTarget, Environment: "prod",
			Inputs: map[string]any{"url": url, "method": "GET"}},
		// A DSN, which must never appear even though this probe does not
		// deliberately copy it into a measurement.
		{ProbeID: "probe.db.connect", Target: connectionTarget, Environment: "prod",
			Inputs: map[string]any{"dsn": dsn}},
	})

	serialised, err := json.Marshal(readings)
	if err != nil {
		t.Fatalf("serialising readings: %v", err)
	}
	if strings.Contains(string(serialised), password) {
		t.Errorf("a reading carries a password:\n%s", serialised)
	}
	if strings.Contains(string(serialised), dsn) {
		t.Errorf("a reading carries a connection string:\n%s", serialised)
	}

	// The redaction must not have swallowed the reading itself — a report
	// that says nothing is not an improvement on one that says too much.
	if len(readings) != 3 {
		t.Fatalf("expected three readings, got %d", len(readings))
	}
	for _, reading := range readings {
		if reading.Verdict == "" {
			t.Error("a reading lost its verdict to redaction")
		}
	}
}
