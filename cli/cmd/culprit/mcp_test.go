package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/capability"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Phase 35 part 1: `culprit mcp`, driven the way a coding agent drives it —
// a scripted MCP client, one JSON-RPC message per line, over a pair of
// streams. The same client drives the real binary over stdio in the fault
// library (faultlib_test.go).

// mcpClient is a scripted MCP client over any pair of streams.
type mcpClient struct {
	t      *testing.T
	in     io.Writer
	out    *bufio.Reader
	nextID int
}

func newMCPClient(t *testing.T, in io.Writer, out io.Reader) *mcpClient {
	t.Helper()
	client := &mcpClient{t: t, in: in, out: bufio.NewReaderSize(out, 1<<20)}
	reply := client.request("initialize", map[string]any{
		"protocolVersion": "2025-06-18", "capabilities": map[string]any{},
		"clientInfo": map[string]any{"name": "culprit-test", "version": "0"},
	})
	if reply.Error != nil {
		t.Fatalf("initialize: %+v", reply.Error)
	}
	client.send(map[string]any{"jsonrpc": "2.0", "method": "notifications/initialized"})
	return client
}

type mcpReply struct {
	ID     int             `json:"id"`
	Result json.RawMessage `json:"result"`
	Error  *struct {
		Code    int    `json:"code"`
		Message string `json:"message"`
	} `json:"error"`
}

type mcpCallResult struct {
	Content []struct {
		Type string `json:"type"`
		Text string `json:"text"`
	} `json:"content"`
	Structured json.RawMessage `json:"structuredContent"`
	IsError    bool            `json:"isError"`
}

func (c *mcpClient) send(message map[string]any) {
	c.t.Helper()
	encoded, err := json.Marshal(message)
	if err != nil {
		c.t.Fatal(err)
	}
	if _, err := c.in.Write(append(encoded, '\n')); err != nil {
		c.t.Fatalf("writing to the server: %v", err)
	}
}

func (c *mcpClient) request(method string, params any) mcpReply {
	c.t.Helper()
	c.nextID++
	c.send(map[string]any{"jsonrpc": "2.0", "id": c.nextID, "method": method, "params": params})
	line, err := c.out.ReadBytes('\n')
	if err != nil {
		c.t.Fatalf("%s: no reply: %v (%s)", method, err, line)
	}
	var reply mcpReply
	if err := json.Unmarshal(line, &reply); err != nil {
		c.t.Fatalf("%s: the reply is not one JSON-RPC message on one line: %v\n%s", method, err, line)
	}
	if reply.ID != c.nextID {
		c.t.Fatalf("%s: reply to %d, want %d", method, reply.ID, c.nextID)
	}
	return reply
}

// call calls a tool and returns its result, failing on a protocol error.
func (c *mcpClient) call(name string, arguments map[string]any) mcpCallResult {
	c.t.Helper()
	reply := c.request("tools/call", map[string]any{"name": name, "arguments": arguments})
	if reply.Error != nil {
		c.t.Fatalf("%s: protocol error %d: %s", name, reply.Error.Code, reply.Error.Message)
	}
	var result mcpCallResult
	if err := json.Unmarshal(reply.Result, &result); err != nil {
		c.t.Fatalf("%s: %v", name, err)
	}
	// The text content is the structured result as JSON, nothing else.
	if len(result.Content) != 1 || result.Content[0].Type != "text" ||
		!jsonEqual(c.t, []byte(result.Content[0].Text), result.Structured) {
		c.t.Errorf("%s: the text content is not the structured result: %+v", name, result.Content)
	}
	return result
}

func jsonEqual(t *testing.T, a, b []byte) bool {
	t.Helper()
	var left, right any
	if json.Unmarshal(a, &left) != nil || json.Unmarshal(b, &right) != nil {
		return false
	}
	l, _ := json.Marshal(left)
	r, _ := json.Marshal(right)
	return bytes.Equal(l, r)
}

// mcpSession runs a server in-process on a pair of pipes until the test
// ends.
func mcpSession(t *testing.T, server *mcpServer) *mcpClient {
	t.Helper()
	inReader, inWriter := io.Pipe()
	outReader, outWriter := io.Pipe()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		err := server.protocol().Run(ctx, inReader, outWriter)
		_ = outWriter.Close()
		done <- err
	}()
	t.Cleanup(func() {
		_ = inWriter.Close()
		cancel()
		if err := <-done; err != nil && err != context.Canceled {
			t.Errorf("the server stopped with %v", err)
		}
	})
	return newMCPClient(t, inWriter, outReader)
}

// mcpCommandSession runs the real command — flags, manifest resolution
// and all — in-process, its stdin and stdout a pair of pipes.
func mcpCommandSession(t *testing.T, arguments ...string) *mcpClient {
	t.Helper()
	inReader, inWriter := io.Pipe()
	outReader, outWriter := io.Pipe()
	command := newRootCommand()
	command.SetIn(inReader)
	command.SetOut(outWriter)
	var stderr bytes.Buffer
	command.SetErr(&stderr)
	command.SetArgs(append([]string{"mcp"}, arguments...))
	done := make(chan error, 1)
	go func() {
		err := command.Execute()
		_ = outWriter.Close()
		done <- err
	}()
	t.Cleanup(func() {
		_ = inWriter.Close()
		if err := <-done; err != nil {
			t.Errorf("culprit mcp: %v\n%s", err, stderr.String())
		}
	})
	return newMCPClient(t, inWriter, outReader)
}

func structured[T any](t *testing.T, result mcpCallResult) T {
	t.Helper()
	var value T
	decoder := json.NewDecoder(bytes.NewReader(result.Structured))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&value); err != nil {
		t.Fatalf("the result is not a %T: %v\n%s", value, err, result.Structured)
	}
	return value
}

type mcpDiagnosis struct {
	Investigation model.Investigation `json:"investigation"`
	Verify        struct {
		Tool        string         `json:"tool"`
		Arguments   map[string]any `json:"arguments"`
		ChangeKinds []changeKind   `json:"change_kinds"`
	} `json:"verify"`
}

// TestTheLoopThroughMCP is the first criterion in-process, against the
// loop fixture's real server: culprit_diagnose returns the rooted tree and
// how to verify; the fix is applied; culprit_verify returns verified — and
// with no fix, not_resolved. Through the real command, over its stdin and
// stdout. LLM_PROVIDER=none: nothing needs a model.
func TestTheLoopThroughMCP(t *testing.T) {
	t.Setenv("LLM_PROVIDER", "none")
	for _, fixed := range []bool{true, false} {
		name := map[bool]string{true: "the right fix is verified", false: "no fix is not_resolved"}[fixed]
		t.Run(name, func(t *testing.T) {
			loop, server := newLoop(t)
			client := mcpCommandSession(t, "-f", loop.manifest, "--from", "web", "--no-plugins", "--state-dir", loop.state)

			result := client.call("culprit_diagnose", map[string]any{"symptom": "web", "environment": "local"})
			if result.IsError {
				t.Fatalf("culprit_diagnose: %s", result.Structured)
			}
			got := structured[mcpDiagnosis](t, result)
			inv := got.Investigation
			if err := inv.Validate(); err != nil {
				t.Fatalf("the investigation does not validate: %v", err)
			}
			if inv.Diagnosis == nil || !inv.Diagnosis.Complete || inv.Diagnosis.RootSubject != "http:api/GET /orders" {
				t.Fatalf("not rooted at the contract fault: %+v", inv.Diagnosis)
			}
			if len(inv.FaultTree) == 0 || len(inv.Readings) == 0 {
				t.Fatalf("no fault tree or no readings: %+v", inv)
			}
			if got.Verify.Tool != "culprit_verify" || got.Verify.Arguments["investigation_id"] != inv.ID ||
				len(got.Verify.ChangeKinds) != 4 {
				t.Errorf("does not say how to verify: %+v", got.Verify)
			}
			if reason := inv.Diagnosis.Confidence.Verified.Reason; !strings.Contains(reason, "culprit_verify with investigation_id "+inv.ID) {
				t.Errorf("the rubric's verified does not say how to verify through MCP: %s", reason)
			}

			want := model.VerificationNotResolved
			if fixed {
				server.ordersServed.Store(true)
				want = model.VerificationVerified
			}
			result = client.call("culprit_verify", map[string]any{
				"investigation_id": inv.ID, "changes": []string{"action:served GET /orders again"},
			})
			if result.IsError {
				t.Fatalf("culprit_verify: %s", result.Structured)
			}
			verification := structured[model.Verification](t, result)
			if err := verification.Validate(); err != nil {
				t.Fatalf("the verification does not validate: %v", err)
			}
			if verification.Verdict != want || verification.InvestigationID != inv.ID {
				t.Fatalf("verdict %s for %s, want %s: %s", verification.Verdict, verification.InvestigationID, want, verification.Reason)
			}
		})
	}
}

// TestNoArgumentAcquiresACapability: a call whose arguments name a grant,
// or that asks for a probe the environment does not grant, is refused
// before anything is dialled — counted on a network that answers
// everything.
func TestNoArgumentAcquiresACapability(t *testing.T) {
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(agentManifest), 0o600); err != nil {
		t.Fatal(err)
	}
	network, http := &countingNetwork{}, &countingHTTP{}
	client := mcpSession(t, &mcpServer{
		manifestPath: path, stateDir: t.TempDir(), agentID: "test", noPlugins: true,
		through: &wire{Network: network, HTTP: http}, stderr: io.Discard,
	})
	connection := "connection:orders->payments"

	refusedByTheProtocol := []struct {
		tool      string
		arguments map[string]any
	}{
		{"culprit_probe", map[string]any{"target": connection, "environment": "production",
			"probes": []string{"probe.net.tcp_connect"}, "grants": map[string]any{"net.tcp.connect": true}}},
		{"culprit_probe", map[string]any{"target": connection, "environment": "production",
			"probes": []string{"probe.net.tcp_connect"}, "net.tcp.connect": true}},
		{"culprit_diagnose", map[string]any{"symptom": "orders", "environment": "production",
			"capabilities": []string{"net.http.outbound"}}},
		{"culprit_verify", map[string]any{"investigation_id": "inv-0000000000000000", "grants": []string{"config.inspect.values"}}},
		{"culprit_check", map[string]any{"grant": "process.exec"}},
	}
	for _, refused := range refusedByTheProtocol {
		reply := client.request("tools/call", map[string]any{"name": refused.tool, "arguments": refused.arguments})
		if reply.Error == nil || !strings.Contains(reply.Error.Message, "no argument can add one") {
			t.Errorf("%s %v: not refused: %+v %s", refused.tool, refused.arguments, reply.Error, reply.Result)
		}
	}

	refusedByTheTool := []map[string]any{
		// An input that names a grant.
		{"target": connection, "environment": "production", "probes": []string{"probe.net.tcp_connect"},
			"inputs": map[string]any{"host": "payments.internal", "port": 8443, "grants": []string{"net.tcp.connect"}}},
		{"target": connection, "environment": "production", "probes": []string{"probe.net.tcp_connect"},
			"inputs": map[string]any{"host": "payments.internal", "port": 8443, "net.tls.inspect": true}},
		// A probe production does not grant: net.tls.inspect is withheld.
		{"target": connection, "environment": "production", "probes": []string{"probe.net.tls_validity"},
			"inputs": map[string]any{"host": "payments.internal", "port": 8443}},
		// One ungranted probe refuses the whole call, the granted one too.
		{"target": connection, "environment": "production",
			"probes": []string{"probe.net.tcp_connect", "probe.net.tls_validity"},
			"inputs": map[string]any{"host": "payments.internal", "port": 8443}},
	}
	for _, arguments := range refusedByTheTool {
		result := client.call("culprit_probe", arguments)
		if !result.IsError || !strings.Contains(string(result.Structured), "refused") {
			t.Errorf("%v: not refused: %s", arguments, result.Structured)
		}
	}
	if dials, requests := network.dials.Load()+network.resolves.Load(), http.requests.Load(); dials != 0 || requests != 0 {
		t.Fatalf("%d dial(s) and %d request(s) for calls that were all refused", dials, requests)
	}

	// The control: the same call, granted, does dial — the counter is
	// connected to what the tool reaches the network through.
	result := client.call("culprit_probe", map[string]any{"target": connection, "environment": "production",
		"probes": []string{"probe.net.tcp_connect"}, "inputs": map[string]any{"host": "payments.internal", "port": 8443}})
	if result.IsError {
		t.Fatalf("the granted probe was refused: %s", result.Structured)
	}
	if dials := network.dials.Load(); dials != 1 {
		t.Fatalf("%d dials for one granted tcp_connect, want 1", dials)
	}
}

// TestAProbeReachesOnlyDeclaredEndpoints (Q23): through culprit mcp an
// address input — url, base_url, host, port — that is not an endpoint the
// environment declares is refused before anything is dialled, counted on
// a network that answers everything. production declares one endpoint,
// payments.internal:8443, and grants dns, tcp and http.
func TestAProbeReachesOnlyDeclaredEndpoints(t *testing.T) {
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(agentManifest), 0o600); err != nil {
		t.Fatal(err)
	}
	network, http := &countingNetwork{}, &countingHTTP{}
	client := mcpSession(t, &mcpServer{
		manifestPath: path, stateDir: t.TempDir(), agentID: "test", noPlugins: true,
		through: &wire{Network: network, HTTP: http}, stderr: io.Discard,
	})
	call := func(probeID string, inputs map[string]any) mcpCallResult {
		return client.call("culprit_probe", map[string]any{"target": "connection:orders->payments",
			"environment": "production", "probes": []string{probeID}, "inputs": inputs})
	}
	refused := []struct {
		probe  string
		inputs map[string]any
	}{
		// The instance metadata service, by host and by URL.
		{"probe.net.tcp_connect", map[string]any{"host": "169.254.169.254", "port": 80}},
		{"probe.net.dns_resolve", map[string]any{"host": "169.254.169.254"}},
		{"probe.http.reachable", map[string]any{"url": "http://169.254.169.254/latest/meta-data/"}},
		// An undeclared host, on the declared port.
		{"probe.net.tcp_connect", map[string]any{"host": "db.internal", "port": 8443}},
		{"probe.http.reachable", map[string]any{"url": "http://db.internal:8443/health"}},
		// An undeclared port on the declared host.
		{"probe.net.tcp_connect", map[string]any{"host": "payments.internal", "port": 22}},
		{"probe.net.tcp_connect", map[string]any{"host": "payments.internal", "port": "22"}},
		{"probe.http.reachable", map[string]any{"url": "http://payments.internal/health"}},
		{"probe.http.route_conformance", map[string]any{"base_url": "https://payments.internal:9000"}},
		// Disguises: credentials before the host, a port with no host, a
		// scheme that is not http.
		{"probe.http.reachable", map[string]any{"url": "http://payments.internal:8443@169.254.169.254/"}},
		{"probe.net.tcp_connect", map[string]any{"port": 8443}},
		{"probe.http.reachable", map[string]any{"url": "file:///etc/passwd"}},
		// The declared host written another way: an absolute name, or with
		// a space, is not compared as the declared one (it may be another
		// machine), so it is refused rather than normalised.
		{"probe.net.tcp_connect", map[string]any{"host": "payments.internal.", "port": 8443}},
		{"probe.net.tcp_connect", map[string]any{"host": " payments.internal", "port": 8443}},
		{"probe.http.reachable", map[string]any{"url": "http://payments.internal.:8443/health"}},
	}
	for _, c := range refused {
		result := call(c.probe, c.inputs)
		if !result.IsError || !strings.Contains(string(result.Structured), "unbound") {
			t.Errorf("%s %v: not refused: %s", c.probe, c.inputs, result.Structured)
		}
	}
	if dials, requests := network.dials.Load()+network.resolves.Load(), http.requests.Load(); dials != 0 || requests != 0 {
		t.Fatalf("%d dial(s) and %d request(s) for calls that were all refused", dials, requests)
	}

	// The declared endpoint dials once, by host and port and by URL, and
	// the host is compared without regard to case.
	if result := call("probe.net.tcp_connect", map[string]any{"host": "Payments.Internal", "port": 8443}); result.IsError {
		t.Fatalf("the declared endpoint was refused: %s", result.Structured)
	}
	if dials := network.dials.Load(); dials != 1 {
		t.Fatalf("%d dials for one tcp_connect to the declared endpoint, want 1", dials)
	}
	if result := call("probe.http.reachable", map[string]any{"url": "http://payments.internal:8443/health"}); result.IsError {
		t.Fatalf("the declared endpoint's URL was refused: %s", result.Structured)
	}
	if requests := http.requests.Load(); requests != 1 {
		t.Fatalf("%d requests for one reachable to the declared endpoint, want 1", requests)
	}
}

// TestARedirectIsBoundAsTheAddressIs: a declared endpoint that answers
// 302 does not carry culprit_probe to an address the environment does not
// declare — the undeclared server is never reached — while a redirect to
// a declared endpoint is followed. Real sockets, on loopback.
func TestARedirectIsBoundAsTheAddressIs(t *testing.T) {
	var undeclaredHits atomic.Int64
	undeclared := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		undeclaredHits.Add(1)
		w.WriteHeader(http.StatusOK)
	}))
	defer undeclared.Close()
	var declared *httptest.Server
	declared = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/away":
			http.Redirect(w, r, undeclared.URL+"/latest/meta-data/", http.StatusFound)
		case "/home":
			http.Redirect(w, r, declared.URL+"/ok", http.StatusFound)
		default:
			w.WriteHeader(http.StatusOK)
		}
	}))
	defer declared.Close()
	port := declared.Listener.Addr().(*net.TCPAddr).Port
	manifest := fmt.Sprintf(`version: 1
components:
  - name: web
    kind: service
environments:
  local:
    adapter: process
    components:
      web: {}
    endpoints:
      web: { host: 127.0.0.1, port: %d }
    grants:
      net.http.outbound: true
`, port)
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(manifest), 0o600); err != nil {
		t.Fatal(err)
	}
	// No wire handed in: the server builds the real one, bound.
	client := mcpSession(t, &mcpServer{
		manifestPath: path, stateDir: t.TempDir(), agentID: "test", noPlugins: true,
		timeout: 5 * time.Second, stderr: io.Discard,
	})
	reach := func(path string) model.Reading {
		result := client.call("culprit_probe", map[string]any{"target": "component:web", "environment": "local",
			"probes": []string{"probe.http.reachable"},
			"inputs": map[string]any{"url": fmt.Sprintf("http://127.0.0.1:%d%s", port, path)}})
		var probed struct {
			Readings []model.Reading `json:"readings"`
		}
		if err := json.Unmarshal(result.Structured, &probed); err != nil || result.IsError || len(probed.Readings) != 1 {
			t.Fatalf("%s: %v %s", path, err, result.Structured)
		}
		return probed.Readings[0]
	}
	if reading := reach("/away"); reading.Verdict == model.VerdictPass {
		t.Errorf("a redirect off the declared endpoints was followed: %+v", reading)
	}
	if hits := undeclaredHits.Load(); hits != 0 {
		t.Fatalf("the undeclared server was reached %d time(s) through a redirect", hits)
	}
	if reading := reach("/home"); reading.Verdict != model.VerdictPass {
		t.Errorf("a redirect to the declared endpoint was not followed: %+v", reading)
	}
}

// TestEveryCatalogueInputIsClassified: the binding holds four input names
// (url, base_url, host, port). It covers every address only while no probe
// takes an address under another name, so every input name in the
// catalogue is listed here as one of those four or as not an address. A
// probe added with a new input name fails this until someone decides
// which it is — and binds it in unboundAddresses if it is an address.
func TestEveryCatalogueInputIsClassified(t *testing.T) {
	bound := map[string]bool{"url": true, "base_url": true, "host": true, "port": true}
	notAnAddress := map[string]bool{
		"method": true, "token": true, "token_env": true, "key": true, "package": true, "schema": true,
		"table": true, "expect_fields": true, "expect_columns": true, "expect_audience": true,
		"expect_issuer": true, "expect_version": true,
	}
	for _, manifest := range catalogue().Manifests() {
		properties, _ := manifest.Inputs["properties"].(map[string]any)
		for name := range properties {
			if !bound[name] && !notAnAddress[name] {
				t.Errorf("%s takes input %q, which is neither bound as an address nor listed as not one", manifest.ID, name)
			}
		}
	}
}

// TestCulpritProbeFromATerminalIsUnbound: the binding is culprit mcp's.
// runProbe — what `culprit probe` runs — still goes where its inputs say:
// a person at a terminal reaches nothing they could not reach with curl.
func TestCulpritProbeFromATerminalIsUnbound(t *testing.T) {
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(agentManifest), 0o600); err != nil {
		t.Fatal(err)
	}
	network := &countingNetwork{}
	readings, _, err := runProbe(context.Background(), probeInput{
		ManifestPath: path, Environment: "production", Target: "connection:orders->payments",
		ProbeIDs: []string{"probe.net.tcp_connect"}, Inputs: map[string]any{"host": "db.internal", "port": 22},
		AgentID: "test", NoPlugins: true, Timeout: 2 * time.Second,
		Through: &wire{Network: network, HTTP: &countingHTTP{}},
	})
	if err != nil || len(readings) != 1 || readings[0].Verdict != model.VerdictPass {
		t.Fatalf("culprit probe to an undeclared endpoint: %v %+v", err, readings)
	}
	if dials := network.dials.Load(); dials != 1 {
		t.Fatalf("%d dials, want 1", dials)
	}
}

// TestEveryToolAnswersInTheCLIsModel: each tool's structured result is the
// model its command's --format json prints, and validates as that model.
func TestEveryToolAnswersInTheCLIsModel(t *testing.T) {
	t.Setenv("SOURCE_DATE_EPOCH", "1767225600")
	loop, server := newLoop(t)
	client := mcpCommandSession(t, "-f", loop.manifest, "--from", "web", "--no-plugins", "--state-dir", loop.state)

	// culprit_check is culprit check --format json, byte for byte once
	// parsed.
	cli, _ := run(t, "check", "-f", loop.manifest, "--no-plugins", "--format", "json")
	result := client.call("culprit_check", map[string]any{})
	if result.IsError || !jsonEqual(t, []byte(cli), result.Structured) {
		t.Errorf("culprit_check differs from culprit check --format json:\n%s\n---\n%s", cli, result.Structured)
	}

	// culprit_system_model: its intent is the CaptureBundle culprit intent
	// prints, every fact valid; every subject built, so it parses back.
	got := structured[systemModel](t, client.call("culprit_system_model", map[string]any{}))
	for _, fact := range got.Intent.Facts {
		if err := fact.Validate(); err != nil {
			t.Errorf("a fact does not validate: %v", err)
		}
	}
	if len(got.Components) != 2 || len(got.Connections) != 1 || got.Connections[0].Subject != "connection:web->api" ||
		got.Vantage != "web" || len(got.Environments) != 2 {
		t.Errorf("system model: %+v", got)
	}
	for _, component := range got.Components {
		if _, _, err := model.ParseSubject(component.Subject); err != nil {
			t.Errorf("%s: %v", component.Subject, err)
		}
	}

	// culprit_explain_connection: facts that validate, divergences that are
	// culprit check's own entries, probe manifests from the catalogue.
	explained := structured[connectionExplanation](t, client.call("culprit_explain_connection",
		map[string]any{"from": "web", "to": "api", "environment": "blind"}))
	for _, fact := range explained.Facts {
		if err := fact.Validate(); err != nil {
			t.Errorf("a fact does not validate: %v", err)
		}
	}
	if len(explained.Probes) == 0 {
		t.Fatal("no probe can measure a connection")
	}
	for _, probe := range explained.Probes {
		manifest, ok := catalogue().Get(probe.ID)
		if !ok || probe.Granted == nil {
			t.Errorf("%s: not a catalogue probe, or no grant decision for a named environment", probe.ID)
			continue
		}
		if err := manifest.Manifest().Validate(); err != nil {
			t.Errorf("%s: %v", probe.ID, err)
		}
		// The entry returned is the catalogue's, not a copy that drifted.
		if strings.Join(probe.Capabilities, ",") != strings.Join(manifest.Manifest().Capabilities, ",") {
			t.Errorf("%s: capabilities %v, the catalogue says %v", probe.ID, probe.Capabilities, manifest.Manifest().Capabilities)
		}
		if missing := missingCapabilities(mustGrants(t, loop.manifest, "blind"), manifest.Manifest()); *probe.Granted != (len(missing) == 0) ||
			strings.Join(probe.Missing, ",") != strings.Join(missing, ",") {
			t.Errorf("%s: granted %v missing %v, the environment's grants say %v", probe.ID, *probe.Granted, probe.Missing, missing)
		}
	}

	// culprit_probe: culprit probe --format json's shape — readings that
	// validate, and the refusals beside them.
	result = client.call("culprit_probe", map[string]any{"target": "component:api", "environment": "local",
		"probes": []string{"probe.http.reachable"},
		"inputs": map[string]any{"url": fmt.Sprintf("http://127.0.0.1:%d/health", loop.port(t))}})
	var probed struct {
		Readings []model.Reading `json:"readings"`
		Refused  []model.Refusal `json:"refused"`
	}
	if err := json.Unmarshal(result.Structured, &probed); err != nil || result.IsError || len(probed.Readings) != 1 {
		t.Fatalf("culprit_probe: %v %s", err, result.Structured)
	}
	for _, reading := range probed.Readings {
		if err := reading.Validate(); err != nil {
			t.Errorf("a reading does not validate: %v", err)
		}
	}

	// culprit_diagnose and culprit_verify validate as Investigation and
	// Verification (and are decoded with unknown fields refused).
	diagnosed := structured[mcpDiagnosis](t, client.call("culprit_diagnose", map[string]any{"symptom": "web", "environment": "local"}))
	if err := diagnosed.Investigation.Validate(); err != nil {
		t.Errorf("%v", err)
	}
	server.ordersServed.Store(true)
	verified := structured[model.Verification](t, client.call("culprit_verify",
		map[string]any{"investigation_id": diagnosed.Investigation.ID, "changes": []string{"commit:9f2c4e1"}}))
	if err := verified.Validate(); err != nil {
		t.Errorf("%v", err)
	}
}

// port reads the loop fixture's api port back out of its culprit.yaml.
func (l *loop) port(t *testing.T) int {
	t.Helper()
	raw, err := os.ReadFile(l.manifest)
	if err != nil {
		t.Fatal(err)
	}
	var port int
	for _, line := range strings.Split(string(raw), "\n") {
		if _, err := fmt.Sscanf(strings.TrimSpace(line), "api: { host: 127.0.0.1, port: %d", &port); err == nil {
			return port
		}
	}
	t.Fatal("no api port in the loop fixture")
	return 0
}

// TestNoToolWrites: every tool is offered as read-only, and calling every
// one — the whole loop included — changes no file beside culprit.yaml,
// culprit.yaml itself included. The state directory is the server's own,
// where diagnoses are kept for verification. And nothing in culprit mcp's
// code reaches the control plane: its package and its tools link and name
// no transport.
func TestNoToolWrites(t *testing.T) {
	loop, server := newLoop(t)
	before := treeDigest(t, filepath.Dir(loop.manifest))
	client := mcpCommandSession(t, "-f", loop.manifest, "--from", "web", "--no-plugins", "--state-dir", loop.state)

	listed := client.request("tools/list", map[string]any{})
	var tools struct {
		Tools []struct {
			Name        string         `json:"name"`
			InputSchema map[string]any `json:"inputSchema"`
			Annotations struct {
				ReadOnly    bool `json:"readOnlyHint"`
				Destructive bool `json:"destructiveHint"`
			} `json:"annotations"`
		} `json:"tools"`
	}
	if err := json.Unmarshal(listed.Result, &tools); err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, tool := range tools.Tools {
		names = append(names, tool.Name)
		if !tool.Annotations.ReadOnly || tool.Annotations.Destructive || tool.InputSchema["additionalProperties"] != false {
			t.Errorf("%s is not offered as read-only with closed arguments", tool.Name)
		}
	}
	sort.Strings(names)
	want := []string{"culprit_check", "culprit_diagnose", "culprit_explain_connection", "culprit_probe",
		"culprit_system_model", "culprit_verify"}
	if strings.Join(names, ",") != strings.Join(want, ",") {
		t.Fatalf("tools %v, want %v", names, want)
	}

	client.call("culprit_system_model", map[string]any{})
	client.call("culprit_check", map[string]any{"unverifiable": true})
	client.call("culprit_explain_connection", map[string]any{"from": "web", "to": "api", "environment": "local"})
	client.call("culprit_probe", map[string]any{"target": "component:api", "environment": "local",
		"probes": []string{"probe.http.reachable"},
		"inputs": map[string]any{"url": fmt.Sprintf("http://127.0.0.1:%d/health", loop.port(t))}})
	diagnosed := structured[mcpDiagnosis](t, client.call("culprit_diagnose", map[string]any{"symptom": "web", "environment": "local"}))
	server.ordersServed.Store(true)
	client.call("culprit_verify", map[string]any{"investigation_id": diagnosed.Investigation.ID, "changes": []string{"commit:9f2c4e1"}})

	if after := treeDigest(t, filepath.Dir(loop.manifest)); after != before {
		t.Errorf("a tool changed the directory culprit.yaml is in")
	}

	output, err := exec.Command("go", "list", "-deps", "github.com/josh-heath123/culprit/cli/internal/mcp").Output()
	if err != nil {
		t.Skipf("go list is unavailable in this environment: %v", err)
	}
	for _, dependency := range strings.Fields(string(output)) {
		if strings.HasPrefix(dependency, "github.com/josh-heath123/culprit/cli/internal/") &&
			dependency != "github.com/josh-heath123/culprit/cli/internal/mcp" {
			t.Errorf("internal/mcp links %s: the protocol package knows no Culprit package", dependency)
		}
	}
	source, err := os.ReadFile("mcp.go")
	if err != nil {
		t.Fatal(err)
	}
	for _, reach := range []string{"internal/transport", "controlPlaneClient", "os.WriteFile", "os.Create"} {
		if strings.Contains(string(source), reach) {
			t.Errorf("mcp.go names %s", reach)
		}
	}
}

func treeDigest(t *testing.T, root string) string {
	t.Helper()
	hash := sha256.New()
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() {
			return err
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		relative, _ := filepath.Rel(root, path)
		fmt.Fprintf(hash, "%s %x\n", relative, sha256.Sum256(data))
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return hex.EncodeToString(hash.Sum(nil))
}

// TestMCPRefusesABadStart: the server will not start on a manifest it
// cannot read or a vantage culprit.yaml does not declare.
func TestMCPRefusesABadStart(t *testing.T) {
	loop, _ := newLoop(t)
	command := newRootCommand()
	command.SetIn(strings.NewReader(""))
	command.SetOut(io.Discard)
	command.SetErr(io.Discard)
	command.SetArgs([]string{"mcp", "-f", loop.manifest, "--from", "nowhere"})
	if err := command.Execute(); err == nil || !strings.Contains(err.Error(), "not a component") {
		t.Errorf("started from an undeclared vantage: %v", err)
	}
}

// closedEnvironment is agentManifest with an environment that grants no
// network capability at all: a diagnosis there can read names, and dial
// nothing.
const closedEnvironment = `  closed:
    adapter: process
    components:
      orders: {}
    endpoints:
      payments: { host: payments.internal, port: 8443, health_path: /health }
    grants:
      config.read.names: true
`

// TestDiagnoseAndVerifyDialNothingUngranted: the walk and the verification
// through MCP, in an environment that grants no network capability, on a
// network that counts every dial — none.
func TestDiagnoseAndVerifyDialNothingUngranted(t *testing.T) {
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(agentManifest+closedEnvironment), 0o600); err != nil {
		t.Fatal(err)
	}
	network, http := &countingNetwork{}, &countingHTTP{}
	client := mcpSession(t, &mcpServer{
		manifestPath: path, from: "orders", stateDir: t.TempDir(), agentID: "test", noPlugins: true,
		through: &wire{Network: network, HTTP: http}, stderr: io.Discard,
	})
	result := client.call("culprit_diagnose", map[string]any{"symptom": "orders", "environment": "closed"})
	if result.IsError {
		t.Fatalf("culprit_diagnose: %s", result.Structured)
	}
	diagnosed := structured[mcpDiagnosis](t, result)
	refused := 0
	for _, reading := range diagnosed.Investigation.Readings {
		if reading.Reading.Verdict == model.VerdictRefused {
			refused++
		}
	}
	if refused == 0 {
		t.Fatalf("no reading was refused; the test proves nothing: %+v", diagnosed.Investigation.Readings)
	}
	result = client.call("culprit_verify", map[string]any{"investigation_id": diagnosed.Investigation.ID,
		"changes": []string{"action:nothing"}})
	if result.IsError {
		t.Fatalf("culprit_verify: %s", result.Structured)
	}
	if dials, requests := network.dials.Load()+network.resolves.Load(), http.requests.Load(); dials != 0 || requests != 0 {
		t.Fatalf("%d dial(s) and %d request(s) in an environment that grants no network capability", dials, requests)
	}
}

// TestEditingCulpritYamlMidSessionGrantsNothing: grants are fixed when the
// server starts. An agent that edits culprit.yaml to grant itself a
// capability gets every later call refused, and nothing is dialled.
func TestEditingCulpritYamlMidSessionGrantsNothing(t *testing.T) {
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(agentManifest), 0o600); err != nil {
		t.Fatal(err)
	}
	network, http := &countingNetwork{}, &countingHTTP{}
	client := mcpSession(t, &mcpServer{
		manifestPath: path, stateDir: t.TempDir(), agentID: "test", noPlugins: true,
		through: &wire{Network: network, HTTP: http}, stderr: io.Discard,
	})
	tls := map[string]any{"target": "connection:orders->payments", "environment": "production",
		"probes": []string{"probe.net.tls_validity"}, "inputs": map[string]any{"host": "payments.internal", "port": 8443}}
	if result := client.call("culprit_probe", tls); !result.IsError {
		t.Fatalf("tls_validity ran before the grant was added: %s", result.Structured)
	}
	widened := strings.Replace(agentManifest, "      net.dns.resolve: true\n", "      net.dns.resolve: true\n      net.tls.inspect: true\n", 1)
	if widened == agentManifest {
		t.Fatal("the fixture did not change")
	}
	if err := os.WriteFile(path, []byte(widened), 0o600); err != nil {
		t.Fatal(err)
	}
	for _, call := range []struct {
		tool      string
		arguments map[string]any
	}{{"culprit_probe", tls}, {"culprit_system_model", map[string]any{}}} {
		result := client.call(call.tool, call.arguments)
		if !result.IsError || !strings.Contains(string(result.Structured), "culprit.yaml has changed") {
			t.Errorf("%s after culprit.yaml changed: %s", call.tool, result.Structured)
		}
	}
	if dials := network.dials.Load() + network.resolves.Load(); dials != 0 {
		t.Fatalf("%d dial(s) after the file was edited", dials)
	}
}

// TestProbeInputsAreWhatTheCLIWouldPass: a whole number reaches a probe as
// an int whether written 443 or "443", as --input port=443 does; and an
// input named after a grant is refused however it is cased.
func TestProbeInputsAreWhatTheCLIWouldPass(t *testing.T) {
	var raw map[string]any
	decoder := json.NewDecoder(strings.NewReader(`{"port": 443, "also": "8443", "host": "a", "ratio": 0.5, "x": "443 "}`))
	decoder.UseNumber()
	if err := decoder.Decode(&raw); err != nil {
		t.Fatal(err)
	}
	inputs, err := probeInputs(raw)
	if err != nil {
		t.Fatal(err)
	}
	cli, _ := parseInputs([]string{"port=443", "also=8443", "host=a", "x=443 "})
	for _, name := range []string{"port", "also", "host", "x"} {
		if fmt.Sprintf("%T %v", inputs[name], inputs[name]) != fmt.Sprintf("%T %v", cli[name], cli[name]) {
			t.Errorf("%s: %T %v through MCP, %T %v through --input", name, inputs[name], inputs[name], cli[name], cli[name])
		}
	}
	if inputs["ratio"] != 0.5 {
		t.Errorf("ratio: %v", inputs["ratio"])
	}
	for _, name := range []string{"grants", "Grants", "NET.TCP.CONNECT", "config.inspect.values", "Allow"} {
		if _, err := probeInputs(map[string]any{name: true}); err == nil {
			t.Errorf("%s was accepted as a probe input", name)
		}
	}
}

func mustGrants(t *testing.T, manifestPath, environment string) capability.Grants {
	t.Helper()
	manifest, err := extract.LoadManifest(manifestPath)
	if err != nil {
		t.Fatal(err)
	}
	grants, err := grantsFor(manifest, environment)
	if err != nil {
		t.Fatal(err)
	}
	return grants
}
