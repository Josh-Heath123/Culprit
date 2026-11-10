package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/verify"
)

// TestMain keeps every test in this package out of the user's state
// directory: `culprit diagnose` now keeps what it diagnoses for `culprit
// verify`, and a test run must not leave investigations in $HOME.
func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "culprit-state-")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	os.Setenv("CULPRIT_STATE_DIR", dir)
	code := m.Run()
	_ = os.RemoveAll(dir)
	os.Exit(code)
}

// loopFixture is diagnoseFixture with config.read.names granted, so the
// process adapter can record web's environment — names and shapes — as the
// capture before.
const loopFixture = `version: 1
components:
  - name: web
    kind: frontend
    connections:
      - to: api
        kind: http
        criticality: on_request_path
  - name: api
    kind: service
invariants:
  - subject: "http:api/GET /orders"
    predicate: exists
    why: api declares it serves this route
  - subject: "http:api/GET /orders"
    predicate: calls
    why: web calls it on every page load
environments:
  local:
    adapter: process
    components:
      web: {}
    endpoints:
      api: { host: 127.0.0.1, port: %d, health_path: /health }
    grants:
      net.http.outbound: true
      net.tcp.connect: true
      net.dns.resolve: true
      config.read.names: true
  blind:
    adapter: process
    components:
      web: {}
    endpoints:
      api: { host: 127.0.0.1, port: %d, health_path: /health }
    grants:
      net.http.outbound: true
      net.tcp.connect: true
      net.dns.resolve: true
`

// api is the server under diagnosis, with a switch for each state of it:
// the contract fault (no /orders), fixed, and fixed but /health broken.
type api struct {
	ordersServed atomic.Bool
	healthBroken atomic.Bool
}

func startSwitchableAPI(t *testing.T) (*api, int) {
	t.Helper()
	state := &api{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/health" && !state.healthBroken.Load():
			_, _ = w.Write([]byte(`{"status":"ok"}`))
		case r.URL.Path == "/orders" && state.ordersServed.Load():
			_, _ = w.Write([]byte(`[]`))
		case r.URL.Path == "/health":
			w.WriteHeader(http.StatusInternalServerError)
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(server.Close)
	_, port, err := net.SplitHostPort(strings.TrimPrefix(server.URL, "http://"))
	if err != nil {
		t.Fatal(err)
	}
	var number int
	fmt.Sscanf(port, "%d", &number)
	return state, number
}

type loop struct {
	t        *testing.T
	manifest string
	state    string
}

func newLoop(t *testing.T) (*loop, *api) {
	t.Helper()
	server, port := startSwitchableAPI(t)
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(fmt.Sprintf(loopFixture, port, port)), 0o600); err != nil {
		t.Fatal(err)
	}
	return &loop{t: t, manifest: path, state: t.TempDir()}, server
}

func (l *loop) diagnose(environment string) model.Investigation {
	l.t.Helper()
	stdout, err := run(l.t, "diagnose", "web", "-f", l.manifest, "--env", environment, "--from", "web",
		"--no-plugins", "--format", "json", "--state-dir", l.state)
	if err != nil {
		l.t.Fatalf("diagnose: %v\n%s", err, stdout)
	}
	var inv model.Investigation
	if err := json.Unmarshal([]byte(stdout), &inv); err != nil {
		l.t.Fatalf("diagnose printed no investigation: %v\n%s", err, stdout)
	}
	return inv
}

func (l *loop) verify(id string, changes ...string) (model.Verification, error) {
	l.t.Helper()
	arguments := []string{"verify", id, "-f", l.manifest, "--no-plugins", "--format", "json", "--state-dir", l.state,
		"--from", "web"}
	for _, change := range changes {
		arguments = append(arguments, "--change", change)
	}
	stdout, err := run(l.t, arguments...)
	var unverified *verificationError
	if err != nil && !errors.As(err, &unverified) {
		l.t.Fatalf("verify: %v\n%s", err, stdout)
	}
	var verification model.Verification
	if err := json.Unmarshal([]byte(stdout), &verification); err != nil {
		l.t.Fatalf("verify printed no verification: %v\n%s", err, stdout)
	}
	if (err == nil) != (verification.Verdict == model.VerificationVerified) {
		l.t.Errorf("verdict %s, exit error %v: exit 0 is for verified alone", verification.Verdict, err)
	}
	return verification, err
}

// TestTheLoopEndToEnd: the real commands, real probes and a real capture
// of this process's environment, against a real server that is diagnosed,
// then changed, then verified — one subtest per verdict the server can be
// made to give. LLM_PROVIDER=none throughout: nothing needed a model.
func TestTheLoopEndToEnd(t *testing.T) {
	t.Setenv("LLM_PROVIDER", "none")
	const fix = "commit:9f2c4e1"

	t.Run("a fix that fixes it is verified", func(t *testing.T) {
		loop, server := newLoop(t)
		inv := loop.diagnose("local")
		if inv.Diagnosis == nil || inv.Diagnosis.RootSubject != "http:api/GET /orders" {
			t.Fatalf("the contract fault was not diagnosed: %+v", inv.Diagnosis)
		}
		if reason := inv.Diagnosis.Confidence.Verified.Reason; !strings.Contains(reason, "culprit verify "+inv.ID) {
			t.Errorf("the verified criterion does not say how to verify: %s", reason)
		}
		server.ordersServed.Store(true)
		verification, _ := loop.verify(inv.ID, fix)
		if verification.Verdict != model.VerificationVerified {
			t.Fatalf("verdict %s: %s", verification.Verdict, verification.Reason)
		}
		// Exactly the investigation's readings, each measured twice now.
		if len(verification.Reran) != len(inv.Readings) {
			t.Fatalf("%d re-runs for %d readings", len(verification.Reran), len(inv.Readings))
		}
		for index, rerun := range verification.Reran {
			original := inv.Readings[index]
			if rerun.ReadingID != original.ID || rerun.ProbeID != original.Reading.ProbeID ||
				rerun.Target != original.Reading.Target {
				t.Errorf("re-run %d is %s %s on %s; the investigation's is %s %s on %s", index,
					rerun.ReadingID, rerun.ProbeID, rerun.Target, original.ID, original.Reading.ProbeID, original.Reading.Target)
			}
			for _, run := range rerun.Runs {
				if !run.TakenAt.After(*inv.ClosedAt) {
					t.Errorf("re-run of %s holds a reading taken %s, before the investigation closed", rerun.ReadingID, run.TakenAt)
				}
			}
		}
		// Kept, append-only, beside the investigation.
		kept, _ := filepath.Glob(filepath.Join(loop.state, "investigations", inv.ID, "verifications", "*.json"))
		if len(kept) != 1 {
			t.Errorf("%d verifications kept, want 1", len(kept))
		}
	})

	t.Run("a fix that is an action, in words, is verified and recorded as one", func(t *testing.T) {
		loop, server := newLoop(t)
		inv := loop.diagnose("local")
		server.ordersServed.Store(true)
		verification, _ := loop.verify(inv.ID, "action: restarted the orders route's handler")
		if verification.Verdict != model.VerificationVerified {
			t.Fatalf("verdict %s: %s", verification.Verdict, verification.Reason)
		}
		named := verification.AppliedChange
		if len(named) != 1 || named[0].Kind != model.ChangeAction ||
			named[0].Description != "restarted the orders route's handler" || named[0].Ref != "" {
			t.Errorf("the change is recorded as %+v, want the action in its own words", named)
		}
	})

	t.Run("a wrong fix is not_resolved", func(t *testing.T) {
		loop, _ := newLoop(t)
		inv := loop.diagnose("local")
		verification, _ := loop.verify(inv.ID, fix)
		if verification.Verdict != model.VerificationNotResolved {
			t.Fatalf("verdict %s: %s", verification.Verdict, verification.Reason)
		}
	})

	t.Run("a fix that breaks what passed is regressed", func(t *testing.T) {
		loop, server := newLoop(t)
		inv := loop.diagnose("local")
		server.ordersServed.Store(true)
		server.healthBroken.Store(true)
		verification, _ := loop.verify(inv.ID, fix)
		if verification.Verdict != model.VerificationRegressed {
			t.Fatalf("verdict %s: %s", verification.Verdict, verification.Reason)
		}
	})

	t.Run("a change underneath is changed_underneath", func(t *testing.T) {
		loop, server := newLoop(t)
		inv := loop.diagnose("local")
		server.ordersServed.Store(true)
		// A config key appears in web's environment: nothing named explains it.
		t.Setenv("CULPRIT_LOOP_UNRELATED_FLAG", "on")
		verification, _ := loop.verify(inv.ID, fix)
		if verification.Verdict != model.VerificationChangedUnderneath {
			t.Fatalf("verdict %s: %s", verification.Verdict, verification.Reason)
		}
		if !strings.Contains(verification.Reason, "CULPRIT_LOOP_UNRELATED_FLAG in web's configuration") {
			t.Errorf("the reason does not name the change underneath: %s", verification.Reason)
		}
		// Naming it explains it.
		verification, _ = loop.verify(inv.ID, fix, "config:web/CULPRIT_LOOP_UNRELATED_FLAG")
		if verification.Verdict != model.VerificationVerified {
			t.Fatalf("with the change named, verdict %s: %s", verification.Verdict, verification.Reason)
		}
	})

	t.Run("no change named is inconclusive", func(t *testing.T) {
		loop, server := newLoop(t)
		inv := loop.diagnose("local")
		server.ordersServed.Store(true)
		verification, _ := loop.verify(inv.ID)
		if verification.Verdict != model.VerificationInconclusive || !strings.Contains(verification.Reason, "no change was named") {
			t.Fatalf("verdict %s: %s", verification.Verdict, verification.Reason)
		}
	})

	t.Run("no record of before is inconclusive, and the investigation says so", func(t *testing.T) {
		loop, server := newLoop(t)
		inv := loop.diagnose("blind")
		reason := inv.Diagnosis.Confidence.Verified.Reason
		if !strings.Contains(reason, "no record of the environment before") || !strings.Contains(reason, "config.read.names") {
			t.Errorf("the investigation does not say why it has no before: %s", reason)
		}
		server.ordersServed.Store(true)
		verification, _ := loop.verify(inv.ID, fix)
		if verification.Verdict != model.VerificationInconclusive || verification.BeforeCapture != nil {
			t.Fatalf("verdict %s (before %v): %s", verification.Verdict, verification.BeforeCapture, verification.Reason)
		}
	})
}

// TestWhatDiagnoseKeepsIsPrivateAndComplete: the record covers every
// reading, the capture before is a sealed envelope, and on Unix none of
// it is readable by anyone but its owner — a capture can carry a value
// config.read.values allowlists.
func TestWhatDiagnoseKeepsIsPrivateAndComplete(t *testing.T) {
	loop, _ := newLoop(t)
	inv := loop.diagnose("local")
	dir := filepath.Join(loop.state, "investigations", inv.ID)
	var record verify.Record
	if err := readJSON(filepath.Join(dir, "record.json"), &record); err != nil {
		t.Fatal(err)
	}
	if err := record.Check(inv); err != nil {
		t.Fatalf("the record kept does not match the investigation printed: %v", err)
	}
	if record.Vantage != "web" || record.BeforeCapture == "" {
		t.Errorf("record vantage %q, before %q", record.Vantage, record.BeforeCapture)
	}
	for _, name := range []string{"investigation.json", "record.json", "before.json"} {
		info, err := os.Stat(filepath.Join(dir, name))
		if err != nil {
			t.Fatal(err)
		}
		if mode := info.Mode().Perm(); runtime.GOOS != "windows" && mode != 0o600 {
			t.Errorf("%s is %o, want 600", name, mode)
		}
	}
}

func TestVerifyRefusesWhatItCannotUse(t *testing.T) {
	loop, _ := newLoop(t)
	diagnosed := loop.diagnose("local").ID
	for name, arguments := range map[string][]string{
		"another vantage than the diagnosis's": {"verify", diagnosed, "--from", "api", "--change", "commit:9f2c4e1",
			"--state-dir", loop.state, "-f", loop.manifest, "--no-plugins"},
		"no vantage, where the diagnosis had one": {"verify", diagnosed, "--change", "commit:9f2c4e1",
			"--state-dir", loop.state, "-f", loop.manifest, "--no-plugins"},
		"an id that is not one":       {"verify", "../../etc", "--state-dir", loop.state, "-f", loop.manifest},
		"an investigation not kept":   {"verify", "inv-0000000000000000", "--state-dir", loop.state, "-f", loop.manifest},
		"a change of no known kind":   {"verify", "inv-0000000000000000", "--change", "restart:web", "--state-dir", loop.state},
		"a commit that is not one":    {"verify", "inv-0000000000000000", "--change", "commit:main", "--state-dir", loop.state},
		"an action that says nothing": {"verify", "inv-0000000000000000", "--change", "action:   ", "--state-dir", loop.state},
	} {
		t.Run(name, func(t *testing.T) {
			_, err := run(t, arguments...)
			var unverified *verificationError
			if err == nil || errors.As(err, &unverified) {
				t.Fatalf("err = %v, want the command to refuse (exit 2)", err)
			}
		})
	}
}
