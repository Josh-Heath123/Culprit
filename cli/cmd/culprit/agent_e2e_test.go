package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// TestTheAgentEndToEnd is Phase 33 part 2's scenario, run in CI against a
// real control plane (`just quickstart`, the e2e job) and the fault
// library's demo stack:
//
//   - the agent runs inside order-service, in the fault stack's own Compose
//     network, which it shares with nothing of the control plane's — it
//     reaches the API only through the address the host publishes;
//   - it is paired with a code an admin makes, and every task comes to it
//     through the API;
//   - an agent with the four network grants and config.read.names completes
//     a reachability investigation, and a schema one ends partial, naming
//     db.metadata.read;
//   - the audience fault, run by an agent holding config.inspect.values,
//     still roots at the audience;
//   - every probe a walk ran has exactly one row in agent_audit_log, and
//     every investigation records that an agent submitted it.
//
// Needs Docker and a running quickstart, so it runs only when
// CULPRIT_AGENT_E2E=1, with:
//
//	CULPRIT_E2E_BASE_URL           the dashboard, as the host reaches it
//	CULPRIT_E2E_USERNAME/PASSWORD  an admin
//	CULPRIT_AGENT_CONTROL_PLANE    the API root as a container reaches it
//	                               (http://host.docker.internal/api)
func TestTheAgentEndToEnd(t *testing.T) {
	if os.Getenv("CULPRIT_AGENT_E2E") != "1" {
		t.Skip("set CULPRIT_AGENT_E2E=1, with a running quickstart, to run the agent scenario")
	}
	base := strings.TrimRight(requireEnv(t, "CULPRIT_E2E_BASE_URL"), "/") + "/api"
	plane := requireEnv(t, "CULPRIT_AGENT_CONTROL_PLANE")
	admin := login(t, base, requireEnv(t, "CULPRIT_E2E_USERNAME"), requireEnv(t, "CULPRIT_E2E_PASSWORD"))

	stack := startFaultStack(t)
	stack.healthy()
	assertNoSharedNetwork(t, stack.container("order-service"))

	network := "      net.dns.resolve: true\n      net.tcp.connect: true\n" +
		"      net.http.outbound: true\n      net.tls.inspect: true\n      config.read.names: true\n"
	networkGrants := []string{"config.read.names", "net.dns.resolve", "net.http.outbound",
		"net.tcp.connect", "net.tls.inspect"}

	// Agent A: the network grants and config.read.names, over a model in
	// which order-service also reads a database.
	reach := newInContainerAgent(t, stack, base, admin, plane, "e2e-reach", network, withOrdersDatabase(t))
	reach.allow(t, networkGrants)

	restore := stack.inject("network-partition")
	partition := reach.diagnose(t, "POST http://order-service:8001/orders")
	restore()
	if partition["complete"] != true || partition["root_subject"] != "connection:order-service->inventory-service" {
		t.Errorf("the reachability investigation: complete=%v root=%v, want complete at the edge",
			partition["complete"], partition["root_subject"])
	}

	restore = stack.inject("latency")
	schema := reach.diagnose(t, "POST http://order-service:8001/orders")
	restore()
	if schema["complete"] == true || !strings.Contains(fmt.Sprint(schema["statement"]), "db.metadata.read") {
		t.Errorf("the schema investigation: complete=%v, statement %q; want partial, naming db.metadata.read",
			schema["complete"], schema["statement"])
	}

	// Agent B: the same, and config.inspect.values for the token it must
	// inspect, over the demo model as it is. The fault first: it recreates
	// order-service with the wrong token, which would take an agent already
	// installed in that container with it.
	restore = stack.inject("auth-audience")
	audience := newInContainerAgent(t, stack, base, admin, plane, "e2e-audience",
		network+"      config.inspect.values: [order-service/INVENTORY_TOKEN]\n", "")
	audience.allow(t, append([]string{"config.inspect.values"}, networkGrants...))
	rooted := audience.diagnose(t, "POST http://order-service:8001/orders")
	restore()
	if rooted["root_subject"] != "auth:order-service->inventory-service/audience" {
		t.Errorf("the audience investigation roots at %v", rooted["root_subject"])
	}

	for _, agent := range []*inContainerAgent{reach, audience} {
		agent.assertAuditMatchesReadings(t)
	}
}

// ---- the agent, inside order-service ---------------------------------------------

type inContainerAgent struct {
	stack     *faultStack
	base      string
	admin     string
	id        string
	dir       string
	container string
	tasks     []string
	readings  map[string]int // task id -> readings its investigation holds
}

func newInContainerAgent(t *testing.T, stack *faultStack, base, admin, plane, id, grants, manifest string) *inContainerAgent {
	t.Helper()
	container := stack.container("order-service")
	dir := "/tmp/" + id
	agent := &inContainerAgent{stack: stack, base: base, admin: admin, id: id + "-" + randomHex(t)[:6],
		dir: dir, container: container, readings: map[string]int{}}
	stack.docker(nil, "exec", "-u", "0", container, "mkdir", "-p", dir)
	stack.docker(nil, "cp", filepath.Join(stack.walkIn, "culprit"), container+":"+dir+"/culprit")
	if manifest == "" {
		stack.docker(nil, "cp", filepath.Join(stack.walkIn, "culprit.yaml"), container+":"+dir+"/culprit.yaml")
	} else {
		stack.docker(nil, "cp", manifest, container+":"+dir+"/culprit.yaml")
	}
	config := filepath.Join(t.TempDir(), "agent.yaml")
	// allow_plain_http: CI's quickstart serves plain http, and the agent
	// reaches it as host.docker.internal, which is not loopback. This test's
	// configuration is not a shipped recipe; no recipe sets it (Phase 33
	// part 3, deploy/agent/).
	text := fmt.Sprintf("version: 1\nagent_id: %s\nmanifest: ./culprit.yaml\nkey: ./agent.key\n"+
		"control_plane:\n  url: %s\n  allow_plain_http: true\nenvironments:\n  faults-order:\n    grants:\n%s",
		agent.id, plane, grants)
	if err := os.WriteFile(config, []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
	stack.docker(nil, "cp", config, container+":"+dir+"/agent.yaml")
	stack.docker(nil, "exec", "-u", "0", container, "chmod", "-R", "a+rwX", dir)

	agent.run(t, "agent", "init", "--config", dir+"/agent.yaml")
	code := adminCall(t, http.MethodPost, base+"/agents/pairing-codes", admin, nil, http.StatusCreated)["code"]
	agent.run(t, "agent", "pair", "--config", dir+"/agent.yaml", "--code", fmt.Sprint(code))
	return agent
}

func (a *inContainerAgent) run(t *testing.T, args ...string) string {
	t.Helper()
	command := exec.Command("docker", append([]string{"exec", a.container, a.dir + "/culprit"}, args...)...)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("culprit %s in %s: %v\n%s", strings.Join(args, " "), a.container, err, output)
	}
	return string(output)
}

func (a *inContainerAgent) allow(t *testing.T, grants []string) {
	t.Helper()
	adminCall(t, http.MethodPatch, a.base+"/agents/"+a.id+"/grants", a.admin,
		map[string]any{"environment": "faults-order", "grants": grants}, http.StatusOK)
}

// diagnose addresses a walk to the agent, lets it run, and returns the
// stored investigation's summary and diagnosis.
func (a *inContainerAgent) diagnose(t *testing.T, symptom string) map[string]any {
	t.Helper()
	created := adminCall(t, http.MethodPost, a.base+"/agents/"+a.id+"/tasks", a.admin, map[string]any{
		"environment": "faults-order", "kind": "diagnose",
		"diagnose": map[string]any{"symptom": symptom, "from": "order-service"},
	}, http.StatusCreated)
	task := fmt.Sprint(created["id"])
	a.tasks = append(a.tasks, task)
	a.run(t, "agent", "--config", a.dir+"/agent.yaml", "--audit", a.dir+"/audit.log", "--once")

	result := adminCall(t, http.MethodGet, a.base+"/agents/"+a.id+"/tasks/"+task, a.admin, nil, http.StatusOK)
	investigation := fmt.Sprint(result["investigation_id"])
	if result["completed_at"] == nil || investigation == "" || investigation == "<nil>" {
		t.Fatalf("task %s did not complete with an investigation: %v", task, result)
	}
	stored := adminCall(t, http.MethodGet, a.base+"/investigations/"+investigation, a.admin, nil, http.StatusOK)
	readings, _ := stored["readings"].([]any)
	a.readings[task] = len(readings)

	listed := adminCall(t, http.MethodGet, a.base+"/investigations?limit=200", a.admin, nil, http.StatusOK)
	items, _ := listed["items"].([]any)
	for _, item := range items {
		summary := item.(map[string]any)
		if summary["id"] == investigation && summary["submitted_by"] != "agent:"+a.id {
			t.Errorf("investigation %s was submitted by %v, want agent:%s", investigation, summary["submitted_by"], a.id)
		}
	}
	diagnosis, _ := stored["diagnosis"].(map[string]any)
	return map[string]any{
		"complete": diagnosis["complete"], "root_subject": diagnosis["root_subject"],
		"statement": diagnosis["statement"],
	}
}

// Every probe a walk ran has exactly one agent_audit_log row.
func (a *inContainerAgent) assertAuditMatchesReadings(t *testing.T) {
	t.Helper()
	log := adminCall(t, http.MethodGet, a.base+"/agents/"+a.id+"/audit", a.admin, nil, http.StatusOK)
	rows, _ := log["items"].([]any)
	probes := map[string]int{}
	tasks := 0
	for _, raw := range rows {
		row := raw.(map[string]any)
		switch row["kind"] {
		case "probe":
			probes[fmt.Sprint(row["task_id"])]++
		case "task":
			tasks++
		}
	}
	if tasks != len(a.tasks) {
		t.Errorf("agent %s: %d task entries, want %d", a.id, tasks, len(a.tasks))
	}
	// Task by task: one probe row for every reading that task's
	// investigation holds, and none for a task that ran nothing.
	for _, task := range a.tasks {
		if probes[task] != a.readings[task] || a.readings[task] == 0 {
			t.Errorf("agent %s, task %s: %d probe rows in agent_audit_log for %d readings",
				a.id, task, probes[task], a.readings[task])
		}
	}
	for task := range probes {
		if _, ours := a.readings[task]; !ours {
			t.Errorf("agent %s: probe rows for a task it was not given: %s", a.id, task)
		}
	}
}

// ---- the topology ---------------------------------------------------------------------

func assertNoSharedNetwork(t *testing.T, agentContainer string) {
	t.Helper()
	networksOf := func(container string) map[string]bool {
		output, err := exec.Command("docker", "inspect", "--format",
			"{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}", container).Output()
		if err != nil {
			t.Fatalf("docker inspect %s: %v", container, err)
		}
		set := map[string]bool{}
		for _, name := range strings.Fields(string(output)) {
			set[name] = true
		}
		return set
	}
	// Every running container outside the fault stack is the control
	// plane's (the quickstart): the agent shares a network with none.
	listing, err := exec.Command("docker", "ps", "--format", "{{.Names}}").Output()
	if err != nil {
		t.Fatal(err)
	}
	agent := networksOf(agentContainer)
	checked := 0
	for _, name := range strings.Fields(string(listing)) {
		if strings.HasPrefix(name, faultProject) {
			continue
		}
		checked++
		for network := range networksOf(name) {
			if agent[network] {
				t.Errorf("the agent's container shares the network %s with the control plane's %s", network, name)
			}
		}
	}
	if checked == 0 {
		t.Fatal("no control-plane container found to compare networks with")
	}
}

// withOrdersDatabase is the demo model with a database order-service
// reads: the schema walk's boundary then holds a database hypothesis only
// db.metadata.read can test.
func withOrdersDatabase(t *testing.T) string {
	t.Helper()
	model, err := os.ReadFile(demoManifest)
	if err != nil {
		t.Fatal(err)
	}
	text := string(model)
	edge := "      - to: payments-service\n        kind: http\n        criticality: on_request_path\n"
	if strings.Count(text, edge) < 1 {
		t.Fatal("the demo model's order-service connections have moved; update this fixture")
	}
	text = strings.Replace(text, edge, edge+"      - to: orders-db\n        kind: sql\n        criticality: on_request_path\n", 1)
	text = strings.Replace(text, "\n  - name: inventory-service\n",
		"\n  - name: orders-db\n    kind: database\n\n  - name: inventory-service\n", 1)
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

// ---- the API, as an admin ----------------------------------------------------------------

func requireEnv(t *testing.T, name string) string {
	t.Helper()
	value := os.Getenv(name)
	if value == "" {
		t.Fatalf("%s is not set", name)
	}
	return value
}

func login(t *testing.T, base, username, password string) string {
	t.Helper()
	body, _ := json.Marshal(map[string]string{"username": username, "password": password})
	response, err := http.Post(base+"/auth/login", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	var token struct {
		AccessToken string `json:"access_token"`
	}
	if response.StatusCode != http.StatusOK || json.NewDecoder(response.Body).Decode(&token) != nil {
		t.Fatalf("admin login: %d", response.StatusCode)
	}
	return token.AccessToken
}

func adminCall(t *testing.T, method, url, token string, payload any, want int) map[string]any {
	t.Helper()
	var body io.Reader
	if payload != nil {
		encoded, _ := json.Marshal(payload)
		body = bytes.NewReader(encoded)
	}
	request, _ := http.NewRequest(method, url, body)
	request.Header.Set("Authorization", "Bearer "+token)
	if payload != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	client := &http.Client{Timeout: 30 * time.Second}
	response, err := client.Do(request)
	if err != nil {
		t.Fatalf("%s %s: %v", method, url, err)
	}
	defer response.Body.Close()
	read, _ := io.ReadAll(response.Body)
	if response.StatusCode != want {
		t.Fatalf("%s %s: %d, want %d: %s", method, url, response.StatusCode, want, read)
	}
	decoded := map[string]any{}
	if len(read) > 0 {
		_ = json.Unmarshal(read, &decoded)
	}
	return decoded
}
