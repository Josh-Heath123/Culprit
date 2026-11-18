package main

import (
	"bytes"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The fault library (DIAGNOSTIC_PLAN.md Phase 32 field 13): every fault the
// demo services can be given, injected into demo-services/faults/, walked by
// `culprit diagnose` from inside the vantage container, and compared with
// cli/testdata/faultlib/expected.json.
//
// It needs Docker, so it runs only when CULPRIT_FAULT_LIBRARY=1 — `just
// fault-library` locally, and its own CI job on every push. The faults are
// test harness: none of this is a probe, a capability or anything the
// binary does (Phase 32, "The fault library's faults are test harness").

type faultExpectation struct {
	Name        string          `json:"name"`
	Inject      string          `json:"inject"`
	Vantage     string          `json:"vantage"`
	Environment string          `json:"environment"`
	RootSubject string          `json:"root_subject"`
	Complete    bool            `json:"complete"`
	Relations   []string        `json:"relations"`
	Rubric      map[string]bool `json:"rubric"`
	// Edges are the fault tree's shape: "from -[relation]-> to", exactly.
	Edges []string `json:"edges"`
	// StatementContains, when set, must appear in the diagnosis statement —
	// how a partial diagnosis says why it is partial.
	StatementContains string `json:"statement_contains"`
	// Attestation is how the symptom's occurrence is known: every symptom
	// here is a POST, which no probe replays, so "reported".
	Attestation string `json:"attestation"`
	// Fix is the known fix, and the verdict `culprit verify` must give
	// once it is applied (Phase 34).
	Fix faultFix `json:"fix"`
	// Kind is the fault injected and fixed, when it is not Name: the same
	// fault walked under another manifest (Phase 36 part 2).
	Kind string `json:"kind"`
	// Manifest is the culprit.yaml the walk reads, in the walk bundle;
	// empty is the demo's own.
	Manifest string `json:"manifest"`
	// RootKind, when set, is the kind of the supported hypothesis on the
	// root subject (Phase 36 part 2: latency_budget_exceeded).
	RootKind string `json:"root_kind"`
	// Symptom, when set, is this fault's symptom in place of the library's:
	// the database fault is seen on the list route, not on an order
	// (Phase 37 part 3).
	Symptom string `json:"symptom"`
	// RemediationContains, when set, must appear in the diagnosis's
	// remediation: the change the walk recommends.
	RemediationContains string `json:"remediation_contains"`
}

// symptom is the fault's own symptom, or the library's.
func (f faultExpectation) symptom(library string) string {
	if f.Symptom != "" {
		return f.Symptom
	}
	return library
}

// injection is the fault injected and fixed.
func (f faultExpectation) injection() string {
	if f.Kind != "" {
		return f.Kind
	}
	return f.Name
}

// manifest is the culprit.yaml the walk reads, inside the container.
func (f faultExpectation) manifest() string {
	if f.Manifest != "" {
		return "/tmp/walk/" + f.Manifest
	}
	return "/tmp/walk/culprit.yaml"
}

type faultFix struct {
	How     string   `json:"how"`
	Change  []string `json:"change"`
	Verdict string   `json:"verdict"`
	// ReasonContains, when set, must appear in the verification's reason.
	ReasonContains string `json:"reason_contains"`
}

// faultScenario is a fault, a change that is not simply its fix, and the
// verdict verification must give for it.
type faultScenario struct {
	Name    string   `json:"name"`
	Fault   string   `json:"fault"`
	Apply   string   `json:"apply"`
	How     string   `json:"how"`
	Change  []string `json:"change"`
	Verdict string   `json:"verdict"`
	// ReasonContains, when set, must appear in the verification's reason.
	ReasonContains string `json:"reason_contains"`
}

type faultLibrary struct {
	Symptom   string             `json:"symptom"`
	Faults    []faultExpectation `json:"faults"`
	Scenarios []faultScenario    `json:"scenarios"`
}

var (
	repoRoot     = filepath.Join("..", "..", "..")
	faultCompose = filepath.Join(repoRoot, "demo-services", "faults", "docker-compose.yml")
	healthyLayer = filepath.Join(repoRoot, "demo-services", "faults", "docker-compose.configured.yml")
	demoManifest = filepath.Join(repoRoot, "demo-services", "culprit.yaml")
)

const faultProject = "culprit-faults"

type faultStack struct {
	t      *testing.T
	env    []string
	good   string
	walkIn string // a host directory holding the linux binary and culprit.yaml
	// tree is the demo's source the walk reads, as the fault planted it:
	// which of inventory-service's migrations the bundle holds (Q33 (2)).
	tree demoTree
	// secrets are every token minted and the secret that signed them. None
	// may appear anywhere in what `culprit diagnose` prints.
	secrets []string
}

func TestTheFaultLibrary(t *testing.T) {
	if os.Getenv("CULPRIT_FAULT_LIBRARY") != "1" {
		t.Skip("needs Docker; run with CULPRIT_FAULT_LIBRARY=1 (just fault-library)")
	}
	raw, err := os.ReadFile(filepath.Join("..", "..", "testdata", "faultlib", "expected.json"))
	if err != nil {
		t.Fatal(err)
	}
	var library faultLibrary
	if err := json.Unmarshal(raw, &library); err != nil {
		t.Fatal(err)
	}

	// CULPRIT_FAULT_LIBRARY_SHARD=<k> runs shard k of faultLibraryShards
	// only (the CI job's matrix); unset, every case runs.
	shard, err := shardFromEnvironment(os.Getenv("CULPRIT_FAULT_LIBRARY_SHARD"))
	if err != nil {
		t.Fatal(err)
	}
	byName := map[string]faultExpectation{}
	for _, fault := range library.Faults {
		byName[fault.Name] = fault
	}
	runs := func(name string) bool { return shard == 0 || shardOf(library, name) == shard }

	stack := startFaultStack(t)
	results := faultResults{
		Why: "Written by TestTheFaultLibrary (CULPRIT_FAULT_LIBRARY_RESULTS): each planted fault, " +
			"diagnosed, its known fix applied and verified; and each scenario, a deliberate wrong or " +
			"partial fix. scripts/accuracy_readme.py renders the README's number from this file.",
	}
	for _, fault := range library.Faults {
		if !runs(fault.Name) {
			continue
		}
		t.Run(fault.Name, func(t *testing.T) {
			stack.t = t
			// Phase 39 part 2: in an environment declared isolated, the load
			// generator, the database's only other client, is stopped before
			// the walk and through verify, and started again afterwards.
			if declaredIsolated(t, fault.Environment) {
				stack.pauseLoad()
				defer stack.resumeLoad()
			}
			inv, restore := stack.injectAndDiagnose(fault.symptom(library.Symptom), fault)
			defer restore()
			// Phase 36 part 1: the demo's latency budget, measured by the
			// probe alone: it fails under the fault and passes once it is
			// cleared. Part 2's walk uses the same budget.
			if fault.Name == "latency" {
				stack.measureLatency(fault, readyRoute, model.VerdictFail)
			}
			// Phase 37 part 3 (Q35): at 0002 the list route's p95 is at least
			// twice its budget, and the statement's mean in the walk's window
			// at least 1.5 times its own.
			if fault.Name == "missing-index" {
				stack.checkRouteP95(stack.measureLatency(fault, productsRoute, model.VerdictFail), productsRouteBudgetMs, ">=", 2)
				stack.checkStatementMean(investigationReadings(inv), ">=", 1.5*productsStatementBudgetMs)
			}
			// Phase 39 part 2 (decision 4): the N+1 route's p95 with the
			// toggle, at least twice its budget; its MEASURED lines are the
			// spread the budget is set from.
			if fault.injection() == "n-plus-one" {
				stack.checkRouteP95(stack.measureLatency(fault, detailsRoute, model.VerdictFail),
					routeBudgetMs(t, detailsRoute.subject), ">=", 2)
			}
			// Phase 34: the loop closed. Apply the known fix, then verify
			// from the same vantage with the change named.
			state := stack.keepState(fault.Vantage)
			stack.applyFix(fault.injection(), restore)
			if fault.Name == "latency" {
				stack.measureLatency(fault, readyRoute, model.VerdictPass)
			}
			if fault.Name == "missing-index" {
				stack.checkRouteP95(stack.measureLatency(fault, productsRoute, model.VerdictPass), productsRouteBudgetMs, "<=", 0.5)
				// Phase 38 part 2: the list route within its bound.
				stack.countList(fault, productsRoute)
			}
			if fault.injection() == "n-plus-one" {
				// Fixed: at most half the budget. And the list probe counts the
				// route's real page, not zero (Phase 38's count of 0, closed).
				// The fix recreated inventory-service, the vantage, and the
				// bundle with it. Its first requests open the pool's
				// connections: one in fifty took about 90 ms in CI, which a
				// p95 judged from 50 samples cannot place (LIMITS). Warmed, as
				// the harness waits for a recreated service to answer.
				stack.rebundle(fault)
				stack.warm(detailsPath, 20)
				stack.checkRouteP95(stack.measureLatency(fault, detailsRoute, model.VerdictPass),
					routeBudgetMs(t, detailsRoute.subject), "<=", 0.5)
				stack.countList(fault, detailsRoute)
			}
			verification := stack.verify(fault, inv, state, fault.Fix.Change)
			stack.checkVerification(verification, inv, fault.Fix.Verdict, fault.Fix.ReasonContains)
			if fault.Name == "missing-index" {
				// At 0003 the statement's mean is under 2 ms, in both of
				// verification's windows.
				stack.checkStatementMean(rerunReadings(verification), "<", 2)
			}
			results.Faults = append(results.Faults, resultOf(fault.Name, inv, verification))
		})
	}
	for _, scenario := range library.Scenarios {
		if !runs("verify/" + scenario.Name) {
			continue
		}
		t.Run("verify/"+scenario.Name, func(t *testing.T) {
			stack.t = t
			fault, ok := byName[scenario.Fault]
			if !ok {
				t.Fatalf("scenario %s names fault %s, which the library does not have", scenario.Name, scenario.Fault)
			}
			inv, restore := stack.injectAndDiagnose(fault.symptom(library.Symptom), fault)
			defer restore()
			state := stack.keepState(fault.Vantage)
			stack.applyScenario(scenario.Apply)
			verification := stack.verify(fault, inv, state, scenario.Change)
			stack.checkVerification(verification, inv, scenario.Verdict, scenario.ReasonContains)
			if scenario.Apply == "index-category-only" {
				// Q35: with category alone the mean is still over the 10 ms
				// budget, and the plan still filters category on the sku index.
				reran := rerunReadings(verification)
				stack.checkStatementMean(reran, ">", productsStatementBudgetMs)
				stack.checkPlanFiltersOnSkuIndex(reran)
			}
			results.Scenarios = append(results.Scenarios, resultOf(scenario.Name, inv, verification))
		})
	}
	// Phase 35 part 1: the audience fault's loop again, through `culprit
	// mcp` — the real binary, in the vantage container, driven over its
	// stdin and stdout by a scripted MCP client as a coding agent drives
	// it: culprit_diagnose, the fix applied, culprit_verify. The right fix
	// is verified; the wrong one is not_resolved. Not results the README
	// counts: the faults above are.
	for _, loop := range mcpLoops {
		if !runs("mcp/" + loop.name) {
			continue
		}
		t.Run("mcp/"+loop.name, func(t *testing.T) {
			stack.t = t
			fault := byName["auth-audience"]
			inv, restore := stack.injectAndWalk(library.Symptom, fault, stack.diagnoseThroughMCP, false)
			defer restore()
			state := stack.keepState(fault.Vantage)
			if loop.apply == "" {
				stack.applyFix(fault.Name, restore)
			} else {
				stack.applyScenario(loop.apply)
			}
			verification := stack.verifyThroughMCP(fault, inv, state, fault.Fix.Change)
			stack.checkVerification(verification, inv, loop.verdict, loop.reason)
		})
	}
	// Phase 34 part 2: the results the README's number is rendered from —
	// only when every case passed, so a failed run never writes them. A
	// shard writes its own cases' entries and keeps the committed ones for
	// every other case, so the job's diff holds each shard to its own.
	if path := os.Getenv("CULPRIT_FAULT_LIBRARY_RESULTS"); path != "" && !t.Failed() {
		if shard != 0 {
			committed, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			if results, err = mergeShardResults(library, shard, results, committed); err != nil {
				t.Fatal(err)
			}
		}
		// Not HTML-escaped: a subject's arrow is written as itself, so a
		// person reading the committed file sees what the README cites.
		var encoded bytes.Buffer
		encoder := json.NewEncoder(&encoded)
		encoder.SetEscapeHTML(false)
		encoder.SetIndent("", "  ")
		if err := encoder.Encode(results); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, encoded.Bytes(), 0o644); err != nil {
			t.Fatal(err)
		}
	}
}

// faultResults is what one run of the library found, case by case, in
// the library's own order. Nothing in it varies between two runs that
// reach the same verdicts: no time, no id.
type faultResults struct {
	Why       string        `json:"why"`
	Faults    []faultResult `json:"faults"`
	Scenarios []faultResult `json:"scenarios"`
}

type faultResult struct {
	Name        string `json:"name"`
	RootSubject string `json:"root_subject"`
	Complete    bool   `json:"complete"`
	Verdict     string `json:"verdict"`
}

func resultOf(name string, inv model.Investigation, verification model.Verification) faultResult {
	result := faultResult{Name: name, Verdict: string(verification.Verdict)}
	if inv.Diagnosis != nil {
		result.RootSubject, result.Complete = inv.Diagnosis.RootSubject, inv.Diagnosis.Complete
	}
	return result
}

// injectAndDiagnose puts the stack in its healthy state, shows the symptom
// is real, injects the fault, walks it and checks the diagnosis. It
// returns the investigation and what undoes the fault, which may be
// called more than once.
func (stack *faultStack) injectAndDiagnose(symptom string, fault faultExpectation) (model.Investigation, func()) {
	stack.t.Helper()
	return stack.injectAndWalk(symptom, fault, stack.diagnose, true)
}

// injectAndWalk is injectAndDiagnose with the walk named: `culprit
// diagnose`, or culprit_diagnose through `culprit mcp` (Phase 35).
func (stack *faultStack) injectAndWalk(symptom string, fault faultExpectation,
	walk func(string, faultExpectation) model.Investigation, record bool,
) (model.Investigation, func()) {
	t := stack.t
	t.Helper()
	stack.healthy()
	if fault.injection() == "n-plus-one" {
		// The route answers on the healthy stack and with the toggle, which
		// slows it without failing it.
		if status := stack.list(detailsPath); status != 200 {
			t.Fatalf("GET %s on the healthy stack answered %d, want 200", detailsPath, status)
		}
		restore := once(stack.inject(fault.injection()))
		if status := stack.list(detailsPath); status != 200 {
			t.Fatalf("GET %s with N_PLUS_ONE_FAULT answered %d, want 200", detailsPath, status)
		}
		inv := walk(symptom, fault)
		stack.record(fault, inv, record)
		checkDiagnosis(t, fault, inv)
		return inv, restore
	}
	if fault.injection() == "missing-index" {
		// The list route answers on the healthy stack and under the fault,
		// which slows it without failing it. A GET, sent from inside
		// inventory-service as a user's would arrive.
		if status := stack.listProducts(); status != 200 {
			t.Fatalf("GET /products on the healthy stack answered %d, want 200", status)
		}
		restore := once(stack.inject(fault.injection()))
		if status := stack.listProducts(); status != 200 {
			t.Fatalf("GET /products with the database at 0002 answered %d, want 200", status)
		}
		inv := walk(symptom, fault)
		stack.record(fault, inv, record)
		checkDiagnosis(t, fault, inv)
		return inv, restore
	}
	// The symptom is real before the walk is asked about it: the
	// order succeeds on the healthy stack and fails under the fault
	// (latency slows it down without failing it). Harness, not a
	// probe — a probe never writes.
	if status := stack.placeOrder(); status != 201 {
		t.Fatalf("POST /orders on the healthy stack answered %d, want 201", status)
	}
	restore := once(stack.inject(fault.injection()))
	status := stack.placeOrder()
	if fault.injection() == "latency" {
		if status != 201 {
			t.Fatalf("POST /orders under added latency answered %d, want 201", status)
		}
	} else if status < 500 {
		t.Fatalf("POST /orders under the fault answered %d; the fault is not real", status)
	}

	inv := walk(symptom, fault)
	stack.record(fault, inv, record)
	checkDiagnosis(t, fault, inv)
	return inv, restore
}

// record keeps a real investigation when CULPRIT_FAULT_LIBRARY_RECORD=<dir>
// names where: the API's round-trip test posts the audience one
// (api/tests/data/), so it is tested on what the walk wrote, not on
// something written by hand to look like it.
func (stack *faultStack) record(fault faultExpectation, inv model.Investigation, record bool) {
	if dir := os.Getenv("CULPRIT_FAULT_LIBRARY_RECORD"); dir != "" && record {
		encoded, _ := json.MarshalIndent(inv, "", "  ")
		_ = os.WriteFile(filepath.Join(dir, fault.Name+".json"), append(encoded, '\n'), 0o644)
	}
}

// once makes an undo safe to call twice: a fix that is the undo runs it,
// and the deferred cleanup runs it again.
func once(undo func()) func() {
	done := false
	return func() {
		if !done {
			done = true
			undo()
		}
	}
}

// phaseNumber is the same pattern internal/isolate's tests use: a plan
// phase named in text a person reads.
var phaseNumber = regexp.MustCompile(`(?i)\bphase \d`)

func checkDiagnosis(t *testing.T, want faultExpectation, inv model.Investigation) {
	t.Helper()
	if err := inv.Validate(); err != nil {
		t.Fatalf("the investigation does not validate: %v", err)
	}
	d := inv.Diagnosis
	if d == nil {
		t.Fatal("no diagnosis")
	}
	// The wording changes, the verdicts do not: what a person reads names
	// no plan phase and no raw hypothesis kind, on a real walk as on the
	// simulated ones in internal/isolate.
	readable := map[string]string{
		"statement": d.Statement, "remediation": d.Remediation,
		"reproduced reason": d.Confidence.Reproduced.Reason, "discriminated reason": d.Confidence.Discriminated.Reason,
		"counterfactual reason": d.Confidence.Counterfactual.Reason, "verified reason": d.Confidence.Verified.Reason,
	}
	for _, h := range inv.Hypotheses {
		readable["hypothesis "+h.ID+" reason"] = h.Reason
	}
	for where, text := range readable {
		if phaseNumber.MatchString(text) {
			t.Errorf("%s names a plan phase: %q", where, text)
		}
		for _, kind := range model.HypothesisKinds {
			if strings.Contains(text, kind) {
				t.Errorf("%s contains the raw kind %s: %q", where, kind, text)
			}
		}
		if strings.Contains(text, "->") {
			t.Errorf("%s contains an arrow pair: %q", where, text)
		}
	}
	if d.RootSubject != want.RootSubject {
		t.Errorf("root %s, want %s\nstatement: %s", d.RootSubject, want.RootSubject, d.Statement)
	}
	if want.RootKind != "" {
		supported := false
		for _, h := range inv.Hypotheses {
			supported = supported || (h.Subject == d.RootSubject && h.Kind == want.RootKind &&
				h.Status == model.HypothesisSupported)
		}
		if !supported {
			t.Errorf("no supported %s hypothesis on the root %s", want.RootKind, d.RootSubject)
		}
	}
	if want.StatementContains != "" && !strings.Contains(d.Statement, want.StatementContains) {
		t.Errorf("the statement does not say %q: %s", want.StatementContains, d.Statement)
	}
	if want.RemediationContains != "" && !strings.Contains(d.Remediation, want.RemediationContains) {
		t.Errorf("the remediation does not say %q: %s", want.RemediationContains, d.Remediation)
	}
	if got := string(inv.Symptom.Attestation.Kind); got != want.Attestation {
		t.Errorf("symptom attestation %s, want %s", got, want.Attestation)
	}
	if d.Complete != want.Complete {
		t.Errorf("complete = %v, want %v\nstatement: %s", d.Complete, want.Complete, d.Statement)
	}
	relations := map[string]bool{}
	for _, edge := range inv.FaultTree {
		relations[string(edge.Relation)] = true
	}
	var got []string
	for relation := range relations {
		got = append(got, relation)
	}
	sort.Strings(got)
	if strings.Join(got, ",") != strings.Join(want.Relations, ",") {
		t.Errorf("fault tree relations %v, want %v", got, want.Relations)
	}
	// The shape, not only the relations: which subjects each edge joins.
	var edges []string
	for _, edge := range inv.FaultTree {
		edges = append(edges, edge.FromSubject+" -["+string(edge.Relation)+"]-> "+edge.ToSubject)
	}
	sort.Strings(edges)
	wantEdges := append([]string(nil), want.Edges...)
	sort.Strings(wantEdges)
	if strings.Join(edges, "\n") != strings.Join(wantEdges, "\n") {
		t.Errorf("fault tree edges:\n  %s\nwant:\n  %s", strings.Join(edges, "\n  "), strings.Join(wantEdges, "\n  "))
	}
	for name, criterion := range map[string]model.Criterion{
		"reproduced": d.Confidence.Reproduced, "discriminated": d.Confidence.Discriminated,
		"counterfactual": d.Confidence.Counterfactual, "verified": d.Confidence.Verified,
	} {
		if criterion.Holds != want.Rubric[name] {
			t.Errorf("rubric %s = %v (%s), want %v", name, criterion.Holds, criterion.Reason, want.Rubric[name])
		}
	}
	if t.Failed() {
		encoded, _ := json.MarshalIndent(inv, "", "  ")
		t.Logf("investigation:\n%s", encoded)
	}
}

// ---- the stack ---------------------------------------------------------------

func startFaultStack(t *testing.T) *faultStack {
	t.Helper()
	secret := randomHex(t)
	stack := &faultStack{
		t:    t,
		good: mintToken(secret, "inventory-service"),
		env:  []string{"DEMO_TOKEN_SECRET=" + secret},
	}
	stack.secrets = []string{secret, stack.good}
	stack.walkIn = buildWalkBundle(t)
	stack.compose(stack.withToken(stack.good), "up", "-d", "--build")
	t.Cleanup(func() { stack.compose(stack.withToken(stack.good), "down", "--volumes", "--timeout", "2") })
	return stack
}

func (s *faultStack) withToken(token string, extra ...string) []string {
	return append(append([]string{"INVENTORY_TOKEN=" + token}, s.env...), extra...)
}

// compose runs docker compose against the fault stack with the healthy
// layer, and fails the test if it fails.
func (s *faultStack) compose(env []string, args ...string) string {
	return s.composeFiles(env, []string{faultCompose, healthyLayer}, args...)
}

func (s *faultStack) composeFiles(env []string, files []string, args ...string) string {
	s.t.Helper()
	full := []string{"compose", "-p", faultProject}
	for _, file := range files {
		full = append(full, "-f", file)
	}
	return s.docker(env, append(full, args...)...)
}

func (s *faultStack) docker(env []string, args ...string) string {
	s.t.Helper()
	command := exec.Command("docker", args...)
	command.Env = append(os.Environ(), env...)
	output, err := command.CombinedOutput()
	if err != nil {
		s.t.Fatalf("docker %s: %v\n%s", strings.Join(args, " "), err, output)
	}
	return string(output)
}

func (s *faultStack) container(service string) string {
	return faultProject + "-" + service + "-1"
}

// healthy puts every service back to its healthy configuration and waits
// until each one answers.
// placeOrder sends the symptom's request from inside order-service and
// returns the status — what a user would have seen.
func (s *faultStack) placeOrder() int {
	s.t.Helper()
	script := "import urllib.request,urllib.error\nr=urllib.request.Request('http://localhost:8001/orders'," +
		"data=b'{\"sku\":\"fault-library\",\"qty\":1,\"amount\":1.0}'," +
		"headers={'Content-Type':'application/json'},method='POST')\n" +
		"try:\n print(urllib.request.urlopen(r,timeout=15).status)\n" +
		"except urllib.error.HTTPError as e:\n print(e.code)"
	output := strings.TrimSpace(s.docker(nil, "exec", s.container("order-service"), "python", "-c", script))
	var status int
	if _, err := fmt.Sscanf(output, "%d", &status); err != nil {
		s.t.Fatalf("placing an order printed %q", output)
	}
	return status
}

// The demo services only, never their dependencies: inventory-service's
// database is set up once per stack (a million seeded rows), and the
// database fault's own undo puts it back at the head.
func (s *faultStack) healthy() {
	s.tree = treeHead
	s.compose(s.withToken(s.good), "up", "-d", "--force-recreate", "--no-deps",
		"order-service", "inventory-service", "payments-service")
	s.waitFor("order-service", "http://inventory-service:8002/ready", "http://payments-service:8003/ready",
		"http://order-service:8001/health")
	s.atTop()
}

func (s *faultStack) waitFor(from string, urls ...string) {
	s.t.Helper()
	script := "import urllib.request,sys\nfor u in sys.argv[1:]: urllib.request.urlopen(u, timeout=2)"
	deadline := time.Now().Add(90 * time.Second)
	for {
		command := exec.Command("docker", append([]string{"exec", s.container(from), "python", "-c", script}, urls...)...)
		if command.Run() == nil {
			return
		}
		if time.Now().After(deadline) {
			s.t.Fatalf("%v did not answer from %s within 90s", urls, from)
		}
		time.Sleep(time.Second)
	}
}

// post sends a JSON POST from inside a container — the demo's admin fault
// endpoints are not published.
func (s *faultStack) post(from, url, body string) { s.send(from, "POST", url, body) }

func (s *faultStack) send(from, method, url, body string) {
	s.t.Helper()
	script := "import urllib.request,sys\nr=urllib.request.Request(sys.argv[1],data=sys.argv[2].encode() or None," +
		"headers={'Content-Type':'application/json'},method=sys.argv[3])\nurllib.request.urlopen(r,timeout=5)"
	s.docker(nil, "exec", s.container(from), "python", "-c", script, url, body, method)
}

// inject applies one fault and returns what undoes it.
func (s *faultStack) inject(name string) func() {
	switch name {
	case "auth-audience", "auth-audience-ungranted":
		wrong := mintToken(strings.TrimPrefix(s.env[0], "DEMO_TOKEN_SECRET="), "inventory")
		s.secrets = append(s.secrets, wrong)
		s.compose(s.withToken(wrong), "up", "-d", "--force-recreate", "order-service")
		s.waitFor("order-service", "http://inventory-service:8002/ready", "http://localhost:8001/health")
		return func() {}
	case "network-partition":
		address := strings.TrimSpace(s.docker(nil, "inspect", "-f",
			`{{(index .NetworkSettings.Networks "`+faultProject+`_default").IPAddress}}`,
			s.container("inventory-service")))
		rule := "OUTPUT -d " + address + " -p tcp -j REJECT --reject-with tcp-reset"
		s.iptables("-A " + rule)
		return func() { s.iptables("-D " + rule) }
	case "contract":
		s.compose(s.withToken(s.good, "CONTRACT_FAULT=stock-route-renamed"), "up", "-d", "--force-recreate", "--no-deps", "inventory-service")
		s.waitFor("order-service", "http://inventory-service:8002/ready")
		return func() {}
	case "config":
		// The base file alone: payments-service without its provider key.
		s.composeFiles(s.withToken(s.good), []string{faultCompose}, "up", "-d", "--force-recreate", "payments-service")
		s.waitFor("order-service", "http://payments-service:8003/health")
		return func() {}
	case "error-rate":
		s.post("order-service", "http://inventory-service:8002/admin/fault/error-rate", `{"rate": 1.0, "duration_s": 300}`)
		return func() { s.send("order-service", "DELETE", "http://inventory-service:8002/admin/fault", "") }
	case "latency":
		s.post("order-service", "http://inventory-service:8002/admin/fault/latency", `{"delay_ms": 800, "duration_s": 300}`)
		return func() { s.send("order-service", "DELETE", "http://inventory-service:8002/admin/fault", "") }
	case "n-plus-one":
		// Phase 39 part 2: a toggle, as CONTRACT_FAULT is. GET
		// /products/details loads each product's details with a statement
		// of its own. Its undo, and its known fix, recreate inventory-service
		// without it.
		s.compose(s.withToken(s.good, "N_PLUS_ONE_FAULT=details-per-product"), "up", "-d", "--force-recreate", "--no-deps", "inventory-service")
		s.waitFor("order-service", "http://inventory-service:8002/ready")
		return s.fixContract
	case "missing-index":
		// Planted in the database and in the tree (Q33 (2)): the database
		// at 0002, and the walk's tree holding 0001-0002 only.
		s.alembic("downgrade", demoFaultRevision)
		s.tree = treeFault
		return s.restoreDatabase
	}
	s.t.Fatalf("the fault library has no injection for %q", name)
	return nil
}

// iptables edits order-service's own network namespace from a throwaway
// sidecar — Phase 31.1's partition, now a fixture.
func (s *faultStack) iptables(rule string) {
	s.docker(nil, "run", "--rm", "--net", "container:"+s.container("order-service"), "--cap-add", "NET_ADMIN",
		"alpine:3.20", "sh", "-c", "apk add -q iptables >/dev/null && iptables "+rule)
}

// diagnose copies the binary and the demo's culprit.yaml into the vantage
// container and runs the walk there, from where that component sits.
func (s *faultStack) diagnose(symptom string, fault faultExpectation) model.Investigation {
	s.t.Helper()
	container := s.container(fault.Vantage)
	s.docker(nil, "exec", "-u", "0", container, "rm", "-rf", "/tmp/walk", containerState)
	s.copyBundle(container)
	// The demo manifest's extractors run on every walk (Q33 (3)): no
	// --no-plugins anywhere in the library's walks.
	command := exec.Command("docker", "exec", container, "/tmp/walk/culprit", "diagnose", symptom,
		"-f", fault.manifest(), "--env", fault.Environment, "--from", fault.Vantage,
		"--format", "json", "--agent-id", "fault-library", "--state-dir", containerState)
	output, err := command.Output()
	if err != nil {
		if exit, ok := err.(*exec.ExitError); !ok || exit.ExitCode() != exitFindings {
			s.t.Fatalf("culprit diagnose in %s: %v\n%s", container, err, output)
		}
	}
	var inv model.Investigation
	if err := json.Unmarshal(output, &inv); err != nil {
		s.t.Fatalf("culprit diagnose did not print an investigation: %v\n%s", err, output)
	}

	// The walk reads order-service's token to check its audience. Neither
	// it nor the secret behind it may reach the investigation, in either
	// format, on any fault.
	text, _ := exec.Command("docker", "exec", container, "/tmp/walk/culprit", "diagnose", symptom,
		"-f", fault.manifest(), "--env", fault.Environment, "--from", fault.Vantage,
		"--format", "text", "--state-dir", containerState).Output()
	if fault.Name == "n-plus-one" {
		// The README quotes this from CI's log, never by hand (Phase 39
		// part 2, item 6).
		s.t.Logf("README OUTPUT (culprit diagnose, N+1):\n%s", text)
	}
	for _, secret := range s.secrets {
		for format, printed := range map[string][]byte{"json": output, "text": text} {
			if strings.Contains(string(printed), secret) {
				s.t.Errorf("a token or its secret appears in the %s investigation", format)
			}
		}
	}
	return inv
}

// budgetedRoute is a route probe.http.latency times against the budget the
// demo's culprit.yaml declares for it.
type budgetedRoute struct{ subject string }

var (
	readyRoute    = budgetedRoute{"http:inventory-service/GET /ready"}
	productsRoute = budgetedRoute{"http:inventory-service/GET /products"}
	// Phase 39 part 2: the N+1 fault's route.
	detailsRoute = budgetedRoute{"http:inventory-service/GET " + detailsPath}
)

const detailsPath = "/products/details"

// latencyBudgetLocator is where the demo's culprit.yaml declares the p95
// budget on subject, found by its subject rather than by its position, so
// reordering the file's budgets moves nothing here (Phase 38 part 1).
func latencyBudgetLocator(t *testing.T, subject string) string {
	t.Helper()
	return budgetLocator(t, subject, "latency_p95_ms")
}

// budgetLocator is where the demo's culprit.yaml declares subject's one
// budget under predicate.
func budgetLocator(t *testing.T, subject, predicate string) string {
	t.Helper()
	manifest, err := extract.LoadManifest(demoManifest)
	if err != nil {
		t.Fatalf("the demo's culprit.yaml: %v", err)
	}
	locator := ""
	for index, budget := range manifest.Budgets {
		if budget.Subject == subject && budget.Predicate == predicate {
			if locator != "" {
				t.Fatalf("the demo's culprit.yaml declares two %s budgets on %s", predicate, subject)
			}
			locator = fmt.Sprintf("budgets[%d]", index)
		}
	}
	if locator == "" {
		t.Fatalf("the demo's culprit.yaml declares no %s budget on %s", predicate, subject)
	}
	return locator
}

// countList runs probe.http.response_items on one of inventory-service's
// list routes from the fault's vantage, against the demo's
// response_items_max budget (Phase 38 part 2), and checks it passes: the
// criterion "culprit probe on the faults stack passes GET /products at 50
// items". It logs the count. GET /products/details (Phase 39 part 2) must
// count a real page, not zero.
func (s *faultStack) countList(fault faultExpectation, route budgetedRoute) {
	s.t.Helper()
	container := s.container(fault.Vantage)
	output, err := exec.Command("docker", "exec", container, "/tmp/walk/culprit", "probe",
		route.subject, "-p", model.ResponseItemsProbeID,
		"--input", "base_url=http://inventory-service:8002",
		"-f", "/tmp/walk/culprit.yaml", "--env", fault.Environment,
		"--no-plugins", "--format", "json", "--agent-id", "fault-library").Output()
	if err != nil {
		s.t.Errorf("culprit probe probe.http.response_items in %s: %v\n%s", container, err, output)
		return
	}
	var result struct {
		Readings []model.Reading `json:"readings"`
	}
	if err := json.Unmarshal(output, &result); err != nil || len(result.Readings) != 1 {
		s.t.Fatalf("culprit probe printed no single reading (%v):\n%s", err, output)
	}
	reading := result.Readings[0]
	s.t.Logf("%s: %s, measured %v against %v", route.subject, reading.Verdict, reading.Measured, reading.Expected)
	if reading.Verdict != model.VerdictPass {
		s.t.Errorf("probe.http.response_items on %s: %s, want pass: %s", route.subject, reading.Verdict, reading.Reason)
	}
	if items, _ := reading.Measured["items"].(float64); route == detailsRoute && items < 2 {
		s.t.Errorf("probe.http.response_items counted %v items on %s, want its page", reading.Measured["items"], route.subject)
	}
	if err := reading.Validate(); err != nil {
		s.t.Errorf("the list reading does not validate: %v", err)
	}
	if reading.ExpectedSource == nil ||
		reading.ExpectedSource.Locator != budgetLocator(s.t, route.subject, "response_items_max") {
		s.t.Errorf("the reading was not measured against the demo's list budget: %+v", reading.ExpectedSource)
	}
	// Expected is the judged form, read back from JSON.
	if bound := listBound(s.t, route.subject); reading.Expected["response_items_max"] != float64(bound) ||
		reading.Expected["at"] != "/products" {
		s.t.Errorf("judged against %v, want %d items at /products", reading.Expected, bound)
	}
	if route != productsRoute {
		return
	}
	// The same command as the README shows it, in text, logged whole: the
	// README quotes this output from CI's log, never by hand (Phase 39
	// part 1, item 1).
	text, err := exec.Command("docker", "exec", container, "/tmp/walk/culprit", "probe",
		productsRoute.subject, "-p", model.ResponseItemsProbeID,
		"--input", "base_url=http://inventory-service:8002",
		"-f", "/tmp/walk/culprit.yaml", "--env", fault.Environment,
		"--no-plugins", "--agent-id", "fault-library").CombinedOutput()
	if err != nil {
		s.t.Errorf("culprit probe probe.http.response_items in text in %s: %v\n%s", container, err, text)
		return
	}
	s.t.Logf("README OUTPUT (culprit probe, list budget):\n%s", text)
}

// measureLatency runs probe.http.latency on one of inventory-service's
// routes from the fault's vantage, against the budget the demo's
// culprit.yaml declares (Phase 36 part 1), checks its verdict and returns
// the reading.
func (s *faultStack) measureLatency(fault faultExpectation, route budgetedRoute, want model.Verdict) model.Reading {
	s.t.Helper()
	container := s.container(fault.Vantage)
	output, err := exec.Command("docker", "exec", container, "/tmp/walk/culprit", "probe",
		route.subject, "-p", model.LatencyProbeID,
		"--input", "base_url=http://inventory-service:8002",
		"-f", "/tmp/walk/culprit.yaml", "--env", fault.Environment,
		"--no-plugins", "--format", "json", "--agent-id", "fault-library").Output()
	if err != nil {
		if exit, ok := err.(*exec.ExitError); !ok || exit.ExitCode() != exitFindings {
			s.t.Fatalf("culprit probe probe.http.latency in %s: %v\n%s", container, err, output)
		}
	}
	var result struct {
		Readings []model.Reading `json:"readings"`
	}
	if err := json.Unmarshal(output, &result); err != nil || len(result.Readings) != 1 {
		s.t.Fatalf("culprit probe printed no single reading (%v):\n%s", err, output)
	}
	reading := result.Readings[0]
	if reading.Verdict != want {
		s.t.Errorf("probe.http.latency on %s: %s, want %s: %s", route.subject, reading.Verdict, want, reading.Reason)
	}
	if err := reading.Validate(); err != nil {
		s.t.Errorf("the latency reading does not validate: %v", err)
	}
	if reading.ExpectedSource == nil || reading.ExpectedSource.Locator != latencyBudgetLocator(s.t, route.subject) {
		s.t.Errorf("the reading was not measured against the demo's budget: %+v", reading.ExpectedSource)
	}
	return reading
}

// buildWalkBundle cross-compiles the binary for the containers and puts it
// beside the demo's culprit.yaml and the tree its extract: section reads,
// in a directory of its own so extraction scans nothing else.
func buildWalkBundle(t *testing.T) string {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "walk")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	arch := os.Getenv("CULPRIT_FAULT_LIBRARY_ARCH")
	if arch == "" {
		arch = runtime.GOARCH
	}
	build := exec.Command("go", "build", "-o", filepath.Join(dir, "culprit"), ".")
	build.Env = append(os.Environ(), "CGO_ENABLED=0", "GOOS=linux", "GOARCH="+arch)
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("building the linux binary: %v\n%s", err, output)
	}
	raw, err := os.ReadFile(demoManifest)
	if err != nil {
		t.Fatal(err)
	}
	// The committed manifest, changed only where the container forces it:
	// the extractor's command (Q33 (3)). Its extract: section reads
	// inventory_service, beside it in the bundle, with the extractor's
	// package beside that.
	text, err := containerManifest(strings.ReplaceAll(string(raw), "\r\n", "\n"))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "culprit.yaml"), []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := bundleTree(dir); err != nil {
		t.Fatalf("copying the tree the walk reads: %v", err)
	}
	// The demo's manifest with no budgets: the latency fault walked where
	// nothing declares how fast is fast (Phase 36 part 2). The budgets are
	// the manifest's last section.
	cut := strings.Index(text, "\nbudgets:\n")
	if cut < 0 {
		t.Fatal("the demo's culprit.yaml has no budgets: section to take out")
	}
	if err := os.WriteFile(filepath.Join(dir, "culprit-no-budgets.yaml"), []byte(text[:cut+1]), 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

// mintToken makes an HS256 JWT for audience — what order-service presents.
func mintToken(secret, audience string) string {
	encode := func(value any) string {
		raw, _ := json.Marshal(value)
		return base64.RawURLEncoding.EncodeToString(raw)
	}
	unsigned := encode(map[string]string{"alg": "HS256", "typ": "JWT"}) + "." +
		encode(map[string]any{"aud": audience, "iss": "order-service", "exp": time.Now().Add(time.Hour).Unix()})
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(unsigned))
	return unsigned + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}

func randomHex(t *testing.T) string {
	buffer := make([]byte, 16)
	if _, err := rand.Read(buffer); err != nil {
		t.Fatal(err)
	}
	return hex.EncodeToString(buffer)
}

// ---- the loop closed: fix, then verify (Phase 34) ------------------------------

// containerState is where `culprit diagnose` keeps what `culprit verify`
// reads, inside the vantage container.
const containerState = "/tmp/culprit-state"

// keepState copies the state directory out of the vantage container: a
// fix may recreate that container, and its /tmp with it.
func (s *faultStack) keepState(vantage string) string {
	s.t.Helper()
	dir := filepath.Join(s.t.TempDir(), "state")
	s.docker(nil, "cp", s.container(vantage)+":"+containerState, dir)
	return dir
}

// applyFix applies a fault's known fix. Harness, like the faults: Culprit
// never applies one.
func (s *faultStack) applyFix(name string, restore func()) {
	s.t.Helper()
	switch name {
	case "auth-audience", "auth-audience-ungranted":
		s.compose(s.withToken(s.good), "up", "-d", "--force-recreate", "order-service")
		s.waitFor("order-service", "http://inventory-service:8002/ready", "http://localhost:8001/health")
	case "contract":
		s.fixContract()
	case "config":
		s.compose(s.withToken(s.good), "up", "-d", "--force-recreate", "payments-service")
		s.waitFor("order-service", "http://payments-service:8003/ready")
	case "network-partition", "error-rate", "latency", "missing-index", "n-plus-one":
		// The database fault's undo is its known fix: the commit that adds
		// 0003, with the database upgraded to it.
		restore()
	default:
		s.t.Fatalf("the fault library has no fix for %q", name)
	}
}

// fixContract recreates inventory-service from the healthy configuration:
// the contract fault's fix, and the N+1 fault's.
func (s *faultStack) fixContract() {
	s.compose(s.withToken(s.good), "up", "-d", "--force-recreate", "--no-deps", "inventory-service")
	s.waitFor("order-service", "http://inventory-service:8002/ready")
}

// applyScenario applies a change that is not simply the fault's fix.
func (s *faultStack) applyScenario(apply string) {
	s.t.Helper()
	switch apply {
	case "remint-wrong-audience":
		wrong := mintToken(strings.TrimPrefix(s.env[0], "DEMO_TOKEN_SECRET="), "inventory-svc")
		s.secrets = append(s.secrets, wrong)
		s.compose(s.withToken(wrong), "up", "-d", "--force-recreate", "order-service")
		s.waitFor("order-service", "http://inventory-service:8002/ready", "http://localhost:8001/health")
	case "fix-contract":
		s.fixContract()
	case "slow-latency-less":
		// A smaller delay, still well over the 300 ms budget: not the fix.
		s.post("order-service", "http://inventory-service:8002/admin/fault/latency", `{"delay_ms": 600, "duration_s": 300}`)
	case "fix-contract-break-payments":
		s.fixContract()
		s.post("order-service", "http://payments-service:8003/admin/fault/error-rate", `{"rate": 1.0, "duration_s": 300}`)
	case "index-category-only":
		// The wrong fix, from the library's own test data: a migration
		// indexing category alone, in the tree and applied.
		s.docker(nil, "cp", categoryOnlyMigration,
			s.container("inventory-service")+":/app/inventory_service/migrations/versions/")
		s.alembic("upgrade", categoryOnlyRevision)
		s.tree = treeCategoryOnly
	case "fix-contract-change-order-config":
		s.fixContract()
		// A config key order-service did not have: a change on another
		// component than the one the contract fix touches.
		override := filepath.Join(s.t.TempDir(), "unrelated.yml")
		if err := os.WriteFile(override, []byte("services:\n  order-service:\n    environment:\n      CULPRIT_UNRELATED_FLAG: \"on\"\n"), 0o644); err != nil {
			s.t.Fatal(err)
		}
		s.composeFiles(s.withToken(s.good), []string{faultCompose, healthyLayer, override}, "up", "-d", "--force-recreate", "order-service")
		s.waitFor("order-service", "http://inventory-service:8002/ready", "http://localhost:8001/health")
	default:
		s.t.Fatalf("the fault library has no scenario action %q", apply)
	}
}

// verify puts the binary and the kept state back in the vantage container
// — owned by the container's own user, as diagnose left them — and runs
// `culprit verify` there with the changes named.
func (s *faultStack) verify(fault faultExpectation, inv model.Investigation, state string, changes []string) model.Verification {
	s.t.Helper()
	container := s.restoreForVerify(fault, state)

	arguments := []string{"exec", container, "/tmp/walk/culprit", "verify", inv.ID,
		"-f", fault.manifest(), "--format", "json", "--agent-id", "fault-library",
		"--state-dir", containerState, "--from", fault.Vantage}
	for _, change := range changes {
		arguments = append(arguments, "--change", change)
	}
	output, err := exec.Command("docker", arguments...).Output()
	if err != nil {
		if exit, ok := err.(*exec.ExitError); !ok || exit.ExitCode() != exitFindings {
			stderr := ""
			if ok {
				stderr = string(exit.Stderr)
			}
			s.t.Fatalf("culprit verify in %s: %v\n%s%s", container, err, output, stderr)
		}
	}
	var verification model.Verification
	if err := json.Unmarshal(output, &verification); err != nil {
		s.t.Fatalf("culprit verify did not print a verification: %v\n%s", err, output)
	}
	for _, secret := range s.secrets {
		if strings.Contains(string(output), secret) {
			s.t.Errorf("a token or its secret appears in the verification")
		}
	}
	return verification
}

// restoreForVerify puts the binary and the kept state back in the vantage
// container — owned by the container's own user, as diagnose left them —
// and returns the container.
func (s *faultStack) restoreForVerify(fault faultExpectation, state string) string {
	s.t.Helper()
	container := s.container(fault.Vantage)
	s.docker(nil, "exec", "-u", "0", container, "rm", "-rf", "/tmp/walk", containerState)
	s.copyBundle(container)
	s.docker(nil, "cp", state, container+":"+containerState)
	owner := strings.TrimSpace(s.docker(nil, "exec", container, "sh", "-c", "echo $(id -u):$(id -g)"))
	s.docker(nil, "exec", "-u", "0", container, "chown", "-R", owner, containerState)
	return container
}

// ---- the loop through `culprit mcp` (Phase 35) -----------------------------------

// mcpInContainer starts `culprit mcp` in the container and returns a
// scripted client on its stdin and stdout. The session ends with the test,
// or when the container is recreated by a fix: each side of the fix is
// its own session, and the state directory carries the investigation
// across, as it does for the commands.
func (s *faultStack) mcpInContainer(container, vantage string) *mcpClient {
	s.t.Helper()
	command := exec.Command("docker", "exec", "-i", container, "/tmp/walk/culprit", "mcp",
		"-f", "/tmp/walk/culprit.yaml", "--from", vantage, "--agent-id", "fault-library",
		"--state-dir", containerState)
	stdin, err := command.StdinPipe()
	if err != nil {
		s.t.Fatal(err)
	}
	stdout, err := command.StdoutPipe()
	if err != nil {
		s.t.Fatal(err)
	}
	var stderr bytes.Buffer
	command.Stderr = &stderr
	if err := command.Start(); err != nil {
		s.t.Fatal(err)
	}
	t := s.t
	t.Cleanup(func() {
		_ = stdin.Close()
		if err := command.Wait(); err != nil {
			t.Logf("culprit mcp in %s: %v\n%s", container, err, stderr.String())
		}
	})
	return newMCPClient(t, stdin, stdout)
}

// diagnoseThroughMCP is diagnose, as culprit_diagnose.
func (s *faultStack) diagnoseThroughMCP(symptom string, fault faultExpectation) model.Investigation {
	s.t.Helper()
	container := s.container(fault.Vantage)
	s.docker(nil, "exec", "-u", "0", container, "rm", "-rf", "/tmp/walk", containerState)
	s.copyBundle(container)
	client := s.mcpInContainer(container, fault.Vantage)
	result := client.call("culprit_diagnose", map[string]any{"symptom": symptom, "environment": fault.Environment})
	s.noSecretIn("culprit_diagnose", result.Structured)
	if result.IsError {
		s.t.Fatalf("culprit_diagnose: %s", result.Structured)
	}
	got := structured[mcpDiagnosis](s.t, result)
	if got.Verify.Tool != "culprit_verify" || got.Verify.Arguments["investigation_id"] != got.Investigation.ID {
		s.t.Errorf("culprit_diagnose does not say how to verify: %+v", got.Verify)
	}
	return got.Investigation
}

// verifyThroughMCP is verify, as culprit_verify, in a new session.
func (s *faultStack) verifyThroughMCP(fault faultExpectation, inv model.Investigation, state string, changes []string) model.Verification {
	s.t.Helper()
	container := s.restoreForVerify(fault, state)
	client := s.mcpInContainer(container, fault.Vantage)
	result := client.call("culprit_verify", map[string]any{"investigation_id": inv.ID, "changes": changes})
	s.noSecretIn("culprit_verify", result.Structured)
	if result.IsError {
		s.t.Fatalf("culprit_verify: %s", result.Structured)
	}
	return structured[model.Verification](s.t, result)
}

func (s *faultStack) noSecretIn(tool string, answer []byte) {
	for _, secret := range s.secrets {
		if strings.Contains(string(answer), secret) {
			s.t.Errorf("a token or its secret appears in what %s answered", tool)
		}
	}
}

// checkVerification: the verdict wanted, and the full reading set measured
// again — exactly the investigation's readings, each twice, none reused.
func (s *faultStack) checkVerification(verification model.Verification, inv model.Investigation, want, says string) {
	t := s.t
	t.Helper()
	t.Logf("verify: %s, %d readings re-run twice: %s", verification.Verdict, len(verification.Reran), verification.Reason)
	if says != "" && !strings.Contains(verification.Reason, says) {
		t.Errorf("the reason does not say %q: %s", says, verification.Reason)
	}
	// Read by a person: subjects in words, no arrow pair, no plan phase.
	if strings.Contains(verification.Reason, "->") || phaseNumber.MatchString(verification.Reason) {
		t.Errorf("the reason is not written for a person: %s", verification.Reason)
	}
	if err := verification.Validate(); err != nil {
		t.Fatalf("the verification does not validate: %v", err)
	}
	if verification.InvestigationID != inv.ID {
		t.Errorf("verification of %s, want %s", verification.InvestigationID, inv.ID)
	}
	if len(verification.Reran) != len(inv.Readings) {
		t.Errorf("%d readings re-run for an investigation of %d", len(verification.Reran), len(inv.Readings))
	}
	for index, rerun := range verification.Reran {
		if index < len(inv.Readings) && rerun.ReadingID != inv.Readings[index].ID {
			t.Errorf("re-run %d is of %s, want %s", index, rerun.ReadingID, inv.Readings[index].ID)
		}
		for _, run := range rerun.Runs {
			if inv.ClosedAt != nil && !run.TakenAt.After(*inv.ClosedAt) {
				t.Errorf("re-run of %s holds a reading taken before the investigation closed", rerun.ReadingID)
			}
		}
	}
	if string(verification.Verdict) != want {
		t.Errorf("verdict %s, want %s\nreason: %s", verification.Verdict, want, verification.Reason)
	}
	if t.Failed() {
		encoded, _ := json.MarshalIndent(verification, "", "  ")
		t.Logf("verification:\n%s", encoded)
	}
}

// declaredIsolated says the demo's culprit.yaml declares environment
// `isolated: true`.
func declaredIsolated(t *testing.T, environment string) bool {
	t.Helper()
	manifest, err := extract.LoadManifest(demoManifest)
	if err != nil {
		t.Fatalf("the demo's culprit.yaml: %v", err)
	}
	return manifest.Environments[environment].Isolated
}

// routeBudgetMs is the latency_p95_ms the demo's culprit.yaml declares on
// subject, read from the file so the harness cannot drift from it.
func routeBudgetMs(t *testing.T, subject string) float64 {
	t.Helper()
	manifest, err := extract.LoadManifest(demoManifest)
	if err != nil {
		t.Fatalf("the demo's culprit.yaml: %v", err)
	}
	for _, budget := range manifest.Budgets {
		if budget.Subject == subject && budget.Predicate == "latency_p95_ms" {
			if value, ok := budget.Value.(int); ok {
				return float64(value)
			}
			if value, ok := budget.Value.(float64); ok {
				return value
			}
		}
	}
	t.Fatalf("the demo's culprit.yaml declares no latency_p95_ms on %s", subject)
	return 0
}

// pauseLoad stops the load generator: in an environment declared isolated,
// nothing but Culprit may talk to the database (Phase 39 part 2).
func (s *faultStack) pauseLoad() {
	s.t.Helper()
	s.compose(s.withToken(s.good), "stop", "load-generator")
}

// resumeLoad starts it again, for the cases after.
func (s *faultStack) resumeLoad() {
	s.t.Helper()
	s.compose(s.withToken(s.good), "start", "load-generator")
}

// listBound is the response_items_max the demo's culprit.yaml declares on
// subject.
func listBound(t *testing.T, subject string) int {
	t.Helper()
	manifest, err := extract.LoadManifest(demoManifest)
	if err != nil {
		t.Fatalf("the demo's culprit.yaml: %v", err)
	}
	for _, budget := range manifest.Budgets {
		if budget.Subject == subject && budget.Predicate == "response_items_max" {
			if value, ok := budget.Value.(int); ok {
				return value
			}
		}
	}
	t.Fatalf("the demo's culprit.yaml declares no response_items_max on %s", subject)
	return 0
}

// rebundle puts the walk bundle back in the vantage container after a fix
// recreated it.
func (s *faultStack) rebundle(fault faultExpectation) {
	s.t.Helper()
	container := s.container(fault.Vantage)
	s.docker(nil, "exec", "-u", "0", container, "rm", "-rf", "/tmp/walk")
	s.copyBundle(container)
}

// warm sends n bare GETs to one of inventory-service's routes from inside
// it, after it was recreated, before anything is measured there. Harness,
// not a probe.
func (s *faultStack) warm(path string, n int) {
	s.t.Helper()
	script := "import urllib.request,sys\nfor _ in range(int(sys.argv[2])): " +
		"urllib.request.urlopen('http://localhost:8002'+sys.argv[1],timeout=15).read()"
	s.docker(nil, "exec", s.container("inventory-service"), "python", "-c", script, path, fmt.Sprint(n))
}
