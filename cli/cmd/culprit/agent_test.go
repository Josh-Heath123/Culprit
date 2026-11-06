package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/agent"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/probe"
)

// The agent, standing alone (Phase 33 part 1): its authority over its own
// grants, revocation on the next task, and an audit entry for every probe
// it runs — driven through the local task directory, with a network that
// counts every dial.

// countingNetwork answers every dial and counts it. Nothing it is asked
// is real, so the count is the whole story.
type countingNetwork struct{ dials, resolves atomic.Int64 }

func (n *countingNetwork) Resolve(context.Context, string) ([]string, error) {
	n.resolves.Add(1)
	return []string{"192.0.2.10"}, nil
}

func (n *countingNetwork) Dial(context.Context, string, int) error {
	n.dials.Add(1)
	return nil
}

func (n *countingNetwork) InspectTLS(context.Context, string, int, time.Time) (probe.TLSStatus, error) {
	n.dials.Add(1)
	return "", errors.New("no TLS here")
}

type countingHTTP struct{ requests atomic.Int64 }

func (h *countingHTTP) Get(context.Context, string, map[string]string) (probe.HTTPResponse, error) {
	h.requests.Add(1)
	return probe.HTTPResponse{Status: 200}, nil
}

func (h *countingHTTP) Options(context.Context, string, map[string]string) (probe.HTTPResponse, error) {
	h.requests.Add(1)
	return probe.HTTPResponse{Status: 200}, nil
}

// agentWorld is a configuration, a manifest, a task directory and an
// audit log in one temporary directory.
type agentWorld struct {
	t          *testing.T
	dir        string
	configPath string
	network    *countingNetwork
	http       *countingHTTP
	agent      *agent.Agent
	auditPath  string
}

const agentManifest = `version: 1
components:
  - name: orders
    kind: service
    connections:
      - to: payments
        kind: http
        criticality: on_request_path
  - name: payments
    kind: service
environments:
  production:
    adapter: process
    components:
      orders: {}
    endpoints:
      payments: { host: payments.internal, port: 8443, health_path: /health }
    # These grants are culprit.yaml's, and the agent ignores them: its
    # authority is its own configuration.
    grants:
      net.dns.resolve: true
      net.tcp.connect: true
      net.http.outbound: true
`

func newAgentWorld(t *testing.T, manifest string, grants string) *agentWorld {
	t.Helper()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "culprit.yaml"), []byte(manifest), 0o600); err != nil {
		t.Fatal(err)
	}
	world := &agentWorld{
		t: t, dir: dir, configPath: filepath.Join(dir, "agent.yaml"),
		network: &countingNetwork{}, http: &countingHTTP{},
		auditPath: filepath.Join(dir, "audit.log"),
	}
	world.configure(grants)
	source := agent.DirSource{Dir: filepath.Join(dir, "tasks")}
	if err := source.Prepare(); err != nil {
		t.Fatal(err)
	}
	audit, err := agent.OpenAudit(world.auditPath)
	if err != nil {
		t.Fatal(err)
	}
	world.agent = &agent.Agent{
		ConfigPath: world.configPath, Source: source, Audit: audit,
		Executor: &agentExecutor{timeout: 2 * time.Second, wire: func(time.Duration) wire {
			return wire{Network: world.network, HTTP: world.http}
		}},
	}
	return world
}

// configure rewrites the agent's configuration in place, as an operator
// would, while the agent keeps running.
func (w *agentWorld) configure(grants string) {
	w.t.Helper()
	text := "version: 1\nagent_id: agent-under-test\nmanifest: ./culprit.yaml\n" +
		"environments:\n  production:\n    grants:\n" + grants
	if grants == "" {
		text += "      {}\n"
		text = strings.Replace(text, "    grants:\n      {}\n", "    grants: {}\n", 1)
	}
	if err := os.WriteFile(w.configPath, []byte(text), 0o600); err != nil {
		w.t.Fatal(err)
	}
}

func (w *agentWorld) submit(task agent.Task) {
	w.t.Helper()
	body, _ := json.Marshal(task)
	if err := os.WriteFile(filepath.Join(w.dir, "tasks", "inbox", task.ID+".json"), body, 0o600); err != nil {
		w.t.Fatal(err)
	}
}

func (w *agentWorld) drain() {
	w.t.Helper()
	if _, err := w.agent.Drain(context.Background()); err != nil {
		w.t.Fatal(err)
	}
}

func (w *agentWorld) result(id string) agent.Result {
	w.t.Helper()
	data, err := os.ReadFile(filepath.Join(w.dir, "tasks", "outbox", id+".json"))
	if err != nil {
		w.t.Fatalf("no result for %s: %v", id, err)
	}
	var result agent.Result
	if err := json.Unmarshal(data, &result); err != nil {
		w.t.Fatal(err)
	}
	return result
}

func (w *agentWorld) entries(taskID string) []agent.Entry {
	w.t.Helper()
	all, err := agent.ReadAudit(w.auditPath)
	if err != nil {
		w.t.Fatalf("the audit log does not verify: %v", err)
	}
	var mine []agent.Entry
	for _, entry := range all {
		if entry.TaskID == taskID {
			mine = append(mine, entry)
		}
	}
	return mine
}

func tcpTask(id string, allowance []string) agent.Task {
	return agent.Task{
		ID: id, Environment: "production", Kind: agent.TaskProbe, Allowance: allowance,
		Probe: &agent.ProbeTask{
			ProbeID: "probe.net.tcp_connect", Target: "connection:orders->payments",
			Inputs: map[string]any{"host": "payments.internal", "port": 8443},
		},
	}
}

// Field 13's chaos test, against the local source: a task asking for a
// capability the agent was not granted is refused without dialling, and
// the refusal is both a reading and an audit entry.
func TestATaskNeedingAnUngrantedCapabilityIsRefusedWithoutDialling(t *testing.T) {
	world := newAgentWorld(t, agentManifest, "      net.dns.resolve: true\n")
	world.submit(tcpTask("chaos-1", nil))
	// The same task again, with an allowance that names the missing grant:
	// whoever sends tasks can narrow the agent's grants, never widen them.
	world.submit(tcpTask("chaos-2", []string{"net.tcp.connect", "net.dns.resolve"}))
	world.drain()

	if dials := world.network.dials.Load(); dials != 0 {
		t.Fatalf("%d dial(s) for tasks the agent was not granted", dials)
	}
	for _, id := range []string{"chaos-1", "chaos-2"} {
		result := world.result(id)
		if result.Outcome != agent.OutcomeRefused || len(result.Readings) != 1 ||
			result.Readings[0].Verdict != model.VerdictRefused {
			t.Errorf("%s: outcome %s, readings %+v; want a refused reading", id, result.Outcome, result.Readings)
			continue
		}
		if !strings.Contains(result.Readings[0].Reason, "net.tcp.connect") {
			t.Errorf("%s: the refusal does not name the grant: %q", id, result.Readings[0].Reason)
		}
		entries := world.entries(id)
		if len(entries) != 2 || entries[0].Kind != agent.EntryProbe || entries[1].Kind != agent.EntryTask {
			t.Fatalf("%s: audit entries %+v, want one probe entry then the task entry", id, entries)
		}
		if entries[0].Verdict != "refused" || len(entries[0].Grants) != 0 {
			t.Errorf("%s: probe entry %+v, want refused with no grants", id, entries[0])
		}
		if entries[1].Outcome != agent.OutcomeRefused {
			t.Errorf("%s: task entry outcome %s", id, entries[1].Outcome)
		}
	}
	if ignored := world.result("chaos-2").AllowanceIgnored; strings.Join(ignored, ",") != "net.tcp.connect" {
		t.Errorf("allowance_ignored = %v, want [net.tcp.connect]: asked for, not given", ignored)
	}
}

func TestAnAllowanceCanWithholdAGrantTheAgentHolds(t *testing.T) {
	world := newAgentWorld(t, agentManifest, "      net.dns.resolve: true\n      net.tcp.connect: true\n")
	world.submit(tcpTask("narrowed", []string{"net.dns.resolve"}))
	world.drain()
	if dials := world.network.dials.Load(); dials != 0 {
		t.Fatalf("%d dial(s) under an allowance that withheld net.tcp.connect", dials)
	}
	if result := world.result("narrowed"); result.Outcome != agent.OutcomeRefused ||
		strings.Join(result.GrantsHeld, ",") != "net.dns.resolve" {
		t.Errorf("outcome %s, held %v", result.Outcome, result.GrantsHeld)
	}
}

// Field 14: a grant removed from the configuration takes effect on the
// next task, with no restart — the same Agent, the same process.
func TestARevokedGrantTakesEffectOnTheNextTaskWithNoRestart(t *testing.T) {
	world := newAgentWorld(t, agentManifest, "      net.dns.resolve: true\n      net.tcp.connect: true\n")
	world.submit(tcpTask("before", nil))
	world.drain()
	if result := world.result("before"); result.Outcome != agent.OutcomeCompleted ||
		result.Readings[0].Verdict != model.VerdictPass {
		t.Fatalf("before revocation: %s %+v", result.Outcome, result.Readings)
	}
	if dials := world.network.dials.Load(); dials != 1 {
		t.Fatalf("before revocation: %d dials, want 1", dials)
	}

	world.configure("      net.dns.resolve: true\n")
	world.submit(tcpTask("after", nil))
	world.drain()
	if dials := world.network.dials.Load(); dials != 1 {
		t.Fatalf("after revocation: %d dials, want still 1", dials)
	}
	if result := world.result("after"); result.Outcome != agent.OutcomeRefused {
		t.Errorf("after revocation: outcome %s", result.Outcome)
	}
}

func TestAConfigurationThatStopsParsingStopsEveryTask(t *testing.T) {
	world := newAgentWorld(t, agentManifest, "      net.tcp.connect: true\n")
	world.configure("      net.*: true\n")
	world.submit(tcpTask("unparsed", nil))
	world.drain()
	result := world.result("unparsed")
	if result.Outcome != agent.OutcomeError || !strings.Contains(result.Reason, "wildcard") {
		t.Errorf("outcome %s (%q), want an error naming the wildcard", result.Outcome, result.Reason)
	}
	if world.network.dials.Load() != 0 {
		t.Error("a task ran under a configuration that does not parse")
	}
}

func TestATaskForAnEnvironmentTheAgentIsNotConfiguredForIsRefused(t *testing.T) {
	world := newAgentWorld(t, agentManifest, "      net.tcp.connect: true\n")
	task := tcpTask("elsewhere", nil)
	task.Environment = "staging"
	world.submit(task)
	world.drain()
	if result := world.result("elsewhere"); result.Outcome != agent.OutcomeRefused || world.network.dials.Load() != 0 {
		t.Errorf("outcome %s, dials %d", result.Outcome, world.network.dials.Load())
	}
}

// Every executed probe has exactly one audit entry: a walk, which chooses
// and runs its own probes, against a real (local) server.
func TestEveryProbeAWalkRunsHasExactlyOneAuditEntry(t *testing.T) {
	port := startAPI(t)
	manifest := fmt.Sprintf(diagnoseFixture, port)
	world := newAgentWorld(t, manifest, "")
	// The world's own wire counts; this walk needs the real one, to reach
	// the local server.
	world.agent.Executor = &agentExecutor{timeout: 2 * time.Second, wire: realWire}
	// diagnoseFixture's environment is "local".
	text := "version: 1\nagent_id: agent-under-test\nmanifest: ./culprit.yaml\nenvironments:\n  local:\n    grants:\n" +
		"      net.http.outbound: true\n      net.tcp.connect: true\n      net.dns.resolve: true\n"
	if err := os.WriteFile(world.configPath, []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	world.submit(agent.Task{ID: "walk-1", Environment: "local", Kind: agent.TaskDiagnose,
		Diagnose: &agent.DiagnoseTask{Symptom: "web", From: "web"}})
	world.drain()

	result := world.result("walk-1")
	if result.Investigation == nil {
		t.Fatalf("no investigation: %s %q", result.Outcome, result.Reason)
	}
	readings := result.Investigation.Readings
	if len(readings) == 0 {
		t.Fatal("the walk ran no probes")
	}
	entries := world.entries("walk-1")
	var probes []agent.Entry
	for _, entry := range entries {
		if entry.Kind == agent.EntryProbe {
			probes = append(probes, entry)
		}
	}
	if len(probes) != len(readings) {
		t.Fatalf("%d readings, %d probe entries: every executed probe needs exactly one", len(readings), len(probes))
	}
	for index, held := range readings {
		reading, entry := held.Reading, probes[index]
		if entry.ProbeID != reading.ProbeID || entry.Target != reading.Target || entry.Verdict != string(reading.Verdict) {
			t.Errorf("entry %d is %s %s %s, reading %d is %s %s %s", index,
				entry.ProbeID, entry.Target, entry.Verdict, index, reading.ProbeID, reading.Target, reading.Verdict)
		}
		if strings.Join(entry.Grants, ",") != strings.Join(reading.GrantsUsed, ",") {
			t.Errorf("entry %d grants %v, reading's grants_used %v", index, entry.Grants, reading.GrantsUsed)
		}
	}
	if last := entries[len(entries)-1]; last.Kind != agent.EntryTask {
		t.Errorf("the task entry is not last: %+v", last)
	}
}

func TestAgentVerifyNamesABrokenChain(t *testing.T) {
	world := newAgentWorld(t, agentManifest, "      net.tcp.connect: true\n")
	world.submit(tcpTask("one", nil))
	world.submit(tcpTask("two", nil))
	world.drain()

	verify := func() (string, error) {
		command := newRootCommand()
		var out, errOut strings.Builder
		command.SetOut(&out)
		command.SetErr(&errOut)
		command.SetArgs([]string{"agent", "verify", world.auditPath})
		err := command.Execute()
		return out.String() + errOut.String(), err
	}
	if output, err := verify(); err != nil || !strings.Contains(output, "4 entries, chain intact") {
		t.Fatalf("intact log: %v %q", err, output)
	}
	data, _ := os.ReadFile(world.auditPath)
	edited := strings.Replace(string(data), `"verdict":"pass"`, `"verdict":"fail"`, 1)
	if err := os.WriteFile(world.auditPath, []byte(edited), 0o600); err != nil {
		t.Fatal(err)
	}
	output, err := verify()
	var findings *findingsError
	if !errors.As(err, &findings) || !strings.Contains(output, "line 1") {
		t.Fatalf("edited log: err %v, output %q; want exit 1 naming line 1", err, output)
	}
}

func TestATaskWhoseIdIsNotItsFileNameIsNotRun(t *testing.T) {
	world := newAgentWorld(t, agentManifest, "      net.tcp.connect: true\n")
	body, _ := json.Marshal(tcpTask("../../escape", nil))
	if err := os.WriteFile(filepath.Join(world.dir, "tasks", "inbox", "honest.json"), body, 0o600); err != nil {
		t.Fatal(err)
	}
	world.drain()
	result := world.result("honest")
	if result.Outcome != agent.OutcomeError || !strings.Contains(result.Reason, "not its file name") {
		t.Errorf("outcome %s (%q)", result.Outcome, result.Reason)
	}
	if world.network.dials.Load() != 0 {
		t.Error("a task with a mismatched id ran")
	}
}

func TestATaskIdIsNeverReusedAndAResultNeverOverwritten(t *testing.T) {
	world := newAgentWorld(t, agentManifest, "      net.tcp.connect: true\n")
	world.submit(tcpTask("once", nil))
	world.drain()
	first, _ := os.ReadFile(filepath.Join(world.dir, "tasks", "outbox", "once.json"))
	world.submit(tcpTask("once", nil))
	world.drain()
	again, _ := os.ReadFile(filepath.Join(world.dir, "tasks", "outbox", "once.json"))
	if string(first) != string(again) {
		t.Fatal("the first result was overwritten")
	}
	data, err := os.ReadFile(filepath.Join(world.dir, "tasks", "outbox", "once.1.json"))
	if err != nil || !strings.Contains(string(data), "not reused") {
		t.Fatalf("the reused id was not refused under a new name: %v %s", err, data)
	}
	if dials := world.network.dials.Load(); dials != 1 {
		t.Errorf("%d dials; the reused task must not run", dials)
	}
}

func TestAgentVerifyOnAnUnreadableLogIsAnErrorNotAFinding(t *testing.T) {
	command := newRootCommand()
	var out strings.Builder
	command.SetOut(&out)
	command.SetErr(&out)
	command.SetArgs([]string{"agent", "verify", filepath.Join(t.TempDir(), "no-such.log")})
	err := command.Execute()
	var findings *findingsError
	if err == nil || errors.As(err, &findings) {
		t.Fatalf("err = %v, want a plain error (exit 2), not a finding (exit 1)", err)
	}
}
