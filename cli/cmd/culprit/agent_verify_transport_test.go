package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestAVerificationReachesTheControlPlaneBeforeItsResult is the loop over
// the transport (Phase 34 part 2): a walk, a fix, a verify task — and the
// verification is posted, with the source the task named, just before the
// result that names it.
func TestAVerificationReachesTheControlPlaneBeforeItsResult(t *testing.T) {
	plane := newFakePlane(t)
	server, port := startSwitchableAPI(t)
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "culprit.yaml"), []byte(fmt.Sprintf(loopFixture, port, port)), 0o600); err != nil {
		t.Fatal(err)
	}
	config := filepath.Join(dir, "agent.yaml")
	text := fmt.Sprintf("version: 1\nagent_id: transport-agent\nmanifest: ./culprit.yaml\nkey: ./agent.key\n"+
		"control_plane:\n  url: %s\nenvironments:\n  local:\n    grants:\n"+
		"      net.http.outbound: true\n      net.tcp.connect: true\n      net.dns.resolve: true\n"+
		"      config.read.names: true\n", plane.server.URL)
	if err := os.WriteFile(config, []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{
		{"agent", "init", "--config", config},
		{"agent", "pair", "--config", config, "--code", "ABCDEF-GHJKMN"},
	} {
		if output, err := runCulprit(t, args...); err != nil {
			t.Fatalf("%v: %v\n%s", args, err, output)
		}
	}
	audit := filepath.Join(dir, "audit.log")
	allowance := []string{"config.read.names", "net.dns.resolve", "net.http.outbound", "net.tcp.connect"}
	plane.tasks = []map[string]any{{"id": "task-walk", "environment": "local", "kind": "diagnose",
		"diagnose": map[string]any{"symptom": "web", "from": "web"}, "allowance": allowance}}
	if output, err := runCulprit(t, "agent", "--config", config, "--audit", audit, "--once"); err != nil {
		t.Fatalf("agent: %v\n%s", err, output)
	}
	if len(plane.investigations) != 1 {
		t.Fatalf("%d investigations posted", len(plane.investigations))
	}
	id := fmt.Sprint(plane.investigations[0]["id"])
	if _, err := os.Stat(filepath.Join(dir, "state", "investigations", id, "record.json")); err != nil {
		t.Fatalf("the walk's record is not kept beside the audit log: %v", err)
	}

	server.ordersServed.Store(true)
	plane.order = nil
	plane.tasks = []map[string]any{{"id": "task-verify", "environment": "local", "kind": "verify",
		"verify": map[string]any{"investigation_id": id, "source": "planted",
			"changes": []map[string]any{{"kind": "action", "description": "redeployed web's API"}}},
		"allowance": allowance}}
	if output, err := runCulprit(t, "agent", "--config", config, "--audit", audit, "--once"); err != nil {
		t.Fatalf("agent: %v\n%s", err, output)
	}
	if len(plane.verifications) != 1 {
		t.Fatalf("%d verifications posted", len(plane.verifications))
	}
	posted := plane.verifications[0]
	verification, _ := posted["verification"].(map[string]any)
	if posted["source"] != "planted" || verification["verdict"] != "verified" || verification["investigation_id"] != id {
		t.Errorf("posted source %v, verdict %v, investigation %v: %v",
			posted["source"], verification["verdict"], verification["investigation_id"], verification["reason"])
	}
	result := plane.results["task-verify"]
	if result["verdict"] != "verified" || result["verification_id"] != verification["id"] {
		t.Errorf("the result names %v %v", result["verdict"], result["verification_id"])
	}
	posting := strings.Join(plane.order, " ")
	if !strings.Contains(posting, "/investigations/"+id+"/verifications /agents/me/tasks/task-verify/result") {
		t.Errorf("the verification was not posted just before its result: %s", posting)
	}
}
