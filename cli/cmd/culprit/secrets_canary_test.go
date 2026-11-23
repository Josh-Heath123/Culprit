// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/agent"
)

// The canary (Phase 44 batch 1, decision 3; docs/SECURITY.md §8): a
// distinct secret is planted in every class of input Culprit reads from
// outside itself, every command and output format is run over them, and
// none of the secrets may appear in stdout, stderr, any file written or
// any MCP result. The API's half is api/tests/test_secrets_canary.py.
//
// Each secret is in a shape shared/tests/redaction_conformance.json lists,
// because that is the promise: a shape not listed there is not covered.

// leakyExtractorVariable makes this test binary act as an extractor that
// writes its value to stderr and exits 3 (see TestMain in verify_test.go).
const leakyExtractorVariable = "CULPRIT_TEST_LEAKY_EXTRACTOR"

// planted is one secret per input class, each distinct, so a leak names
// the exit it came out of.
var planted = map[string]string{
	"extractor stderr (DSN)":             "ExtLeakA1",
	"extractor stderr (env-style key)":   "ExtLeakA2",
	"probe input (URL userinfo)":         "ProbeLeakB1",
	"probe measured list (JWT audience)": "ProbeLeakB2",
	"agent task symptom":                 "AgentLeakC1",
	"change action":                      "ChangeLeakD1",
	"change action through MCP":          "ChangeLeakD2",
	"manifest value":                     "ManLeakE1",
	"bad --input argument":               "ArgLeakF1",
	"bad symptom argument":               "ArgLeakF2",
	"bad --change argument":              "ArgLeakF3",
	"MCP symptom":                        "McpLeakG1",
}

const canaryManifest = `version: 1
components:
  - name: svc
    kind: service
extract:
  extractors:
    - name: leak
      command: [%q]
  components:
    svc: { root: ., extractors: [leak] }
environments:
  local:
    adapter: process
    components:
      svc: {}
    grants:
      net.http.outbound: true
      net.tcp.connect: true
      net.dns.resolve: true
`

// canaryOutputs collects everything any command wrote, by where it went.
type canaryOutputs map[string]string

func (o canaryOutputs) add(where, text string) { o[where] += text }

// run executes the CLI as main does — the error line included — and keeps
// stdout and stderr.
func (o canaryOutputs) run(t *testing.T, arguments ...string) {
	t.Helper()
	var stdout, stderr bytes.Buffer
	code := execute(arguments, &stdout, &stderr)
	label := strings.Join(arguments, " ")
	if len(label) > 60 {
		label = label[:60]
	}
	o.add("stdout of "+label, stdout.String())
	o.add("stderr of "+label, stderr.String())
	t.Logf("%s: exit %d", label, code)
}

// files reads every file under a directory that Culprit wrote. A local
// agent's inbox/ and done/ hold the operator's own task file, moved and
// never rewritten: what it is given is not something it writes.
func (o canaryOutputs) files(t *testing.T, root string) {
	t.Helper()
	_ = filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if entry.IsDir() {
			if name := entry.Name(); name == "inbox" || name == "done" {
				return filepath.SkipDir
			}
			return nil
		}
		data, readErr := os.ReadFile(path)
		if readErr == nil {
			o.add("file "+path, string(data))
		}
		return nil
	})
}

func canaryJWT(audiences ...string) string {
	part := func(value any) string {
		encoded, _ := json.Marshal(value)
		return base64.RawURLEncoding.EncodeToString(encoded)
	}
	return part(map[string]any{"alg": "none"}) + "." +
		part(map[string]any{"aud": audiences, "iss": "canary", "exp": 4102444800}) + ".c2ln"
}

func TestNoPlantedSecretLeavesAnyExit(t *testing.T) {
	t.Setenv("LLM_PROVIDER", "none")
	outputs := canaryOutputs{}

	// 1. An extractor's stderr: intent and check, every format.
	project := t.TempDir()
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	manifest := filepath.Join(project, "culprit.yaml")
	if err := os.WriteFile(manifest, []byte(fmt.Sprintf(canaryManifest, executable)), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv(leakyExtractorVariable, "connect failed: postgresql://app:"+planted["extractor stderr (DSN)"]+
		"@db.internal/app DB_PASSWORD="+planted["extractor stderr (env-style key)"])
	for _, format := range []string{"text", "json"} {
		outputs.run(t, "intent", "-f", manifest, "--format", format)
	}
	for _, format := range []string{"text", "json", "sarif", "junit"} {
		outputs.run(t, "check", "-f", manifest, "--format", format)
	}

	// 2. A probe's input and a measured list, text and JSON.
	state := t.TempDir()
	token := canaryJWT("orders", "postgresql://app:"+planted["probe measured list (JWT audience)"]+"@db.internal/app")
	for _, format := range []string{"text", "json"} {
		outputs.run(t, "probe", "auth:svc->db/audience", "-f", manifest, "--env", "local", "--no-plugins",
			"-p", "probe.auth.token_shape", "--input", "token="+token, "--input", "expect_audience=other",
			"--format", format)
		outputs.run(t, "probe", "component:svc", "-f", manifest, "--env", "local", "--no-plugins",
			"-p", "probe.http.status", "--input",
			"url=http://canary:"+planted["probe input (URL userinfo)"]+"@127.0.0.1:1/health",
			"--format", format)
	}

	// 3. Arguments the CLI refuses, echoed in its error line.
	outputs.run(t, "probe", "component:svc", "-f", manifest, "--no-plugins",
		"--input", "postgresql://u:"+planted["bad --input argument"]+"@h/d")
	outputs.run(t, "diagnose", "postgresql://u:"+planted["bad symptom argument"]+"@h/d",
		"-f", manifest, "--env", "local", "--no-plugins", "--state-dir", state)
	outputs.run(t, "verify", "inv-0000000000000000", "-f", manifest, "--no-plugins", "--state-dir", state,
		"--change", "DB_PASSWORD="+planted["bad --change argument"])

	// 4. A value in culprit.yaml that the loader refuses.
	badManifest := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(badManifest, []byte("version: 1\ncomponents:\n  - name: svc\n    kind: \"DB_PASSWORD="+
		planted["manifest value"]+"\"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	outputs.run(t, "check", "-f", badManifest, "--no-plugins")
	outputs.run(t, "intent", "-f", badManifest, "--no-plugins")

	// 5. A change named in words, through the CLI and through MCP.
	loop, server := newLoop(t)
	inv := loop.diagnose("local")
	server.ordersServed.Store(true)
	outputs.run(t, "verify", inv.ID, "-f", loop.manifest, "--no-plugins", "--format", "json",
		"--state-dir", loop.state, "--from", "web",
		"--change", "action:rotated DB_PASSWORD="+planted["change action"])
	client := mcpCommandSession(t, "-f", loop.manifest, "--from", "web", "--no-plugins", "--state-dir", loop.state)
	result := client.call("culprit_verify", map[string]any{
		"investigation_id": inv.ID, "changes": []string{"action:rotated DB_PASSWORD=" + planted["change action through MCP"]},
	})
	outputs.add("MCP culprit_verify", string(result.Structured))
	result = client.call("culprit_diagnose", map[string]any{
		"symptom": "postgresql://u:" + planted["MCP symptom"] + "@h/d", "environment": "local",
	})
	outputs.add("MCP culprit_diagnose", string(result.Structured))
	outputs.files(t, loop.state)

	// 6. An agent task whose symptom carries a DSN: the audit log, the
	// outbox and the agent's own log.
	world := newAgentWorld(t, agentManifest, "      net.tcp.connect: true\n")
	var agentLog bytes.Buffer
	world.agent.Logf = func(format string, args ...any) { fmt.Fprintf(&agentLog, format+"\n", args...) }
	world.submit(agent.Task{
		ID: "canary", Environment: "production", Kind: agent.TaskDiagnose,
		Diagnose: &agent.DiagnoseTask{Symptom: "postgresql://app:" + planted["agent task symptom"] + "@db.internal/app"},
	})
	world.drain()
	outputs.add("agent log", agentLog.String())
	outputs.files(t, world.dir)

	outputs.files(t, project)
	outputs.files(t, state)

	leaks := 0
	for class, secret := range planted {
		for where, text := range outputs {
			if strings.Contains(text, secret) {
				leaks++
				t.Errorf("the %s (%s) leaves through %s", class, secret, where)
			}
		}
	}
	// The canary is only as good as its reach: each class must have been
	// read, or a command that failed early would pass it by saying nothing.
	if leaks == 0 && len(outputs) < 20 {
		t.Errorf("only %d outputs were collected; the canary did not run every exit", len(outputs))
	}
}
