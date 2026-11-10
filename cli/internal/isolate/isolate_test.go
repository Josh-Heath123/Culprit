package isolate

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/report"
)

// ---- a synthetic world --------------------------------------------------------

// world decides what each probe would see. It is the fault, written down.
type world func(probeID, target string) model.Verdict

// countingRunner runs probes against a world and counts every execution —
// what the O(log n) criterion asserts on.
type countingRunner struct {
	world world
	count map[string]int // probe id -> executions
	total int
}

func newRunner(w world) *countingRunner {
	return &countingRunner{world: w, count: map[string]int{}}
}

var clock = time.Date(2026, 11, 4, 12, 0, 0, 0, time.UTC)

func (r *countingRunner) Run(_ context.Context, request Request) model.Reading {
	r.count[request.ProbeID]++
	r.total++
	verdict := r.world(request.ProbeID, request.Target)
	reading := model.Reading{
		ProbeID: request.ProbeID, ProbeVersion: 1, Target: request.Target,
		Environment: "simulated", Verdict: verdict, TakenAt: clock, AgentID: "simulated-runner",
	}
	if verdict.NeedsReason() {
		reading.Reason = "the simulated world gives no reason"
	}
	return reading
}

// openPlacement can place every probe, everywhere.
type openPlacement struct {
	refuse  map[string]string // hypothesis kind -> reason it cannot be placed
	vantage string
}

func (p openPlacement) Vantage() string { return p.vantage }

func (p openPlacement) Applicable(h model.Hypothesis) bool {
	return h.Kind != KindTLSInvalid // plain-text endpoints in these worlds
}

func (p openPlacement) Inputs(_ model.ProbeManifest, h model.Hypothesis) (map[string]any, string) {
	if reason, refused := p.refuse[h.Kind]; refused {
		return nil, reason
	}
	return map[string]any{}, ""
}

func manifests() []model.ProbeManifest {
	return []model.ProbeManifest{
		{ID: "probe.http.reachable", Version: 1, Discriminates: []string{KindComponentFails}, Cost: model.CostCheap},
		{ID: "probe.net.tcp_connect", Version: 1, Discriminates: []string{KindConnectionUnreachable}, Cost: model.CostCheap},
		{ID: "probe.auth.token_shape", Version: 1, Discriminates: []string{KindAuthAudience}, Cost: model.CostCheap},
		{ID: "probe.auth.propagation", Version: 1, Discriminates: []string{KindAuthRejected}, Cost: model.CostCheap},
		{ID: "probe.http.route_conformance", Version: 1, Discriminates: []string{KindContractMismatch}, Cost: model.CostCheap},
		{ID: "probe.config.present", Version: 1, Discriminates: []string{KindConfigMissing}, Cost: model.CostCheap},
		{ID: "probe.db.connect", Version: 1, Discriminates: []string{KindDatabaseUnreachable}, Cost: model.CostCheap},
	}
}

func component(name string) string {
	return model.MustBuildSubject(model.KindComponent, model.Parts{"name": name})
}

// chain builds c0 -> c1 -> ... -> c(n-1), every edge on the request path.
func chain(n int) ([]Component, []Connection, []string) {
	var components []Component
	var connections []Connection
	var names []string
	for index := 0; index < n; index++ {
		name := fmt.Sprintf("c%d", index)
		names = append(names, name)
		components = append(components, Component{Name: name, Kind: "service"})
		if index > 0 {
			connections = append(connections, Connection{From: names[index-1], To: name, Kind: "http", OnRequestPath: true})
		}
	}
	return components, connections, names
}

// componentFault: a request at any component at or above the faulty one
// fails; below it, requests succeed. Every other probe passes.
func componentFault(names []string, faulty int) world {
	position := map[string]int{}
	for index, name := range names {
		position[component(name)] = index
	}
	return func(probeID, target string) model.Verdict {
		if probeID == "probe.http.reachable" {
			if position[target] <= faulty {
				return model.VerdictFail
			}
		}
		return model.VerdictPass
	}
}

func diagnose(t *testing.T, w *Walk, entry string) model.Investigation {
	t.Helper()
	symptom := model.Symptom{Kind: model.SymptomComponent, Subject: component(entry), Source: "simulated"}
	inv, err := w.Diagnose(context.Background(), symptom, entry)
	if err != nil {
		t.Fatal(err)
	}
	inv.ID, inv.OpenedAt = "inv-test", clock
	if err := inv.Validate(); err != nil {
		t.Fatalf("the walk built an investigation the model rejects: %v", err)
	}
	assertReadable(t, inv)
	return inv
}

// assertReadable: every sentence the walk writes for a person — the
// statement, the suggested fix, each hypothesis's reason and each rubric
// reason — names no plan phase and no raw hypothesis kind. Every walk in
// this file passes through it.
func assertReadable(t *testing.T, inv model.Investigation) {
	t.Helper()
	for where, text := range userFacingText(inv) {
		if phaseNumber.MatchString(text) {
			t.Errorf("%s names a plan phase: %q", where, text)
		}
		for _, kind := range model.HypothesisKinds {
			if strings.Contains(text, kind) {
				t.Errorf("%s contains the raw kind %s: %q", where, kind, text)
			}
		}
		// Q17, ruled at 32.2's review: an arrow pair is notation, not a
		// name; a sentence says "from A to B".
		if strings.Contains(text, "->") {
			t.Errorf("%s contains an arrow pair: %q", where, text)
		}
	}
}

var phaseNumber = regexp.MustCompile(`(?i)\bphase \d`)

func userFacingText(inv model.Investigation) map[string]string {
	texts := map[string]string{}
	for _, h := range inv.Hypotheses {
		texts["hypothesis "+h.ID+" reason"] = h.Reason
	}
	if d := inv.Diagnosis; d != nil {
		texts["statement"] = d.Statement
		texts["remediation"] = d.Remediation
		texts["reproduced reason"] = d.Confidence.Reproduced.Reason
		texts["discriminated reason"] = d.Confidence.Discriminated.Reason
		texts["counterfactual reason"] = d.Confidence.Counterfactual.Reason
		texts["verified reason"] = d.Confidence.Verified.Reason
	}
	return texts
}

// TestEveryKindHasALabel: the walk's words for a kind come from the shared
// label map; a kind with no label there fails here as well as in
// internal/model and the frontend.
func TestEveryKindHasALabel(t *testing.T) {
	for _, kind := range model.HypothesisKinds {
		if model.HypothesisLabels[kind] == "" {
			t.Errorf("kind %s has no label", kind)
		}
		if phrase := kindPhrase(kind); strings.Contains(phrase, "_") || phrase == "" {
			t.Errorf("kind %s reads as %q", kind, phrase)
		}
	}
	if got := kindPhrase(model.HypothesisTLSInvalid); got != "TLS certificate invalid" {
		t.Errorf("an acronym is lower-cased: %q", got)
	}
	if got := kindPhrase(""); got == "" {
		t.Error("an empty kind reads as nothing")
	}
	if got := kindPhrase(model.HypothesisAuthAudience); got != "auth audience mismatch" {
		t.Errorf("auth_audience_mismatch reads as %q", got)
	}
}

func TestSubjectsAreDescribedInWords(t *testing.T) {
	cases := map[string]string{
		"component:order-service":                        "order-service",
		"connection:order-service->inventory-service":    "the connection from order-service to inventory-service",
		"auth:order-service->inventory-service/audience": "the token audience order-service presents to inventory-service",
		"config:payments-service/PAYMENTS_PROVIDER_KEY":  "PAYMENTS_PROVIDER_KEY in payments-service's configuration",
		"http:inventory-service/GET /stock":              "GET /stock on inventory-service",
		"not a subject":                                  "not a subject",
	}
	for subject, want := range cases {
		if got := describe(subject); got != want {
			t.Errorf("describe(%q) = %q, want %q", subject, got, want)
		}
	}
}

// ---- criterion 3: O(log n), counted ------------------------------------------

// TestASixHopChainIsBisectedNotWalked is Phase 32's criterion: isolation on
// a six-hop chain uses O(log n) probes, not n — asserted by counting probe
// executions, for a fault at every position on the chain.
func TestASixHopChainIsBisectedNotWalked(t *testing.T) {
	components, connections, names := chain(7) // six hops
	bound := int(math.Ceil(math.Log2(float64(len(names)))))
	for faulty := 0; faulty < len(names); faulty++ {
		runner := newRunner(componentFault(names, faulty))
		walk := New(components, connections, nil, manifests(), runner, openPlacement{}, Options{Environment: "simulated"})
		inv := diagnose(t, walk, "c0")

		searched := runner.count["probe.http.reachable"]
		// One more http.reachable run is the reproduction of the root
		// reading for the rubric; the search itself is bounded by log2(n).
		if searched-1 > bound {
			t.Errorf("fault at c%d: %d request probes to search %d components, want <= %d",
				faulty, searched-1, len(names), bound)
		}
		if searched >= len(names) && faulty > 0 {
			t.Errorf("fault at c%d: %d request probes — that is walking the chain, not bisecting it", faulty, searched)
		}
		if got, want := inv.Diagnosis.RootSubject, component(names[faulty]); got != want {
			t.Errorf("fault at c%d: root %s, want %s", faulty, got, want)
		}
	}
}

// TestBisectionScalesLogarithmically runs the same walk on a 64-component
// chain: six request probes, not sixty-three.
func TestBisectionScalesLogarithmically(t *testing.T) {
	components, connections, names := chain(64)
	runner := newRunner(componentFault(names, 41))
	walk := New(components, connections, nil, manifests(), runner, openPlacement{}, Options{Environment: "simulated", MaxProbes: 200})
	inv := diagnose(t, walk, "c0")
	if searched := runner.count["probe.http.reachable"] - 1; searched > 6 {
		t.Errorf("%d request probes on a 64-component chain, want <= 6", searched)
	}
	// Every probe, not only request probes: the boundary hypotheses and the
	// rubric's reproduction are constants on top of log2(n), not a second n.
	if runner.total > 12 {
		t.Errorf("%d probe executions in all on a 64-component chain, want <= 12", runner.total)
	}
	if inv.Diagnosis.RootSubject != component("c41") {
		t.Errorf("root %s, want c41", inv.Diagnosis.RootSubject)
	}
}

// ---- criterion 2: symptom, propagation and root, every edge cited -------------

func TestTheTreeSeparatesSymptomPropagationAndRoot(t *testing.T) {
	components, connections, names := chain(5)
	// c2 answers when asked directly, but c1 cannot reach it: the fault is
	// on the edge c1 -> c2, and c1 and c0 fail because of it.
	edge := model.MustBuildSubject(model.KindConnection, model.Parts{"from_component": "c1", "to_component": "c2"})
	runner := newRunner(func(probeID, target string) model.Verdict {
		switch {
		case probeID == "probe.http.reachable" && (target == component("c0") || target == component("c1")):
			return model.VerdictFail
		case probeID == "probe.net.tcp_connect" && target == edge:
			return model.VerdictFail
		}
		return model.VerdictPass
	})
	walk := New(components, connections, nil, manifests(), runner, openPlacement{}, Options{Environment: "simulated"})
	symptom := model.Symptom{Kind: model.SymptomEndpoint, Subject: "http:c0/GET /checkout", Source: "simulated"}
	inv, err := walk.Diagnose(context.Background(), symptom, "c0")
	if err != nil {
		t.Fatal(err)
	}
	inv.ID, inv.OpenedAt = "inv-test", clock
	if err := inv.Validate(); err != nil {
		t.Fatal(err)
	}
	_ = names

	if inv.Diagnosis.RootSubject != edge || !inv.Diagnosis.Complete {
		t.Fatalf("diagnosis %+v, want a complete one rooted at %s", inv.Diagnosis, edge)
	}
	relations := map[model.Relation][]string{}
	for _, e := range inv.FaultTree {
		relations[e.Relation] = append(relations[e.Relation], e.FromSubject+" -> "+e.ToSubject)
		if len(e.EstablishedBy) == 0 {
			t.Errorf("edge %s -> %s cites no reading", e.FromSubject, e.ToSubject)
		}
	}
	want := map[model.Relation][]string{
		model.RelationSymptomOf:    {"http:c0/GET /checkout -> component:c0"},
		model.RelationPropagatesTo: {"component:c1 -> component:c0"},
		model.RelationCausedBy:     {"component:c1 -> " + edge},
	}
	for relation, edges := range want {
		if strings.Join(relations[relation], "; ") != strings.Join(edges, "; ") {
			t.Errorf("%s edges = %v, want %v", relation, relations[relation], edges)
		}
	}
}

// ---- criterion 1, in miniature: the audience, not the 500 ---------------------

// TestAnAudienceMismatchIsTheRootNotTheEdge is the demo's shape: order calls
// inventory and payments; both answer when asked directly; order's token for
// inventory carries the wrong audience. The root must be the audience, not
// order-service, and not the 500 the user saw at the edge.
func TestAnAudienceMismatchIsTheRootNotTheEdge(t *testing.T) {
	components := []Component{{"order-service", "service"}, {"inventory-service", "service"}, {"payments-service", "service"}}
	connections := []Connection{
		{From: "order-service", To: "inventory-service", Kind: "http", OnRequestPath: true},
		{From: "order-service", To: "payments-service", Kind: "http", OnRequestPath: true},
		// The demo declares edges back up the path too. A request entering
		// at order-service never travels them, and a walk that followed
		// them let a pass at inventory rule out the whole system.
		{From: "inventory-service", To: "order-service", Kind: "http", OnRequestPath: true},
		{From: "payments-service", To: "order-service", Kind: "http", OnRequestPath: true},
	}
	audience := model.MustBuildSubject(model.KindAuth, model.Parts{
		"from_component": "order-service", "to_component": "inventory-service", "aspect": "audience"})
	runner := newRunner(func(probeID, target string) model.Verdict {
		if probeID == "probe.auth.token_shape" && target == audience {
			return model.VerdictFail
		}
		return model.VerdictPass
	})
	walk := New(components, connections, nil, manifests(), runner, openPlacement{}, Options{Environment: "simulated"})
	symptom := model.Symptom{Kind: model.SymptomEndpoint, Subject: "http:order-service/POST /orders", Source: "simulated"}
	inv, err := walk.Diagnose(context.Background(), symptom, "order-service")
	if err != nil {
		t.Fatal(err)
	}
	inv.ID, inv.OpenedAt = "inv-test", clock
	if err := inv.Validate(); err != nil {
		t.Fatal(err)
	}
	if inv.Diagnosis.RootSubject != audience {
		t.Fatalf("root %s, want %s", inv.Diagnosis.RootSubject, audience)
	}
	if !inv.Diagnosis.Confidence.Reproduced.Holds || !inv.Diagnosis.Confidence.Discriminated.Holds {
		t.Errorf("rubric %+v: the failing probe was repeated and alternatives were ruled out", inv.Diagnosis.Confidence)
	}
	if inv.Diagnosis.Confidence.Verified.Holds {
		t.Error("a diagnosis claimed verified")
	}
}

// ---- partial diagnoses are visibly partial -------------------------------------

func TestARefusedProbeLeavesTheDiagnosisVisiblyPartial(t *testing.T) {
	components := []Component{{"order-service", "service"}, {"inventory-service", "service"}}
	connections := []Connection{{From: "order-service", To: "inventory-service", Kind: "http", OnRequestPath: true}}
	runner := newRunner(func(string, string) model.Verdict { return model.VerdictPass })
	placement := openPlacement{refuse: map[string]string{
		KindAuthAudience: "no token for the calls from order-service to inventory-service is available to this agent",
	}}
	walk := New(components, connections, nil, manifests(), runner, placement, Options{Environment: "simulated"})
	inv := diagnose(t, walk, "order-service")

	if inv.Diagnosis.Complete {
		t.Fatal("a diagnosis with an untested hypothesis claimed to be complete")
	}
	found := false
	for _, h := range inv.Hypotheses {
		if h.Kind == KindAuthAudience && h.Status == model.HypothesisUnexplored &&
			strings.Contains(h.Reason, "no token") {
			found = true
		}
	}
	if !found {
		t.Errorf("the unexplored audience hypothesis does not say why: %+v", inv.Hypotheses)
	}
	if !strings.Contains(inv.Diagnosis.Statement, "no token") {
		t.Errorf("the statement hides why it is partial: %q", inv.Diagnosis.Statement)
	}
}

// TestABoundaryWithUntestedAlternativesIsWhereTheWalkStopped: an edge
// failed a probe, but an alternative on the same edge could not be tested.
// The statement names where the walk stopped and what it could not check —
// never "because of" — and offers no fix (Phase 32.1 field 14).
func TestABoundaryWithUntestedAlternativesIsWhereTheWalkStopped(t *testing.T) {
	components := []Component{{"order-service", "service"}, {"inventory-service", "service"}}
	connections := []Connection{{From: "order-service", To: "inventory-service", Kind: "http", OnRequestPath: true}}
	runner := newRunner(func(probeID, target string) model.Verdict {
		switch {
		case probeID == "probe.http.reachable" && target == component("order-service"):
			return model.VerdictFail
		case probeID == "probe.net.tcp_connect":
			return model.VerdictFail
		}
		return model.VerdictPass
	})
	placement := openPlacement{refuse: map[string]string{
		KindAuthAudience: "no token for the calls from order-service to inventory-service is available to this agent",
	}}
	walk := New(components, connections, nil, manifests(), runner, placement, Options{Environment: "simulated"})
	inv := diagnose(t, walk, "order-service")

	d := inv.Diagnosis
	if d.Complete {
		t.Fatalf("complete with an unexplored alternative: %+v", d)
	}
	if !strings.HasPrefix(d.Statement, "The walk stopped at ") || !strings.Contains(d.Statement, "no token") {
		t.Errorf("statement = %q, want where the walk stopped and what it could not check", d.Statement)
	}
	if strings.Contains(strings.ToLower(d.Statement), "because") || strings.Contains(strings.ToLower(d.Statement), "cause") {
		t.Errorf("a partial statement names a cause: %q", d.Statement)
	}
	if d.Remediation != "" {
		t.Errorf("a partial diagnosis suggests a fix: %q", d.Remediation)
	}

	// The whole text output, the fault tree included, never says root or
	// cause for it.
	var out strings.Builder
	if err := report.RenderInvestigation(&out, inv); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "-[stopped_at]->") {
		t.Errorf("the boundary edge is not shown as where the walk stopped:\n%s", out.String())
	}
	if text := strings.ToLower(out.String()); strings.Contains(text, "root") || strings.Contains(text, "cause") {
		t.Errorf("a partial investigation's text says root or cause:\n%s", out.String())
	}

	// CULPRIT_ISOLATE_RECORD=<dir> keeps this walk for the API round trip
	// and the browser suite: the one partial investigation with a fault
	// tree, which no fault-library case produces.
	if dir := os.Getenv("CULPRIT_ISOLATE_RECORD"); dir != "" {
		inv.ID = "inv-5ea1b0a7d0e5c0de"
		encoded, _ := json.MarshalIndent(inv, "", "  ")
		if err := os.WriteFile(filepath.Join(dir, "partial-with-boundary.json"), append(encoded, '\n'), 0o644); err != nil {
			t.Fatal(err)
		}
	}
}

func TestTheProbeBudgetIsABudget(t *testing.T) {
	components, connections, names := chain(7)
	runner := newRunner(componentFault(names, 5))
	walk := New(components, connections, nil, manifests(), runner, openPlacement{}, Options{Environment: "simulated", MaxProbes: 2})
	inv := diagnose(t, walk, "c0")
	if runner.total > 2 {
		t.Errorf("ran %d probes on a budget of 2", runner.total)
	}
	if inv.Diagnosis.Complete {
		t.Error("a walk that ran out of budget claimed a complete diagnosis")
	}
	budget := false
	for _, h := range inv.Hypotheses {
		if h.Status == model.HypothesisUnexplored && strings.Contains(h.Reason, "budget") {
			budget = true
		}
	}
	if !budget {
		t.Error("no hypothesis says the budget ran out")
	}
}

// ---- determinism ------------------------------------------------------------------

// TestTheWalkIsDeterministic: the same model, world and budget give the
// same investigation, byte for byte. Nothing in it is chosen by chance or
// by a model's judgement (D8).
func TestTheWalkIsDeterministic(t *testing.T) {
	components, connections, names := chain(7)
	var outputs []string
	for run := 0; run < 3; run++ {
		walk := New(components, connections, nil, manifests(), newRunner(componentFault(names, 4)),
			openPlacement{}, Options{Environment: "simulated", Now: func() time.Time { return clock }})
		inv := diagnose(t, walk, "c0")
		encoded, err := json.Marshal(inv)
		if err != nil {
			t.Fatal(err)
		}
		outputs = append(outputs, string(encoded))
	}
	if outputs[0] != outputs[1] || outputs[1] != outputs[2] {
		t.Error("three identical walks produced different investigations")
	}
}

// TestAPartitionSeenFromInsideTheCallerBlamesTheEdge is Phase 31.1's
// partition, walked: from inside order-service, inventory-service does not
// answer — but it answers everyone else. The request crossed the edge, so
// the edge is tested before inventory is blamed.
func TestAPartitionSeenFromInsideTheCallerBlamesTheEdge(t *testing.T) {
	components := []Component{{"order-service", "service"}, {"inventory-service", "service"}}
	connections := []Connection{{From: "order-service", To: "inventory-service", Kind: "http", OnRequestPath: true}}
	edge := model.MustBuildSubject(model.KindConnection, model.Parts{
		"from_component": "order-service", "to_component": "inventory-service"})
	runner := newRunner(func(probeID, target string) model.Verdict {
		switch {
		case probeID == "probe.http.reachable" && target == component("inventory-service"):
			return model.VerdictFail // as seen from inside order-service
		case probeID == "probe.net.tcp_connect" && target == edge:
			return model.VerdictFail
		}
		return model.VerdictPass
	})
	walk := New(components, connections, nil, manifests(), runner,
		openPlacement{vantage: "order-service"}, Options{Environment: "simulated"})
	inv := diagnose(t, walk, "order-service")
	if inv.Diagnosis.RootSubject != edge || !inv.Diagnosis.Complete {
		t.Fatalf("diagnosis %+v, want a complete one rooted at %s", inv.Diagnosis, edge)
	}

	// The same failure seen from outside every component did not cross the
	// edge: there, inventory-service is what failed.
	walk = New(components, connections, nil, manifests(), runner, openPlacement{}, Options{Environment: "simulated"})
	inv = diagnose(t, walk, "order-service")
	if inv.Diagnosis.RootSubject != component("inventory-service") {
		t.Errorf("from outside, root %s, want inventory-service", inv.Diagnosis.RootSubject)
	}
}

// TestNothingFailingIsNotADiagnosis: added latency fails no read-only
// probe. Every probe passes, and the walk must not present "it is the
// entry, by elimination" as a complete diagnosis.
func TestNothingFailingIsNotADiagnosis(t *testing.T) {
	components, connections, _ := chain(3)
	runner := newRunner(func(string, string) model.Verdict { return model.VerdictPass })
	walk := New(components, connections, nil, manifests(), runner, openPlacement{}, Options{Environment: "simulated"})
	inv := diagnose(t, walk, "c0")
	if inv.Diagnosis.Complete {
		t.Fatalf("a walk in which nothing failed claimed a complete diagnosis: %+v", inv.Diagnosis)
	}
	if !strings.Contains(inv.Diagnosis.Statement, "latency") {
		t.Errorf("the statement does not say what it might be missing: %q", inv.Diagnosis.Statement)
	}
}

// TestEveryReadingKeepsTheRequestBehindIt: `culprit verify` re-runs an
// investigation's readings exactly (Phase 34), so the walk keeps the
// request behind each one — the reproduction and the counterfactual
// included, the latter under the reference environment's name.
func TestEveryReadingKeepsTheRequestBehindIt(t *testing.T) {
	components, connections, names := chain(4)
	fault := componentFault(names, 2)
	reference := newRunner(func(string, string) model.Verdict { return model.VerdictPass })
	walk := New(components, connections, nil, manifests(), newRunner(fault), openPlacement{},
		Options{Environment: "simulated", Reference: reference, ReferenceName: "staging",
			ReferencePlacement: openPlacement{}})
	inv := diagnose(t, walk, names[0])

	requests := walk.Requests()
	if len(requests) != len(inv.Readings) {
		t.Fatalf("%d requests kept for %d readings", len(requests), len(inv.Readings))
	}
	environments := map[string]int{}
	for _, item := range inv.Readings {
		recorded, ok := requests[item.ID]
		if !ok {
			t.Fatalf("reading %s has no request", item.ID)
		}
		if recorded.Request.ProbeID != item.Reading.ProbeID || recorded.Request.Target != item.Reading.Target {
			t.Errorf("reading %s is %s on %s; its request is %s on %s", item.ID, item.Reading.ProbeID,
				item.Reading.Target, recorded.Request.ProbeID, recorded.Request.Target)
		}
		environments[recorded.Environment]++
		// Taken again, the same request measures the same thing.
		again := newRunner(fault).Run(context.Background(), recorded.Request)
		if recorded.Environment == "simulated" && again.Verdict != item.Reading.Verdict {
			t.Errorf("reading %s was %s; its request, run again, is %s", item.ID, item.Reading.Verdict, again.Verdict)
		}
	}
	if environments["staging"] != 1 || environments["simulated"] != len(inv.Readings)-1 {
		t.Errorf("requests by environment: %v", environments)
	}
}
