package main

import (
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
	"runtime"
	"sort"
	"strings"
	"testing"
	"time"

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
}

type faultLibrary struct {
	Symptom string             `json:"symptom"`
	Faults  []faultExpectation `json:"faults"`
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

	stack := startFaultStack(t)
	for _, fault := range library.Faults {
		t.Run(fault.Name, func(t *testing.T) {
			stack.t = t
			stack.healthy()
			// The symptom is real before the walk is asked about it: the
			// order succeeds on the healthy stack and fails under the fault
			// (latency slows it down without failing it). Harness, not a
			// probe — a probe never writes.
			if status := stack.placeOrder(); status != 201 {
				t.Fatalf("POST /orders on the healthy stack answered %d, want 201", status)
			}
			restore := stack.inject(fault.Name)
			defer restore()
			status := stack.placeOrder()
			if fault.Name == "latency" {
				if status != 201 {
					t.Fatalf("POST /orders under added latency answered %d, want 201", status)
				}
			} else if status < 500 {
				t.Fatalf("POST /orders under the fault answered %d; the fault is not real", status)
			}

			inv := stack.diagnose(library.Symptom, fault)
			checkDiagnosis(t, fault, inv)
		})
	}
}

func checkDiagnosis(t *testing.T, want faultExpectation, inv model.Investigation) {
	t.Helper()
	if err := inv.Validate(); err != nil {
		t.Fatalf("the investigation does not validate: %v", err)
	}
	d := inv.Diagnosis
	if d == nil {
		t.Fatal("no diagnosis")
	}
	if d.RootSubject != want.RootSubject {
		t.Errorf("root %s, want %s\nstatement: %s", d.RootSubject, want.RootSubject, d.Statement)
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

func (s *faultStack) healthy() {
	s.compose(s.withToken(s.good), "up", "-d", "--force-recreate")
	s.waitFor("order-service", "http://inventory-service:8002/ready", "http://payments-service:8003/ready",
		"http://order-service:8001/health")
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
	case "auth-audience":
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
		s.compose(s.withToken(s.good, "CONTRACT_FAULT=stock-route-renamed"), "up", "-d", "--force-recreate", "inventory-service")
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
	s.docker(nil, "cp", s.walkIn, container+":/tmp/walk")
	s.docker(nil, "exec", "-u", "0", container, "chmod", "755", "/tmp/walk/culprit")
	command := exec.Command("docker", "exec", container, "/tmp/walk/culprit", "diagnose", symptom,
		"-f", "/tmp/walk/culprit.yaml", "--env", fault.Environment, "--from", fault.Vantage,
		"--no-plugins", "--format", "json", "--agent-id", "fault-library")
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
		"-f", "/tmp/walk/culprit.yaml", "--env", fault.Environment, "--from", fault.Vantage,
		"--no-plugins", "--format", "text").Output()
	for _, secret := range s.secrets {
		for format, printed := range map[string][]byte{"json": output, "text": text} {
			if strings.Contains(string(printed), secret) {
				s.t.Errorf("a token or its secret appears in the %s investigation", format)
			}
		}
	}
	return inv
}

// buildWalkBundle cross-compiles the binary for the containers and puts it
// beside the demo's culprit.yaml, in a directory of its own so extraction
// scans nothing else.
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
	manifest, err := os.ReadFile(demoManifest)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "culprit.yaml"), manifest, 0o644); err != nil {
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
