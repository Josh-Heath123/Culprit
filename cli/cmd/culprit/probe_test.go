package main

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// `culprit probe` at the command level.
//
// The properties worth asserting here are the ones a user meets first:
// that an ungranted run refuses instead of dialling, that a bad target is
// rejected before any work happens, and that the exit code means what
// every other command's exit code means.

const probeFixture = `version: 1
components:
  - name: orders-api
    kind: service
environments:
  staging:
    adapter: process
    components:
      orders-api: {}
    grants:
      net.dns.resolve: true
`

func writeProbeFixture(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(probeFixture), 0o600); err != nil {
		t.Fatalf("writing fixture: %v", err)
	}
	return path
}

func TestProbeListShowsTheWholeCatalogue(t *testing.T) {
	stdout, err := run(t, "probe", "--list")
	if err != nil {
		t.Fatalf("probe --list: %v", err)
	}
	for _, id := range []string{
		"probe.net.dns_resolve", "probe.net.tcp_connect", "probe.net.tls_validity",
		"probe.http.reachable", "probe.http.route_conformance",
		"probe.http.schema_conformance", "probe.auth.token_shape",
		"probe.auth.propagation", "probe.db.connect", "probe.db.schema_conformance",
		"probe.config.present", "probe.dep.version", "probe.edge.impedance",
	} {
		if !strings.Contains(stdout, id) {
			t.Errorf("%s is missing from --list:\n%s", id, stdout)
		}
	}
}

// TestProbeListNamesEveryProbesCapabilities matters because it is how a
// user decides what to grant before running anything.
func TestProbeListNamesEveryProbesCapabilities(t *testing.T) {
	stdout, err := run(t, "probe", "--list")
	if err != nil {
		t.Fatalf("probe --list: %v", err)
	}
	if !strings.Contains(stdout, "net.http.outbound") {
		t.Errorf("--list does not say which probes make HTTP requests:\n%s", stdout)
	}
	if !strings.Contains(stdout, "needs: none") {
		t.Errorf("--list should say when a probe needs nothing:\n%s", stdout)
	}
}

func TestProbeRejectsATargetThatIsNotASubjectURI(t *testing.T) {
	path := writeProbeFixture(t)
	_, err := run(t, "probe", "the orders api", "-f", path, "--env", "staging")
	if err == nil {
		t.Fatal("a free-text target was accepted")
	}
	var findings *findingsError
	if errors.As(err, &findings) {
		t.Fatal("a malformed target was reported as a finding rather than an error")
	}
	if !strings.Contains(err.Error(), "subject URI") {
		t.Errorf("the error should explain what a target looks like, got: %v", err)
	}
}

func TestProbeRefusesWhatIsNotGrantedAndSaysWhich(t *testing.T) {
	path := writeProbeFixture(t)
	// The fixture grants net.dns.resolve and nothing else, so tcp_connect
	// must refuse. Nothing is dialled: there is no listener on this host
	// for the probe to reach even if it tried.
	stdout, err := run(t, "probe", "component:orders-api", "-f", path,
		"--env", "staging", "-p", "probe.net.tcp_connect",
		"--input", "host=127.0.0.1", "--input", "port=9")
	if err != nil {
		t.Fatalf("a refusal is not a finding and must exit zero, got %v", err)
	}
	if !strings.Contains(stdout, "REFUSED") {
		t.Errorf("expected a refusal section:\n%s", stdout)
	}
	if !strings.Contains(stdout, "net.tcp.connect") {
		t.Errorf("the refusal must name the missing capability:\n%s", stdout)
	}
}

// TestProbeWithNoEnvironmentGrantsNothing guards against ambient
// authority: running probes against an unspecified target with whatever
// access happens to be lying around is how a diagnostic tool becomes an
// incident.
func TestProbeWithNoEnvironmentGrantsNothing(t *testing.T) {
	path := writeProbeFixture(t)
	stdout, err := run(t, "probe", "component:orders-api", "-f", path,
		"-p", "probe.net.dns_resolve", "--input", "host=example.com")
	if err != nil {
		t.Fatalf("probe: %v", err)
	}
	if !strings.Contains(stdout, "REFUSED") {
		t.Errorf("without --env nothing should be granted:\n%s", stdout)
	}
}

func TestProbeRequiresATarget(t *testing.T) {
	path := writeProbeFixture(t)
	_, err := run(t, "probe", "-f", path)
	if err == nil {
		t.Fatal("probe with no target was accepted")
	}
	if !strings.Contains(err.Error(), "--list") {
		t.Errorf("the error should point at --list, got: %v", err)
	}
}

func TestProbeRejectsAMalformedInput(t *testing.T) {
	path := writeProbeFixture(t)
	_, err := run(t, "probe", "component:orders-api", "-f", path,
		"--env", "staging", "-p", "probe.net.dns_resolve", "--input", "hostexample.com")
	if err == nil {
		t.Fatal("a malformed --input was accepted; the probe would have run " +
			"without the input the user thought they gave it")
	}
}

func TestProbeJSONOutputCarriesRefusals(t *testing.T) {
	path := writeProbeFixture(t)
	stdout, err := run(t, "probe", "component:orders-api", "-f", path,
		"--env", "staging", "-p", "probe.db.connect", "--format", "json", "--no-plugins")
	if err != nil {
		t.Fatalf("probe: %v", err)
	}
	// A no-grant run that produced an empty, clean-looking report was a
	// real defect in Phase 30's first audit. The refusals must be in the
	// machine-readable output too, not only the text one.
	if !strings.Contains(stdout, "refused") {
		t.Errorf("JSON output carries no refusals:\n%s", stdout)
	}
	if strings.Contains(stdout, "postgresql://reader@db/orders") {
		t.Errorf("the JSON output echoed a connection string:\n%s", stdout)
	}
}

func TestRepeatingAnInputBuildsAList(t *testing.T) {
	inputs, err := parseInputs([]string{
		"url=http://x/y", "expect_fields=sku", "expect_fields=quantity", "port=443",
	})
	if err != nil {
		t.Fatalf("parseInputs: %v", err)
	}
	fields, ok := inputs["expect_fields"].([]any)
	if !ok {
		t.Fatalf("expect_fields = %#v, want a list", inputs["expect_fields"])
	}
	if len(fields) != 2 || fields[0] != "sku" || fields[1] != "quantity" {
		t.Errorf("expect_fields = %#v, want [sku quantity] in order", fields)
	}
	if inputs["port"] != 443 {
		t.Errorf("port = %#v, want the int 443", inputs["port"])
	}
	if inputs["url"] != "http://x/y" {
		t.Errorf("a single value should not become a list, got %#v", inputs["url"])
	}
}

// A fixture whose database is reached the way field 12 requires: by the
// name culprit.yaml gives (`dsn_env`), never by a DSN on the command line.
const databaseProbeFixture = `version: 1
components:
  - name: orders-api
    kind: service
    connections:
      - to: orders-db
        kind: sql
  - name: orders-db
    kind: database
environments:
  staging:
    adapter: process
    components:
      orders-api:
        database:
          dsn_env: CULPRIT_TEST_ORDERS_DSN
          name: orders-db
    grants:
      db.metadata.read: true
`

// TestAFailingDatabaseProbeNeverPrintsTheDSN is Phase 31.1 field 12's
// required test: "a fixture DSN's password is absent from the text and
// JSON output of a *failing* database probe, because failure is where
// credentials escape" (standing invariant 11).
//
// It runs the real command end to end — culprit.yaml, the environment
// variable it names, the capture PostgresReader — against a port nothing
// listens on, so both probes genuinely fail to reach the database rather
// than being refused before they try. Both formats are checked, because
// Phase 31's own audit found a password in the one format nobody looked
// at.
func TestAFailingDatabaseProbeNeverPrintsTheDSN(t *testing.T) {
	const password = "hunter2-fixture-password"
	const dsn = "postgresql://orders_reader:" + password + "@127.0.0.1:1/orders"
	t.Setenv("CULPRIT_TEST_ORDERS_DSN", dsn)

	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(databaseProbeFixture), 0o600); err != nil {
		t.Fatalf("writing fixture: %v", err)
	}

	for _, format := range []string{"text", "json"} {
		stdout, err := run(t, "probe", "schema:orders-db/public.orders", "-f", path,
			"--env", "staging", "--no-plugins", "--format", format,
			"-p", "probe.db.connect", "-p", "probe.db.schema_conformance",
			"--timeout", "3s")

		var findings *findingsError
		if !errors.As(err, &findings) {
			t.Fatalf("%s: want a failing reading (exit 1), got err=%v\n%s", format, err, stdout)
		}
		for _, needle := range []string{password, dsn, "orders_reader"} {
			if strings.Contains(stdout, needle) {
				t.Errorf("%s output carries %q:\n%s", format, needle, stdout)
			}
		}
		// The failure must still say what failed, or the test passes for
		// a report that says nothing.
		if !strings.Contains(stdout, "orders-db") {
			t.Errorf("%s output does not name the database it failed to reach:\n%s", format, stdout)
		}
	}
}
