package main

import (
	"bytes"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/check"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The corpus fixtures double as end-to-end fixtures for the command: a
// real culprit.yaml with real policy sections, run through the real
// cobra plumbing.
const faultsDir = "../../testdata/faults"

// run executes the root command in-process and returns stdout and the
// error it finished with.
//
// In-process rather than by building a binary: the exit code is derived
// from the error `main` receives, so a test that asserts on the error is
// asserting on precisely the thing that becomes the exit code, without a
// build step in the middle.
func run(t *testing.T, arguments ...string) (string, error) {
	t.Helper()
	command := newRootCommand()
	var stdout, stderr bytes.Buffer
	command.SetOut(&stdout)
	command.SetErr(&stderr)
	command.SetArgs(arguments)
	err := command.Execute()
	if stderr.Len() > 0 {
		t.Logf("stderr: %s", stderr.String())
	}
	return stdout.String(), err
}

// TestExitCodeContract is Phase 29 field 7, which names the codes
// explicitly: 0 clean, 1 findings, 2 execution error. They are a
// contract with every CI script written against the first release, so
// they are asserted rather than assumed.
func TestExitCodeContract(t *testing.T) {
	t.Run("a clean repository exits zero", func(t *testing.T) {
		_, err := run(t, "check", "-f", filepath.Join(faultsDir, "clean", "culprit.yaml"),
			"--no-plugins")
		if err != nil {
			t.Fatalf("expected a clean exit, got %v", err)
		}
	})

	t.Run("an unreadable manifest is an execution error, not a finding", func(t *testing.T) {
		_, err := run(t, "check", "-f", filepath.Join(faultsDir, "no-such-fixture.yaml"))
		if err == nil {
			t.Fatal("a missing manifest exited zero")
		}
		var findings *findingsError
		if errors.As(err, &findings) {
			// This is the distinction that matters in CI: "your build has
			// a problem" and "the tool could not run" need different
			// alerts, and conflating them makes both useless.
			t.Fatal("a missing manifest was reported as a divergence")
		}
	})

	t.Run("a bad --fail-on fails before doing any work", func(t *testing.T) {
		_, err := run(t, "check", "--fail-on", "catastrophic")
		if err == nil || !strings.Contains(err.Error(), "catastrophic") {
			t.Fatalf("expected a rejection naming the flag value, got %v", err)
		}
	})
}

// TestFailOnThreshold checks which severities each threshold admits.
//
// Asserted against `check.CountAtOrAbove` rather than by running the
// command four times: the flag's whole job is to turn a severity set into
// a count, and testing that directly says what is meant. The `unknown`
// row is the one worth reading — it is above `cosmetic` on purpose, so
// "we could not work out how bad this is" is never quieter than "we
// worked it out and it is trivial".
func TestFailOnThreshold(t *testing.T) {
	findings := []model.Divergence{
		{Severity: model.SeverityBreaksRequestPath},
		{Severity: model.SeverityDegrades},
		{Severity: model.SeverityUnknown},
		{Severity: model.SeverityCosmetic},
		{Severity: model.SeverityBreaksRequestPath, Status: model.StatusSuppressed},
	}

	for _, testCase := range []struct {
		flag  string
		count int
	}{
		{"breaks_request_path", 1},
		{"degrades", 2},
		{"any", 4},
	} {
		t.Run(testCase.flag, func(t *testing.T) {
			threshold, err := parseFailOn(testCase.flag)
			if err != nil {
				t.Fatalf("parseFailOn(%q): %v", testCase.flag, err)
			}
			got := check.CountAtOrAbove(findings, threshold)
			if got != testCase.count {
				t.Errorf("--fail-on=%s counted %d, expected %d",
					testCase.flag, got, testCase.count)
			}
		})
	}

	t.Run("a suppressed finding never fails a build", func(t *testing.T) {
		threshold, _ := parseFailOn("any")
		only := []model.Divergence{{
			Severity: model.SeverityBreaksRequestPath,
			Status:   model.StatusSuppressed,
		}}
		if count := check.CountAtOrAbove(only, threshold); count != 0 {
			t.Errorf("a suppression did not suppress: counted %d", count)
		}
	})
}

func TestOutputFileIsWrittenAndStdoutStaysQuiet(t *testing.T) {
	destination := filepath.Join(t.TempDir(), "culprit.sarif")
	stdout, err := run(t, "check",
		"-f", filepath.Join(faultsDir, "clean", "culprit.yaml"),
		"--no-plugins", "--format", "sarif", "--output", destination)
	if err != nil {
		t.Fatalf("check: %v", err)
	}
	if strings.TrimSpace(stdout) != "" {
		t.Errorf("stdout should be empty when --output is given, got %q", stdout)
	}
	written, err := os.ReadFile(destination)
	if err != nil {
		t.Fatalf("the SARIF file was not written: %v", err)
	}
	if !strings.Contains(string(written), "\"version\": \"2.1.0\"") {
		t.Errorf("the file is not a SARIF log:\n%s", written)
	}
}

// TestTheCheckPathCannotMakeANetworkCall is Phase 29 field 17, made
// executable.
//
// Field 17 says `culprit check` "must never make a network call to a
// model provider, and a test asserts it". The obvious test greps the
// source for provider names, and it is weak: it passes for any provider
// nobody thought to list, and for any call made through a wrapper.
//
// This asserts something much stronger and much simpler to trust. The
// entire check pipeline — extraction, comparison, severity, suppression,
// reporting — is `internal/check` and its transitive dependencies, and
// **that package graph contains no networking package at all.** Not
// `net/http`, not `net`, not `crypto/tls`. A package that does not link a
// socket cannot open one, to a model provider or to anywhere else, and no
// list of vendor names has to be kept up to date for that to stay true.
func TestTheCheckPathCannotMakeANetworkCall(t *testing.T) {
	forbidden := map[string]string{
		"net":        "the pipeline would be able to open a socket",
		"net/http":   "the pipeline would be able to make an HTTP request",
		"crypto/tls": "the pipeline would be able to open a TLS connection",
	}

	output, err := exec.Command("go", "list", "-deps",
		"github.com/josh-heath123/culprit/cli/internal/check").Output()
	if err != nil {
		t.Skipf("go list is unavailable in this environment: %v", err)
	}
	for _, line := range strings.Split(strings.TrimSpace(string(output)), "\n") {
		dependency := strings.TrimSpace(line)
		if reason, bad := forbidden[dependency]; bad {
			t.Errorf("internal/check depends on %s: %s.\n"+
				"Phase 29 field 17 forbids a network call anywhere on this path. "+
				"If a later phase genuinely needs one (Phase 30's environment "+
				"capture will), it belongs in its own package with its own "+
				"capability gate — not linked into the comparator.",
				dependency, reason)
		}
	}
}

// TestNoModelProviderIsLinkedIntoTheBinary is the second half: the
// command as a whole, not just the pipeline.
//
// `cmd/culprit` does link `net` (through os/exec, which the plugin runner
// needs), so the structural argument above cannot be made about the whole
// binary. A name check is the available tool here, and it is worth having
// even though it is the weaker of the two.
func TestNoModelProviderIsLinkedIntoTheBinary(t *testing.T) {
	providers := []string{
		"anthropic", "openai", "generative-ai", "genai", "cohere",
		"voyage", "mistral", "langchain", "google.golang.org/api/aiplatform",
	}

	output, err := exec.Command("go", "list", "-deps",
		"github.com/josh-heath123/culprit/cli/cmd/culprit").Output()
	if err != nil {
		t.Skipf("go list is unavailable in this environment: %v", err)
	}
	listing := strings.ToLower(string(output))
	for _, provider := range providers {
		if strings.Contains(listing, provider) {
			t.Errorf("the culprit binary links %q", provider)
		}
	}
}

// TestTheNetworkBoundaryIsAnAllowlist is D8 as amended 2026-11-03.
//
// Phase 31 replaced a binary-wide ban on `net/http`, because probes exist
// to ask a running service a question (§2.7's `net.http.outbound`). What
// it replaced it with named six packages that must stay off the network,
// so every package NOT on that list was unchecked — internal/capability
// and internal/render then, and every package created after. A check that
// covers only what someone remembered to list looks like a gate and is
// not one (standing invariant 9).
//
// So the list is inverted. The packages ALLOWED each name are written
// down; every other package under cli/internal/ is enumerated by
// `go list ./internal/...` and may link none of them. A package created
// tomorrow is covered the day it exists, with no edit here.
//
// The rule of record: only internal/probe, internal/probe/guardedhttp and
// internal/transport may link net/http; only those, internal/capture and
// internal/capture/dbsession may link net or crypto/tls (Q27 put the
// client and the session in packages of their own).
// Dependencies are transitive (`go list -deps`), so a package that reaches
// the network through another package is caught exactly as if it had
// imported net itself.
func TestTheNetworkBoundaryIsAnAllowlist(t *testing.T) {
	const module = "github.com/josh-heath123/culprit/cli/"
	allowed := map[string]map[string]bool{
		// internal/transport (Phase 33 part 2) is the agent's connection to
		// its control plane: it dials only the configured address, follows
		// no redirect and opens no listener (internal/transport's tests).
		//
		// internal/probe/guardedhttp and internal/capture/dbsession (Q27,
		// ruled 2026-11-12) hold the network use internal/probe and
		// internal/capture already had, in packages of one file each whose
		// exported surface names no network or driver type: narrower, no
		// new reach. probe and capture still link what those two link.
		"net/http": {"internal/probe": true, "internal/probe/guardedhttp": true, "internal/transport": true},
		"net": {"internal/probe": true, "internal/probe/guardedhttp": true, "internal/capture": true,
			"internal/capture/dbsession": true, "internal/transport": true},
		"crypto/tls": {"internal/probe": true, "internal/probe/guardedhttp": true, "internal/capture": true,
			"internal/capture/dbsession": true, "internal/transport": true},
	}
	reasons := map[string]string{
		"net":        "it can open a socket",
		"net/http":   "it can make an HTTP request",
		"crypto/tls": "it can open a TLS connection",
	}

	// The module path, not "./internal/...": this test runs from
	// cmd/culprit, where the relative pattern matches nothing and go list
	// still exits 0 — an empty enumeration that would pass every package.
	listing, err := exec.Command("go", "list", module+"internal/...").Output()
	if err != nil {
		t.Skipf("go list is unavailable in this environment: %v", err)
	}
	packages := strings.Fields(strings.TrimSpace(string(listing)))
	if len(packages) < 2 {
		// An enumeration that found (almost) nothing proves nothing, and a
		// gate that silently checks zero packages is the failure this test
		// exists to prevent.
		t.Fatalf("go list ./internal/... found %d packages; expected the whole tree", len(packages))
	}

	for _, full := range packages {
		pkg := strings.TrimPrefix(full, module)
		output, err := exec.Command("go", "list", "-deps", full).Output()
		if err != nil {
			t.Fatalf("go list -deps %s: %v", full, err)
		}
		for _, line := range strings.Split(strings.TrimSpace(string(output)), "\n") {
			dep := strings.TrimSpace(line)
			permitted, guarded := allowed[dep]
			if !guarded || permitted[pkg] {
				continue
			}
			t.Errorf("%s links %s: %s. Only %s may (D8, amended 2026-11-03). "+
				"Code that computes findings must not reach the network; a "+
				"network client belongs in internal/probe, behind a capability.",
				pkg, dep, reasons[dep], strings.Join(sortedKeys(permitted), " and "))
		}
	}
}

func sortedKeys(set map[string]bool) []string {
	keys := make([]string, 0, len(set))
	for key := range set {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}
