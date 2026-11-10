package main

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/agentauth"
	"github.com/josh-heath123/culprit/cli/internal/transport"
)

// The binary against a control plane (Phase 33 part 2): init, pair, and
// tasks over the real transport. The fake control plane here verifies
// every signature with internal/agentauth — the half of the contract the
// shared fixture holds the API to — so a request it accepts is one the
// API would.

type fakePlane struct {
	t        *testing.T
	mu       sync.Mutex
	server   *httptest.Server
	pairing  [][]byte // every byte of every pairing request, as received
	public   ed25519.PublicKey
	agentID  string
	revoked  bool
	nonces   map[string]bool
	tasks    []map[string]any
	results  map[string]map[string]any
	readings []map[string]any
	audit    []string
	// Phase 34 part 2: what a walk and a verification post, and the order
	// every accepted request arrived in.
	investigations []map[string]any
	verifications  []map[string]any
	order          []string
}

func newFakePlane(t *testing.T) *fakePlane {
	plane := &fakePlane{t: t, nonces: map[string]bool{}, results: map[string]map[string]any{}}
	plane.server = httptest.NewServer(http.HandlerFunc(plane.handle))
	t.Cleanup(plane.server.Close)
	return plane
}

func (p *fakePlane) verified(r *http.Request, body []byte) bool {
	timestamp, _ := strconv.ParseInt(r.Header.Get(agentauth.HeaderTimestamp), 10, 64)
	request := agentauth.Request{Method: r.Method, Path: r.URL.Path, Body: body, Timestamp: timestamp,
		Nonce: r.Header.Get(agentauth.HeaderNonce), AgentID: r.Header.Get(agentauth.HeaderAgent)}
	if p.public == nil || request.AgentID != p.agentID {
		return false
	}
	ok := agentauth.Decide(&agentauth.Key{Public: p.public, Revoked: p.revoked}, request,
		r.Header.Get(agentauth.HeaderSignature), time.Now(), func(n string) bool { return p.nonces[n] })
	if ok {
		p.nonces[request.Nonce] = true
	}
	return ok
}

func (p *fakePlane) handle(w http.ResponseWriter, r *http.Request) {
	p.mu.Lock()
	defer p.mu.Unlock()
	// Every request, whatever its path, while the agent is not yet paired:
	// "every byte the agent sends while pairing".
	if p.public == nil {
		dump, _ := httputil.DumpRequest(r, true)
		p.pairing = append(p.pairing, dump)
		r.Body = io.NopCloser(bytes.NewReader(dump[bytes.Index(dump, []byte("\r\n\r\n"))+4:]))
	}
	if r.URL.Path == "/agents/register" {
		dump := p.pairing[len(p.pairing)-1]
		var body transport.Registration
		_ = json.Unmarshal(dump[bytes.Index(dump, []byte("\r\n\r\n"))+4:], &body)
		key, _ := base64.StdEncoding.DecodeString(body.PublicKey)
		p.public, p.agentID = key, body.AgentID
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte(`{"agent_id":"` + body.AgentID + `"}`))
		return
	}
	body, _ := io.ReadAll(r.Body)
	if !p.verified(r, body) {
		http.Error(w, `{"detail":"request refused"}`, http.StatusUnauthorized)
		return
	}
	p.order = append(p.order, r.URL.Path)
	switch {
	case r.URL.Path == "/investigations":
		var investigation map[string]any
		_ = json.Unmarshal(body, &investigation)
		p.investigations = append(p.investigations, investigation)
		w.WriteHeader(http.StatusCreated)
	case strings.HasPrefix(r.URL.Path, "/investigations/") && strings.HasSuffix(r.URL.Path, "/verifications"):
		var posted map[string]any
		_ = json.Unmarshal(body, &posted)
		p.verifications = append(p.verifications, posted)
		w.WriteHeader(http.StatusCreated)
	case r.URL.Path == "/agents/me/tasks/claim":
		if len(p.tasks) == 0 {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		task := p.tasks[0]
		p.tasks = p.tasks[1:]
		_ = json.NewEncoder(w).Encode(task)
	case strings.HasPrefix(r.URL.Path, "/agents/me/tasks/") && strings.HasSuffix(r.URL.Path, "/result"):
		var result map[string]any
		_ = json.Unmarshal(body, &result)
		p.results[strings.Split(r.URL.Path, "/")[4]] = result
		w.WriteHeader(http.StatusNoContent)
	case r.URL.Path == "/readings":
		var batch struct {
			Readings []map[string]any `json:"readings"`
		}
		_ = json.Unmarshal(body, &batch)
		for _, reading := range batch.Readings {
			if reading["agent_id"] != p.agentID {
				http.Error(w, "another agent", http.StatusForbidden)
				return
			}
		}
		p.readings = append(p.readings, batch.Readings...)
		w.WriteHeader(http.StatusCreated)
	case r.URL.Path == "/agents/me/audit/head":
		_ = json.NewEncoder(w).Encode(map[string]any{"seq": len(p.audit), "hash": p.head()})
	case r.URL.Path == "/agents/me/audit":
		var batch struct {
			Entries []string `json:"entries"`
		}
		_ = json.Unmarshal(body, &batch)
		for _, line := range batch.Entries {
			var entry struct {
				Seq  int    `json:"seq"`
				Prev string `json:"prev"`
			}
			_ = json.Unmarshal([]byte(line), &entry)
			if entry.Seq != len(p.audit)+1 || entry.Prev != p.head() {
				w.WriteHeader(http.StatusConflict)
				return
			}
			p.audit = append(p.audit, line)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"seq": len(p.audit), "hash": p.head()})
	default:
		http.NotFound(w, r)
	}
}

func (p *fakePlane) head() string {
	if len(p.audit) == 0 {
		return strings.Repeat("0", 64)
	}
	var entry struct {
		Hash string `json:"hash"`
	}
	_ = json.Unmarshal([]byte(p.audit[len(p.audit)-1]), &entry)
	return entry.Hash
}

func runCulprit(t *testing.T, args ...string) (string, error) {
	t.Helper()
	command := newRootCommand()
	var out bytes.Buffer
	command.SetOut(&out)
	command.SetErr(&out)
	command.SetArgs(args)
	err := command.Execute()
	return out.String(), err
}

func pairedAgent(t *testing.T, plane *fakePlane, grants string) (dir, config string) {
	t.Helper()
	dir = t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "culprit.yaml"), []byte(agentManifest), 0o600); err != nil {
		t.Fatal(err)
	}
	config = filepath.Join(dir, "agent.yaml")
	text := fmt.Sprintf("version: 1\nagent_id: transport-agent\nmanifest: ./culprit.yaml\nkey: ./agent.key\n"+
		"control_plane:\n  url: %s\nenvironments:\n  production:\n    grants:\n%s", plane.server.URL, grants)
	if err := os.WriteFile(config, []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	if output, err := runCulprit(t, "agent", "init", "--config", config); err != nil {
		t.Fatalf("init: %v\n%s", err, output)
	}
	if output, err := runCulprit(t, "agent", "pair", "--config", config, "--code", "ABCDEF-GHJKMN"); err != nil {
		t.Fatalf("pair: %v\n%s", err, output)
	}
	return dir, config
}

func TestInitWritesAKeyOnlyItsOwnerCanReadAndNeverOverwritesOne(t *testing.T) {
	plane := newFakePlane(t)
	dir, config := pairedAgent(t, plane, "      net.dns.resolve: true\n")
	keyPath := filepath.Join(dir, "agent.key")
	info, err := os.Stat(keyPath)
	if err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS != "windows" && info.Mode().Perm() != 0o600 {
		t.Errorf("the key is %v, want 0600", info.Mode().Perm())
	}
	before, _ := os.ReadFile(keyPath)
	output, err := runCulprit(t, "agent", "init", "--config", config)
	if err == nil || !strings.Contains(err.Error()+output, "never overwritten") {
		t.Fatalf("a second init: %v %s", err, output)
	}
	after, _ := os.ReadFile(keyPath)
	if !bytes.Equal(before, after) {
		t.Fatal("the key was overwritten")
	}
}

// Every byte the agent sends while pairing, captured: the public key is
// there, and neither the private key nor its seed, in any encoding the
// key file or Go would write it in.
func TestPairingSendsNoPrivateKey(t *testing.T) {
	plane := newFakePlane(t)
	dir, _ := pairedAgent(t, plane, "      net.dns.resolve: true\n")
	if len(plane.pairing) != 1 {
		t.Fatalf("%d pairing requests, want 1", len(plane.pairing))
	}
	sent := plane.pairing[0]
	data, _ := os.ReadFile(filepath.Join(dir, "agent.key"))
	key, err := transport.ParseKey(data)
	if err != nil {
		t.Fatal(err)
	}
	for name, secret := range map[string][]byte{
		"the raw seed":            key.Seed(),
		"the raw private key":     key,
		"the seed, base64":        []byte(base64.StdEncoding.EncodeToString(key.Seed())),
		"the private key, base64": []byte(base64.StdEncoding.EncodeToString(key)),
		"the seed, base64url":     []byte(base64.RawURLEncoding.EncodeToString(key.Seed())),
		"the key file":            bytes.TrimSpace(data),
		"the seed, hex":           []byte(fmt.Sprintf("%x", key.Seed())),
	} {
		if bytes.Contains(sent, secret) {
			t.Errorf("the pairing request contains %s", name)
		}
	}
	public := base64.StdEncoding.EncodeToString(key.Public().(ed25519.PublicKey))
	if !bytes.Contains(sent, []byte(public)) {
		t.Error("the pairing request does not carry the public key")
	}
	if !bytes.Contains(sent, []byte(`"net.dns.resolve"`)) {
		t.Error("the pairing request does not report the configuration's grants")
	}
}

// Field 13's chaos test over the real transport: the control plane's
// allowance names a grant the agent's configuration lacks. The agent runs
// the task without it — refused before anything is dialled — and records
// it, the reading and the audit entry both reaching the control plane.
func TestAnAllowanceNamingAGrantTheConfigurationLacksIsRefusedOverTheTransport(t *testing.T) {
	plane := newFakePlane(t)
	dir, config := pairedAgent(t, plane, "      net.dns.resolve: true\n")
	plane.tasks = []map[string]any{
		{"id": "task-chaos", "environment": "production", "kind": "probe",
			"probe":     map[string]any{"probe_id": "probe.net.tcp_connect", "target": "connection:orders->payments", "inputs": map[string]any{"host": "127.0.0.1", "port": 9}},
			"allowance": []string{"net.tcp.connect", "net.dns.resolve"}},
		{"id": "task-resolve", "environment": "production", "kind": "probe",
			"probe":     map[string]any{"probe_id": "probe.net.dns_resolve", "target": "connection:orders->payments", "inputs": map[string]any{"host": "localhost"}},
			"allowance": []string{"net.dns.resolve"}},
	}
	audit := filepath.Join(dir, "audit.log")
	if output, err := runCulprit(t, "agent", "--config", config, "--audit", audit, "--once"); err != nil {
		t.Fatalf("agent: %v\n%s", err, output)
	}

	chaos := plane.results["task-chaos"]
	if chaos["outcome"] != "refused" || !strings.Contains(fmt.Sprint(chaos["reason"]), "net.tcp.connect") {
		t.Errorf("chaos task result %v, want refused naming net.tcp.connect", chaos)
	}
	if fmt.Sprint(chaos["allowance_ignored"]) != "[net.tcp.connect]" {
		t.Errorf("allowance_ignored %v: the allowance asked for a grant the agent does not hold", chaos["allowance_ignored"])
	}
	if plane.results["task-resolve"]["outcome"] != "completed" {
		t.Errorf("resolve task result %v", plane.results["task-resolve"])
	}

	// One reading per probe, each the agent's own; one probe entry per
	// reading in the shipped chain, which matches the local one exactly.
	if len(plane.readings) != 2 {
		t.Fatalf("%d readings reached the control plane, want 2", len(plane.readings))
	}
	if plane.readings[0]["verdict"] != "refused" || plane.readings[0]["grants_used"] != nil {
		t.Errorf("the chaos reading %v, want refused with no grants", plane.readings[0])
	}
	probes := 0
	for _, line := range plane.audit {
		if strings.Contains(line, `"kind":"probe"`) {
			probes++
		}
	}
	if probes != 2 || len(plane.audit) != 4 {
		t.Errorf("shipped %d entries, %d of them probes; want 4 and 2", len(plane.audit), probes)
	}
	local, _ := os.ReadFile(audit)
	if strings.Join(plane.audit, "\n")+"\n" != string(local) {
		t.Error("the shipped chain is not the local log, byte for byte")
	}
}

func TestARevokedAgentStopsOnItsNextRequest(t *testing.T) {
	plane := newFakePlane(t)
	dir, config := pairedAgent(t, plane, "      net.dns.resolve: true\n")
	plane.revoked = true
	output, err := runCulprit(t, "agent", "--config", config, "--audit", filepath.Join(dir, "audit.log"), "--once")
	if err == nil || !strings.Contains(err.Error()+output, "401") {
		t.Fatalf("a revoked agent: %v %s", err, output)
	}
}

// Phase 33 part 3: allow_plain_http is reported at every start — by
// `culprit agent` and by `culprit agent pair`, the two commands that reach the control plane —
// and a configuration without it says nothing of the kind.
func TestAllowPlainHTTPIsReportedAtEveryStart(t *testing.T) {
	plane := newFakePlane(t)
	_, config := pairedAgent(t, plane, "      net.dns.resolve: true\n")
	quiet, err := runCulprit(t, "agent", "--config", config, "--audit", filepath.Join(t.TempDir(), "audit.log"), "--once")
	if err != nil {
		t.Fatalf("run: %v\n%s", err, quiet)
	}
	if strings.Contains(quiet, "allow_plain_http") {
		t.Errorf("reported allow_plain_http though the configuration does not set it:\n%s", quiet)
	}

	text, _ := os.ReadFile(config)
	allowed := strings.Replace(string(text), "control_plane:\n", "control_plane:\n  allow_plain_http: true\n", 1)
	if err := os.WriteFile(config, []byte(allowed), 0o600); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{
		{"agent", "--config", config, "--audit", filepath.Join(t.TempDir(), "audit.log"), "--once"},
		{"agent", "pair", "--config", config, "--code", "ABCDEF-GHJKMN"},
	} {
		output, _ := runCulprit(t, args...)
		if !strings.Contains(output, "allow_plain_http") || !strings.Contains(output, "unencrypted") {
			t.Errorf("`culprit %s` did not report allow_plain_http at start:\n%s", strings.Join(args[:2], " "), output)
		}
	}
}
