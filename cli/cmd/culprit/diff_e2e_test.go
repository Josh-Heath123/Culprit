package main

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// Phase 30 field 13: "Capture against a docker-compose fixture."
//
// The whole of `culprit diff` against two real Compose projects — a real
// Postgres per environment, real `docker inspect`, real image digests from
// a real registry pull, and INTENT from the real extractors over
// cli/testdata/fixtures/fastapi-orders — driven through the real cobra
// command. Nothing here is recorded or stubbed; that is what
// internal/capture's own tests are for.
//
// Gated on CULPRIT_DOCKER_TESTS=1, because it pulls two images and starts
// four containers. CI sets it (the `cli` job); `just cli-test-docker` sets
// it locally. Skipped rather than failed without it, and the skip says so
// — a skipped end-to-end test must never be mistaken for a passing one.

const demoDir = "../../testdata/demo"

// The three planted secrets from environments/*.yml. None may appear in
// any rendering of any capture or report — acceptance criterion 4.
var plantedInDemo = []string{
	"fixture-db-password-planted",
	"fixture-jwt-signing-key-planted-staging",
	"sk_test_fixture_planted_staging_0123",
	"sk_live_fixture_planted_production_0123",
}

func compose(t *testing.T, project, override string, arguments ...string) string {
	t.Helper()
	argv := append([]string{"compose", "-p", project,
		"-f", filepath.Join(demoDir, "environments", "compose.yml"),
		"-f", filepath.Join(demoDir, "environments", override)}, arguments...)
	output, err := exec.Command("docker", argv...).CombinedOutput()
	if err != nil {
		t.Fatalf("docker %s: %v\n%s", strings.Join(argv, " "), err, output)
	}
	return strings.TrimSpace(string(output))
}

func bringUp(t *testing.T, environment string) string {
	t.Helper()
	project := "culprit-demo-" + environment
	override := environment + ".yml"
	compose(t, project, override, "up", "-d", "--wait")
	t.Cleanup(func() {
		if os.Getenv("CULPRIT_KEEP_DEMO") == "" {
			_ = exec.Command("docker", "compose", "-p", project,
				"-f", filepath.Join(demoDir, "environments", "compose.yml"),
				"-f", filepath.Join(demoDir, "environments", override),
				"down", "-v").Run()
		}
	})
	address := compose(t, project, override, "port", "orders-db", "5432")
	return "postgresql://orders:fixture-db-password-planted@" + address + "/orders?sslmode=disable"
}

func TestEnvironmentDiffAgainstRealContainers(t *testing.T) {
	if os.Getenv("CULPRIT_DOCKER_TESTS") != "1" {
		t.Skip("NOT RUN: set CULPRIT_DOCKER_TESTS=1 to run the Compose end-to-end test (needs Docker, uv, node)")
	}
	for _, tool := range []string{"docker", "uv", "node"} {
		if _, err := exec.LookPath(tool); err != nil {
			t.Fatalf("CULPRIT_DOCKER_TESTS=1 but %s is not on PATH", tool)
		}
	}

	t.Setenv("CULPRIT_DEMO_STAGING_DB_URL", bringUp(t, "staging"))
	t.Setenv("CULPRIT_DEMO_PRODUCTION_DB_URL", bringUp(t, "production"))
	manifest := filepath.Join(demoDir, "culprit.yaml")

	stdout, err := run(t, "diff", "staging", "production", "-f", manifest, "--format", "json")
	var findings *findingsError
	if !errors.As(err, &findings) {
		t.Fatalf("expected findings (exit 1), got %v", err)
	}
	var report struct {
		Divergences []struct {
			Kind      string `json:"kind"`
			Subject   string `json:"subject"`
			Predicate string `json:"predicate"`
			Severity  string `json:"severity"`
			Right     struct {
				Environment string `json:"environment"`
			} `json:"right"`
		} `json:"divergences"`
		Environments []struct {
			Name    string `json:"name"`
			Refused []struct {
				Capability string `json:"capability"`
			} `json:"refused"`
		} `json:"environments"`
	}
	if err := json.Unmarshal([]byte(stdout), &report); err != nil {
		t.Fatalf("the report is not JSON: %v\n%s", err, stdout)
	}

	got := map[string]string{}
	for _, finding := range report.Divergences {
		got[finding.Kind+" | "+finding.Subject+" | "+finding.Predicate+" | "+finding.Right.Environment] =
			finding.Severity
	}
	// The exact set: acceptance criteria 1, 2 (twice — the version and the
	// table) and 3 (twice — the digest and the tag it came from), and
	// nothing else.
	want := map[string]string{
		"intent_vs_configured | config:orders-api/JWT_SECRET_KEY | exists | production":     "breaks_request_path",
		"intent_vs_configured | component:orders-api | migration_head | production":         "breaks_request_path",
		"intent_vs_configured | schema:orders-db/public.order_lines | columns | production": "breaks_request_path",
		"env_vs_env | image:orders-api | digest | staging":                                  "degrades",
		"env_vs_env | image:orders-api | reference | staging":                               "degrades",
	}
	for key, severity := range want {
		if got[key] != severity {
			t.Errorf("expected %s at %s, got %q", key, severity, got[key])
		}
	}
	if len(got) != len(want) {
		t.Errorf("expected exactly %d findings, got %d:\n%v", len(want), len(got), got)
	}

	// Criterion 4: values were not granted, and the report says so.
	for _, environment := range report.Environments {
		refused := false
		for _, refusal := range environment.Refused {
			refused = refused || refusal.Capability == "config.read.values"
		}
		if !refused {
			t.Errorf("%s: the report does not say config values were refused", environment.Name)
		}
	}

	// ...and no value appears in any rendering of any of it.
	outputs := map[string]string{"diff json": stdout}
	for _, format := range []string{"text", "sarif", "junit"} {
		rendered, _ := run(t, "diff", "staging", "production", "-f", manifest, "--format", format)
		outputs["diff "+format] = rendered
	}
	envelopePath := filepath.Join(t.TempDir(), "production.capture.json")
	if _, err := run(t, "env", "capture", "production", "-f", manifest, "-o", envelopePath); err != nil {
		t.Fatalf("env capture: %v", err)
	}
	envelopeText, _ := os.ReadFile(envelopePath)
	outputs["envelope"] = string(envelopeText)
	var envelope struct {
		Payload string `json:"payload"`
	}
	_ = json.Unmarshal(envelopeText, &envelope)
	payload, _ := base64.StdEncoding.DecodeString(envelope.Payload)
	outputs["envelope payload"] = string(payload)
	captureText, _ := run(t, "env", "capture", "staging", "-f", manifest, "--format", "text")
	outputs["capture text"] = captureText

	for name, output := range outputs {
		for _, secret := range plantedInDemo {
			if strings.Contains(output, secret) {
				t.Errorf("%s contains the planted value %q", name, secret)
			}
		}
	}

	// A saved envelope stands in for a live environment, verified first.
	fromFile, err := run(t, "diff", "staging", envelopePath, "-f", manifest, "--format", "json")
	if !errors.As(err, &findings) || !strings.Contains(fromFile, "JWT_SECRET_KEY") {
		t.Errorf("diffing against a saved capture did not reproduce the finding: %v", err)
	}

	// A least-privilege capture role: no table privileges at all. The table
	// list must still be complete (pg_catalog, not information_schema), and
	// the migration version, which does need SELECT on alembic_version,
	// must be reported unread — never read as "no revision", which is what
	// pgx's deferred query error made it until a real role showed it.
	compose(t, "culprit-demo-staging", "staging.yml", "exec", "-T", "orders-db",
		"psql", "-U", "orders", "-d", "orders", "-c",
		"DROP ROLE IF EXISTS capture_probe; CREATE ROLE capture_probe LOGIN PASSWORD 'probe'")
	stagingURL := os.Getenv("CULPRIT_DEMO_STAGING_DB_URL")
	t.Setenv("CULPRIT_DEMO_STAGING_DB_URL",
		strings.Replace(stagingURL, "orders:fixture-db-password-planted@", "capture_probe:probe@", 1))
	probed, err := run(t, "env", "capture", "staging", "-f", manifest, "--format", "text")
	if err != nil {
		t.Fatalf("capture with a least-privilege role: %v", err)
	}
	if !strings.Contains(probed, "schema:orders-db/public.order_lines ") ||
		!strings.Contains(probed, "schema:orders-db/public.orders ") {
		t.Errorf("a least-privilege role lost tables from the schema:\n%s", probed)
	}
	if strings.Contains(probed, "migration_head") ||
		!strings.Contains(probed, "SELECT on alembic_version") {
		t.Errorf("an unreadable migration version was not reported as unread:\n%s", probed)
	}
	t.Setenv("CULPRIT_DEMO_STAGING_DB_URL", stagingURL)

	// An altered one is refused, as an execution error rather than a finding.
	tampered := strings.Replace(string(envelopeText), `"sha256": "`, `"sha256": "0`, 1)
	tamperedPath := filepath.Join(t.TempDir(), "tampered.json")
	_ = os.WriteFile(tamperedPath, []byte(tampered), 0o600)
	if _, err := run(t, "diff", "staging", tamperedPath, "-f", manifest); err == nil ||
		errors.As(err, &findings) {
		t.Errorf("a tampered capture was not refused as an error: %v", err)
	}
}
