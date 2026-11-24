// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package verify

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	capturepkg "github.com/josh-heath123/culprit/cli/internal/capture"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Q42. A fix that recreates the container culprit runs in gives it a new
// hostname, a random id. Shaped, that id was opaque, numeric or a duration
// depending on its digits, so about 0.8% of recreations recorded a HOSTNAME
// difference nobody made — and turned a correct fix into changed_underneath.
// These captures go through the real process adapter and the real capture,
// so the test holds the rule and the comparison together.

const identityManifest = `
version: 1
components:
  - name: order-service
environments:
  local:
    adapter: process
    grants: {config.read.names: true}
    components:
      order-service: {}
`

// processCapture captures order-service's environment as the process
// adapter does, with the given hostname as the OS would report it.
func processCapture(t *testing.T, id, hostname string, environ ...string) model.CaptureBundle {
	t.Helper()
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(identityManifest), 0o600); err != nil {
		t.Fatal(err)
	}
	manifest, err := extract.LoadManifest(path)
	if err != nil {
		t.Fatal(err)
	}
	bundle, err := capturepkg.Run(context.Background(), capturepkg.Options{
		Manifest: manifest, Environment: "local", Now: clock, Version: "test",
		Environ:   func() []string { return environ },
		Hostname:  func() (string, error) { return hostname, nil },
		LookupEnv: func(string) (string, bool) { return "", false },
	})
	if err != nil {
		t.Fatal(err)
	}
	bundle.CaptureID = id
	return bundle
}

func TestARecreatedContainersHostnameIsNoDifference(t *testing.T) {
	const was = "3f9a2b7c1d0e" // classified opaque: it has a letter
	for _, now := range []string{
		"123456789012", // all digits: numeric
		"12345678901d", // digits and a d: a duration
	} {
		t.Run(now, func(t *testing.T) {
			before := processCapture(t, "cap-before", was, "HOSTNAME="+was, "PORT=8001")
			after := processCapture(t, "cap-after", now, "HOSTNAME="+now, "PORT=8001")
			if differences := Differences(before, after); len(differences) != 0 {
				t.Errorf("a new hostname was counted as a change: %+v", differences)
			}
		})
	}
}

// TestTheSameChangeOnAnotherKeyIsStillADifference keeps the detector
// honest: the rule hides the runtime's identity, not every value change.
func TestTheSameChangeOnAnotherKeyIsStillADifference(t *testing.T) {
	const was, now, hostname = "3f9a2b7c1d0e", "123456789012", "orders-host"
	before := processCapture(t, "cap-before", hostname, "BUILD_ID="+was)
	after := processCapture(t, "cap-after", hostname, "BUILD_ID="+now)
	differences := Differences(before, after)
	if len(differences) != 1 || differences[0].Subject != "config:order-service/BUILD_ID" ||
		differences[0].Predicate != model.PredicateValueShape {
		t.Errorf("differences = %+v, want BUILD_ID's value_shape", differences)
	}
}

// F44-012. The process adapter records the environment it is launched in,
// the launcher's own variables included. Two captures from one kind of
// shell, one nested deeper and started in another directory, differ in
// SHLVL (a counter: one lexical class, F44-011) and PWD (the working
// directory: an OS fact, like the hostname). Neither is a change of
// configuration. (Two absolute paths are one kind of value whatever their
// length, so this holds the comparison; the capture's own test holds that
// PWD is not shaped at all.)
func TestTheLaunchersDepthAndDirectoryAreNoDifference(t *testing.T) {
	shallow := t.TempDir()
	deep := filepath.Join(t.TempDir(),
		"a-directory-nested-well-below-the-first-one", "and-below-that-again-for-length",
		"so-that-its-path-is-a-long-one-of-more-than-a-hundred-and-twenty-eight-characters")
	if err := os.MkdirAll(deep, 0o755); err != nil {
		t.Fatal(err)
	}
	t.Chdir(shallow)
	before := processCapture(t, "cap-before", "orders-host", "SHLVL=1", "PWD="+cwd(t), "PORT=8001")
	t.Chdir(deep)
	after := processCapture(t, "cap-after", "orders-host", "SHLVL=12", "PWD="+cwd(t), "PORT=8001")
	if differences := Differences(before, after); len(differences) != 0 {
		t.Errorf("the launcher's depth or directory was counted as a change: %+v", differences)
	}
}

// TestTheSameChangeOnAVariableThatIsNotTheDirectoryStillCounts keeps the
// rule honest: it hides the directory the OS reports, not every path.
func TestTheSameChangeOnAVariableThatIsNotTheDirectoryStillCounts(t *testing.T) {
	t.Chdir(t.TempDir())
	before := processCapture(t, "cap-before", "orders-host", "APP_DIR=/srv/app", "PWD="+cwd(t))
	after := processCapture(t, "cap-after", "orders-host", "APP_DIR=srv/app", "PWD="+cwd(t))
	differences := Differences(before, after)
	if len(differences) != 1 || differences[0].Subject != "config:order-service/APP_DIR" ||
		differences[0].Predicate != model.PredicateValueShape {
		t.Errorf("differences = %+v, want APP_DIR's value_shape", differences)
	}
}

func cwd(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	return dir
}
