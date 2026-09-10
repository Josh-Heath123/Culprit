package capture

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/report"
)

// Secrets planted in every place an environment can hand one over: a
// DSN's password, a JWT, a provider key, a value in a ConfigMap, and a
// command's stderr. No test output in this file may ever contain one,
// except where a key is explicitly on the config.read.values allowlist.
const (
	plantedPassword = "hunter2-planted-password"
	plantedJWT      = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwbGFudGVkIn0.planted-signature-value"
	plantedStripe   = "sk_live_plantedstripekey0123456789"
)

var clock = time.Date(2026, 9, 10, 12, 0, 0, 0, time.UTC)

// fakeRunner answers commands from a table keyed by the joined argv.
type fakeRunner struct {
	outputs map[string]string
	fail    map[string]RunErrorKind
	seen    []string
}

func (f *fakeRunner) Run(_ context.Context, argv []string) ([]byte, error) {
	joined := strings.Join(argv, " ")
	f.seen = append(f.seen, joined)
	if kind, ok := f.fail[joined]; ok {
		return nil, &RunError{Command: argv[0], Kind: kind}
	}
	if out, ok := f.outputs[joined]; ok {
		return []byte(out), nil
	}
	return nil, &RunError{Command: argv[0], Kind: RunFailed}
}

type fakeDatabase struct {
	schema Schema
	err    error
	dsn    string
}

func (f *fakeDatabase) Read(_ context.Context, dsn string) (Schema, error) {
	f.dsn = dsn
	return f.schema, f.err
}

type fakeNetwork struct{ resolves, reachable bool }

func (f fakeNetwork) Resolves(context.Context, string) bool       { return f.resolves }
func (f fakeNetwork) Reachable(context.Context, string, int) bool { return f.reachable }
func (f fakeNetwork) Certificate(context.Context, string, int, time.Time) string {
	return TLSExpiringSoon
}

func loadManifest(t *testing.T, text string) *extract.Manifest {
	t.Helper()
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	manifest, err := extract.LoadManifest(path)
	if err != nil {
		t.Fatalf("LoadManifest: %v", err)
	}
	return manifest
}

const composeManifest = `
version: 1
components:
  - name: orders-api
    kind: service
environments:
  staging:
    adapter: compose
    compose:
      project: shop
    grants:
      config.read.names: true
      deploy.metadata.read: true
      config.read.values: [orders-api/LOG_LEVEL]
    components:
      orders-api: {}
`

func composeRunner() *fakeRunner {
	inspect := fmt.Sprintf(`[{"Id":"abc","Name":"/shop-orders-api-1","Image":"sha256:local1",
	  "Config":{"Image":"ghcr.io/acme/orders:1.4","Env":[
	    "DATABASE_URL=postgresql://orders:%s@db:5432/orders",
	    "JWT_SECRET_KEY=%s",
	    "STRIPE_API_KEY=%s",
	    "LOG_LEVEL=planted-log-level-value",
	    "EMPTY_ONE=",
	    "PATH=/usr/local/bin:/usr/bin"]}}]`, plantedPassword, plantedJWT, plantedStripe)
	return &fakeRunner{outputs: map[string]string{
		"docker compose -p shop ps -q orders-api":    "abc\n",
		"docker inspect abc":                         inspect,
		"docker image inspect sha256:local1":         `[{"Id":"sha256:local1","RepoDigests":["ghcr.io/acme/orders@sha256:aaaa"]}]`,
		"docker compose -p shop ps -q unknown-thing": "",
	}}
}

func runCapture(t *testing.T, manifest *extract.Manifest, environment string, options Options) model.CaptureBundle {
	t.Helper()
	options.Manifest = manifest
	options.Environment = environment
	options.Now = clock
	options.Version = "test"
	if options.Environ == nil {
		options.Environ = func() []string { return nil }
	}
	if options.LookupEnv == nil {
		options.LookupEnv = func(string) (string, bool) { return "", false }
	}
	if options.Network == nil {
		options.Network = fakeNetwork{resolves: true, reachable: true}
	}
	if options.Database == nil {
		options.Database = &fakeDatabase{}
	}
	bundle, err := Run(context.Background(), options)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	for index, fact := range bundle.Facts {
		if err := fact.Validate(); err != nil {
			t.Fatalf("facts.%d (%s %s) does not validate: %v", index, fact.Subject, fact.Predicate, err)
		}
		if fact.Plane != model.PlaneConfigured || fact.Environment != environment {
			t.Fatalf("facts.%d is not a CONFIGURED fact in %s: %+v", index, environment, fact)
		}
	}
	return bundle
}

func find(bundle model.CaptureBundle, subject, predicate string) (model.Fact, bool) {
	for _, fact := range bundle.Facts {
		if fact.Subject == subject && fact.Predicate == predicate {
			return fact, true
		}
	}
	return model.Fact{}, false
}

func TestComposeCaptureReadsNamesShapesAndImage(t *testing.T) {
	bundle := runCapture(t, loadManifest(t, composeManifest), "staging", Options{Runner: composeRunner()})

	shapeFact, ok := find(bundle, "config:orders-api/DATABASE_URL", model.PredicateValueShape)
	if !ok {
		t.Fatal("no shape for DATABASE_URL")
	}
	shape := *shapeFact.ValueShape
	if shape.Format != model.FormatDSN || shape.Scheme != model.SchemePostgreSQL || !shape.Present {
		t.Errorf("DATABASE_URL shaped as %+v", shape)
	}
	if _, ok := find(bundle, "config:orders-api/DATABASE_URL", PredicateValue); ok {
		t.Error("a value was captured for a key that is not on the allowlist")
	}
	if empty, _ := find(bundle, "config:orders-api/EMPTY_ONE", model.PredicateValueShape); empty.ValueShape.LengthClass != model.LengthEmpty {
		t.Errorf("a present-but-empty key was not shaped as empty: %+v", empty.ValueShape)
	}

	logLevel, ok := find(bundle, "config:orders-api/LOG_LEVEL", PredicateValue)
	if !ok || logLevel.Value != "planted-log-level-value" || logLevel.GrantRef != "config.read.values:orders-api/LOG_LEVEL" {
		t.Errorf("the allowlisted value was not captured with its grant: %+v", logLevel)
	}

	if digest, _ := find(bundle, "image:orders-api", PredicateDigest); digest.Value != "sha256:aaaa" {
		t.Errorf("digest = %v", digest.Value)
	}
	if reference, _ := find(bundle, "image:orders-api", PredicateReference); reference.Value != "ghcr.io/acme/orders:1.4" {
		t.Errorf("reference = %v", reference.Value)
	}
	if _, ok := find(bundle, "image:orders-api", PredicateImageID); ok {
		t.Error("the local image id was emitted alongside a registry digest")
	}

	// Five keys have values that were not allowlisted. One refusal, naming
	// the count, rather than four.
	refusals := 0
	for _, refusal := range bundle.Refused {
		if refusal.Capability == "config.read.values" {
			refusals++
			if !strings.Contains(refusal.Reason, "5 key(s)") {
				t.Errorf("the values refusal does not say how many: %q", refusal.Reason)
			}
		}
	}
	if refusals != 1 {
		t.Errorf("expected one config.read.values refusal, got %+v", bundle.Refused)
	}
}

// TestNothingPlantedLeavesTheCapture is field 12's "a capture bundle is
// safe to attach to a bug report by construction, and there is a test
// asserting that" — and acceptance criterion 4, "with only
// config.read.names granted, values never appear in output".
//
// Every artefact a capture can become is rendered and searched: the
// sealed envelope, its decoded payload, the text view, and a diff report
// in all four formats.
func TestNothingPlantedLeavesTheCapture(t *testing.T) {
	onlyNames := strings.Replace(composeManifest,
		"      config.read.values: [orders-api/LOG_LEVEL]\n", "", 1)
	bundle := runCapture(t, loadManifest(t, onlyNames), "staging", Options{Runner: composeRunner()})

	_, key, _ := ed25519.GenerateKey(nil)
	envelope, err := Seal(bundle, key)
	if err != nil {
		t.Fatal(err)
	}
	envelopeJSON, _ := json.Marshal(envelope)
	payload, _ := base64.StdEncoding.DecodeString(envelope.Payload)

	var text bytes.Buffer
	if err := report.RenderCapture(&text, bundle); err != nil {
		t.Fatal(err)
	}
	outputs := map[string]string{
		"envelope": string(envelopeJSON),
		"payload":  string(payload),
		"text":     text.String(),
	}
	for _, format := range []string{"text", "json", "sarif", "junit"} {
		var rendered bytes.Buffer
		if err := report.Render(&rendered, format, report.Input{
			Bundle: model.CaptureBundle{}, Captures: []model.CaptureBundle{bundle},
		}); err != nil {
			t.Fatal(err)
		}
		outputs["diff report ("+format+")"] = rendered.String()
	}

	for name, output := range outputs {
		for _, secret := range []string{plantedPassword, plantedJWT, plantedStripe, "planted-log-level-value"} {
			if strings.Contains(output, secret) {
				t.Errorf("%s contains %q", name, secret)
			}
		}
	}
	if !strings.Contains(text.String(), "Refused") || !strings.Contains(text.String(), "config values") {
		t.Errorf("the text view does not say values were refused:\n%s", text.String())
	}
}

// TestAGrantedValueReachesThePayloadAndNoRendering: the allowlisted value
// is in the sealed payload, where the comparator needs it, and in no
// human-facing rendering, where it does not belong.
func TestAGrantedValueReachesThePayloadAndNoRendering(t *testing.T) {
	bundle := runCapture(t, loadManifest(t, composeManifest), "staging", Options{Runner: composeRunner()})
	envelope, _ := Seal(bundle, nil)
	payload, _ := base64.StdEncoding.DecodeString(envelope.Payload)
	if !strings.Contains(string(payload), `"value":"planted-log-level-value"`) {
		t.Error("the granted value is not in the payload")
	}
	var text bytes.Buffer
	_ = report.RenderCapture(&text, bundle)
	if strings.Contains(text.String(), "planted-log-level-value") {
		t.Errorf("the granted value was rendered:\n%s", text.String())
	}
}

// TestUngrantedChecksAreRefusedNotOmitted is field 13's grant-enforcement
// test: every check the manifest configures and the grants do not allow
// produces a refusal naming it, and no fact of its kind.
func TestUngrantedChecksAreRefusedNotOmitted(t *testing.T) {
	manifest := loadManifest(t, `
version: 1
components:
  - name: orders-api
environments:
  production:
    adapter: compose
    compose: {project: shop}
    exec:
      pip-freeze: ["docker", "compose", "exec", "orders-api", "pip", "freeze"]
    grants:
      config.read.names: true
      process.exec.allowlist: [pip-freeze]
    components:
      orders-api:
        database: {dsn_env: PROD_DB_URL}
        endpoint: {host: api.example.com, port: 443, tls: true}
        packages: pip-freeze
`)
	runner := composeRunner()
	runner.outputs["docker compose exec orders-api pip freeze"] = "fastapi==0.115.4\n"
	database := &fakeDatabase{schema: Schema{Tables: []TableShape{{Namespace: "public", Table: "orders",
		Columns: map[string]bool{"id": false}}}}}
	bundle := runCapture(t, manifest, "production", Options{
		Runner: runner, Database: database,
		LookupEnv: func(string) (string, bool) { return "postgresql://u:p@h/d", true },
	})

	refused := map[string]string{}
	for _, refusal := range bundle.Refused {
		refused[refusal.Check] = refusal.Capability
	}
	for check, capability := range map[string]string{
		CheckImage:  "deploy.metadata.read",
		CheckSchema: "db.metadata.read",
		CheckDNS:    "net.dns.resolve",
		CheckPort:   "net.tcp.connect",
		CheckTLS:    "net.tls.inspect",
		CheckValues: "config.read.values",
	} {
		if refused[check] != capability {
			t.Errorf("%s was not refused for %s (refused: %+v)", check, capability, bundle.Refused)
		}
	}
	if database.dsn != "" {
		t.Error("the database was contacted without db.metadata.read")
	}
	for _, fact := range bundle.Facts {
		kind, _, _ := model.ParseSubject(fact.Subject)
		if kind == model.KindSchema || kind == model.KindImage || kind == model.KindComponent {
			t.Errorf("a fact for a refused check was emitted: %s %s", fact.Subject, fact.Predicate)
		}
	}
	// The one allowlisted command did run.
	if installed, _ := find(bundle, "dep:orders-api/fastapi", PredicateInstalledVersion); installed.Value != "0.115.4" {
		t.Errorf("installed_version = %v", installed.Value)
	}
	used := map[string]bool{}
	for _, grant := range bundle.Grants {
		used[grant.Capability] = grant.Used
	}
	if !used["config.read.names"] || !used["process.exec.allowlist"] {
		t.Errorf("grants are not recorded as used: %+v", bundle.Grants)
	}
}

func TestDatabaseMetadataBecomesFacts(t *testing.T) {
	manifest := loadManifest(t, `
version: 1
components:
  - name: orders-api
environments:
  staging:
    adapter: process
    grants: {db.metadata.read: true}
    components:
      orders-api:
        database: {dsn_env: STAGING_DB_URL}
`)
	database := &fakeDatabase{schema: Schema{
		HasAlembic:     true,
		MigrationHeads: []string{"0002_add_status"},
		Tables: []TableShape{{Namespace: "public", Table: "orders",
			Columns: map[string]bool{"id": false, "cancelled_at": true}}},
	}}
	bundle := runCapture(t, manifest, "staging", Options{
		Database:  database,
		LookupEnv: func(name string) (string, bool) { return "postgresql://u:p@h/d", name == "STAGING_DB_URL" },
	})
	columns, ok := find(bundle, "schema:orders-api-db/public.orders", model.PredicateColumns)
	if !ok || model.CanonicalJSON(columns.Value) != `["cancelled_at","id"]` {
		t.Errorf("columns = %+v", columns.Value)
	}
	if nullable, _ := find(bundle, "schema:orders-api-db/public.orders.cancelled_at", model.PredicateNullable); nullable.Value != true {
		t.Errorf("nullable = %v", nullable.Value)
	}
	head, _ := find(bundle, "component:orders-api", model.PredicateMigrationHead)
	if model.CanonicalJSON(head.Value) != `["0002_add_status"]` {
		t.Errorf("migration_head = %v", head.Value)
	}
}

func TestADatabaseFailureNamesItsKindAndNothingElse(t *testing.T) {
	manifest := loadManifest(t, `
version: 1
components:
  - name: orders-api
environments:
  staging:
    adapter: process
    grants: {db.metadata.read: true}
    components:
      orders-api:
        database: {dsn_env: STAGING_DB_URL}
`)
	dsn := "postgresql://orders:" + plantedPassword + "@db.internal:5432/orders"
	bundle := runCapture(t, manifest, "staging", Options{
		Database:  &fakeDatabase{err: &DBError{Kind: DBAuthFailed}},
		LookupEnv: func(string) (string, bool) { return dsn, true },
	})
	encoded, _ := json.Marshal(bundle)
	if strings.Contains(string(encoded), plantedPassword) || strings.Contains(string(encoded), "db.internal") {
		t.Errorf("the bundle mentions the connection string:\n%s", encoded)
	}
	if !strings.Contains(string(encoded), string(DBAuthFailed)) {
		t.Errorf("the skip does not say why: %s", encoded)
	}

	unset := runCapture(t, manifest, "staging", Options{})
	if len(unset.Skipped) != 1 || !strings.Contains(unset.Skipped[0].Reason, "STAGING_DB_URL is not set") {
		t.Errorf("an unset dsn_env is not reported by name: %+v", unset.Skipped)
	}
}

func TestKubernetesCaptureReadsTheDeploymentSpec(t *testing.T) {
	manifest := loadManifest(t, `
version: 1
components:
  - name: orders-api
environments:
  production:
    adapter: kubernetes
    kubernetes: {context: prod, namespace: shop}
    grants: {config.read.names: true, deploy.metadata.read: true}
    components:
      orders-api: {container: api}
`)
	deployment := `{"spec":{"selector":{"matchLabels":{"app":"orders"}},"template":{"spec":{"containers":[
	  {"name":"sidecar","image":"envoy:1","env":[]},
	  {"name":"api","image":"ghcr.io/acme/orders:1.4",
	   "env":[{"name":"PORT","value":"8000"},
	          {"name":"DATABASE_URL","valueFrom":{"secretKeyRef":{"name":"db","key":"url"}}}],
	   "envFrom":[{"configMapRef":{"name":"orders-config"}},{"secretRef":{"name":"orders-secrets"}}]}]}}}}`
	base := "kubectl --context prod -n shop "
	runner := &fakeRunner{outputs: map[string]string{
		base + "get deployment orders-api -o json":                                                           deployment,
		base + "get configmap orders-config -o json":                                                         `{"data":{"LOG_LEVEL":"info","STRIPE_URL":"https://api.stripe.com"}}`,
		base + `get secret orders-secrets -o go-template={{range $key, $_ := .data}}{{$key}}{{"\n"}}{{end}}`: "JWT_SECRET_KEY\nSTRIPE_API_KEY\n",
		base + "get pods -l app=orders -o json": `{"items":[{"metadata":{"name":"orders-1"},"status":{"containerStatuses":[
		  {"name":"api","imageID":"docker-pullable://ghcr.io/acme/orders@sha256:bbbb"}]}}]}`,
	}}
	bundle := runCapture(t, manifest, "production", Options{Runner: runner})

	for key, wantType := range map[string]model.ValueType{
		"PORT":           model.TypeString,
		"DATABASE_URL":   model.TypeUnknown, // valueFrom: set, unreadable
		"LOG_LEVEL":      model.TypeString,  // from the ConfigMap
		"JWT_SECRET_KEY": model.TypeUnknown, // from the Secret: key only
	} {
		fact, ok := find(bundle, "config:orders-api/"+key, model.PredicateValueShape)
		if !ok || fact.ValueShape.Type != wantType || !fact.ValueShape.Present {
			t.Errorf("%s: %+v", key, fact.ValueShape)
		}
	}
	if digest, _ := find(bundle, "image:orders-api", PredicateDigest); digest.Value != "sha256:bbbb" {
		t.Errorf("digest = %v", digest.Value)
	}
	if len(bundle.Skipped) != 0 {
		t.Errorf("a complete enumeration recorded skips: %+v", bundle.Skipped)
	}
}

// TestAnIncompleteEnumerationSaysSo: when a Secret's keys cannot be
// listed, the capture records that the environment was not seen whole,
// which is what stops the comparator concluding a key is missing.
func TestAnIncompleteEnumerationSaysSo(t *testing.T) {
	manifest := loadManifest(t, `
version: 1
components:
  - name: orders-api
environments:
  production:
    adapter: kubernetes
    grants: {config.read.names: true}
    components:
      orders-api: {}
`)
	runner := &fakeRunner{outputs: map[string]string{
		"kubectl get deployment orders-api -o json": `{"spec":{"template":{"spec":{"containers":[
		  {"name":"api","image":"x","envFrom":[{"secretRef":{"name":"locked"}}]}]}}}}`,
	}}
	bundle := runCapture(t, manifest, "production", Options{Runner: runner})
	if len(bundle.Skipped) != 1 || bundle.Skipped[0].Want != string(model.WantConfigKeys) ||
		!strings.Contains(bundle.Skipped[0].Reason, "no key is judged missing") {
		t.Errorf("an incomplete enumeration was not recorded: %+v", bundle.Skipped)
	}
}

func TestProcessAndExecAdapters(t *testing.T) {
	manifest := loadManifest(t, `
version: 1
components:
  - name: orders-api
  - name: worker
environments:
  ci:
    adapter: process
    grants: {config.read.names: true}
    components:
      orders-api: {}
  heroku:
    adapter: exec
    exec:
      print-env: ["heroku", "config", "--shell", "-a", "worker"]
    grants:
      config.read.names: true
      process.exec.allowlist: [print-env]
    components:
      worker: {env_command: print-env}
`)
	process := runCapture(t, manifest, "ci", Options{
		Environ: func() []string { return []string{"PORT=8000", "NOT AN ASSIGNMENT"} },
	})
	if _, ok := find(process, "config:orders-api/PORT", model.PredicateExists); !ok {
		t.Error("the process adapter did not read its own environment")
	}

	for name, output := range map[string]string{
		"NUL-delimited (env -0)": "REDIS_URL=rediss://h:6380\x00QUEUE=jobs\x00",
		"a JSON object":          `{"REDIS_URL": "rediss://h:6380", "QUEUE": "jobs"}`,
	} {
		t.Run(name, func(t *testing.T) {
			runner := &fakeRunner{outputs: map[string]string{"heroku config --shell -a worker": output}}
			execBundle := runCapture(t, manifest, "heroku", Options{Runner: runner})
			redis, ok := find(execBundle, "config:worker/REDIS_URL", model.PredicateValueShape)
			if !ok || redis.ValueShape.Scheme != model.SchemeRedisTLS {
				t.Errorf("REDIS_URL = %+v", redis.ValueShape)
			}
			if _, ok := find(execBundle, "config:worker/QUEUE", model.PredicateExists); !ok {
				t.Error("QUEUE was not read")
			}
			if len(execBundle.Skipped) != 0 {
				t.Errorf("a clean parse recorded gaps: %+v", execBundle.Skipped)
			}
		})
	}
}

// TestAMultiLineValueCannotBecomeAKey is the invariant audit's blocking
// finding, as a test. `printenv` prints a PEM key across several lines,
// and the last line of its base64 body — `QUJDREVGRw==` here — looks
// exactly like a variable assignment. Read line by line, a fragment of
// the key became a subject, and subjects are never masked. Line-delimited
// output is now refused outright, and nothing from it survives anywhere.
func TestAMultiLineValueCannotBecomeAKey(t *testing.T) {
	manifest := loadManifest(t, `
version: 1
components:
  - name: worker
environments:
  heroku:
    adapter: exec
    exec:
      print-env: ["printenv"]
    grants:
      config.read.names: true
      process.exec.allowlist: [print-env]
    components:
      worker: {env_command: print-env}
`)
	fragment := "QUJDREVGRw"
	printenv := "PORT=8000\nSIGNING_KEY=-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkq\n" +
		fragment + "==\n-----END PRIVATE KEY-----\n"
	bundle := runCapture(t, manifest, "heroku", Options{
		Runner: &fakeRunner{outputs: map[string]string{"printenv": printenv}},
	})
	encoded, _ := json.Marshal(bundle)
	if strings.Contains(string(encoded), fragment) || strings.Contains(string(encoded), "MIIEvQ") {
		t.Fatalf("a fragment of a multi-line secret reached the capture:\n%s", encoded)
	}
	if len(bundle.Facts) != 0 {
		t.Errorf("line-delimited output was read: %+v", bundle.Facts)
	}
	if len(bundle.Skipped) != 1 || !strings.Contains(bundle.Skipped[0].Reason, "env -0") {
		t.Errorf("the refusal does not say what to do instead: %+v", bundle.Skipped)
	}
}

func TestEndpointChecks(t *testing.T) {
	manifest := loadManifest(t, `
version: 1
components:
  - name: orders-api
environments:
  staging:
    adapter: process
    grants: {net.dns.resolve: true, net.tcp.connect: true, net.tls.inspect: true}
    components:
      orders-api:
        endpoint: {host: api.example.com, port: 443, tls: true}
`)
	bundle := runCapture(t, manifest, "staging", Options{Network: fakeNetwork{resolves: true, reachable: false}})
	for predicate, want := range map[string]any{
		PredicateDNSResolves:    true,
		PredicatePortReachable:  false,
		PredicateTLSCertificate: TLSExpiringSoon,
	} {
		if fact, _ := find(bundle, "component:orders-api", predicate); fact.Value != want {
			t.Errorf("%s = %v, want %v", predicate, fact.Value, want)
		}
	}
}

func TestClassifyExpiry(t *testing.T) {
	for _, testCase := range []struct {
		notAfter time.Time
		want     string
	}{
		{clock.Add(-time.Second), TLSExpired},
		{clock, TLSExpired},
		{clock.Add(24 * time.Hour), TLSExpiringSoon},
		{clock.Add(30 * 24 * time.Hour), TLSExpiringSoon},
		{clock.Add(31 * 24 * time.Hour), TLSValid},
	} {
		if got := classifyExpiry(testCase.notAfter, clock); got != testCase.want {
			t.Errorf("%s: %s, want %s", testCase.notAfter.Sub(clock), got, testCase.want)
		}
	}
}

func TestParsePackages(t *testing.T) {
	pip, ok := parsePackages([]byte("FastAPI==0.115.4\n-e git+https://x#egg=y\nlocal @ file:///tmp/x\n# comment\n"))
	if !ok || pip["fastapi"] != "0.115.4" || len(pip) != 1 {
		t.Errorf("pip freeze: %v", pip)
	}
	npm, ok := parsePackages([]byte(`{"dependencies":{"react":{"version":"18.3.1"}}}`))
	if !ok || npm["react"] != "18.3.1" {
		t.Errorf("npm ls: %v", npm)
	}
	if _, ok := parsePackages([]byte("nothing here")); ok {
		t.Error("unrecognised output was accepted")
	}
}

// --- the envelope -----------------------------------------------------

func sealed(t *testing.T, key ed25519.PrivateKey) Envelope {
	t.Helper()
	bundle := runCapture(t, loadManifest(t, composeManifest), "staging", Options{Runner: composeRunner()})
	envelope, err := Seal(bundle, key)
	if err != nil {
		t.Fatal(err)
	}
	return envelope
}

func TestAnEnvelopeRoundTrips(t *testing.T) {
	_, key, _ := ed25519.GenerateKey(nil)
	envelope := sealed(t, key)
	verified, err := Open(envelope)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	if len(verified.SignedBy) != 1 || verified.SignedBy[0] != envelope.Signatures[0].KeyID {
		t.Errorf("SignedBy = %v", verified.SignedBy)
	}
	if *verified.Bundle.Environment != "staging" || len(verified.Bundle.Facts) == 0 {
		t.Errorf("the bundle did not survive: %+v", verified.Bundle)
	}

	unsigned := sealed(t, nil)
	if verified, err := Open(unsigned); err != nil || len(verified.SignedBy) != 0 {
		t.Errorf("an unsigned envelope: %v, %v", verified.SignedBy, err)
	}
}

// TestAnAlteredEnvelopeIsRefused: each way of changing a sealed capture
// after the fact is caught, and none is waved through with a warning.
func TestAnAlteredEnvelopeIsRefused(t *testing.T) {
	_, key, _ := ed25519.GenerateKey(nil)
	_, otherKey, _ := ed25519.GenerateKey(nil)

	alter := func(mutate func(*Envelope, []byte) []byte) Envelope {
		envelope := sealed(t, key)
		payload, _ := base64.StdEncoding.DecodeString(envelope.Payload)
		payload = mutate(&envelope, payload)
		envelope.Payload = base64.StdEncoding.EncodeToString(payload)
		return envelope
	}
	// Dropping every refusal is the edit that matters most: it makes a
	// capture claim it looked at things it was never allowed to.
	dropRefusals := func(payload []byte) []byte {
		var bundle map[string]any
		_ = json.Unmarshal(payload, &bundle)
		delete(bundle, "refused")
		out, _ := json.Marshal(bundle)
		return out
	}

	for name, envelope := range map[string]Envelope{
		"payload edited, digest left alone": alter(func(_ *Envelope, payload []byte) []byte {
			return dropRefusals(payload)
		}),
		"payload and digest edited, signature left alone": alter(func(envelope *Envelope, payload []byte) []byte {
			edited := dropRefusals(payload)
			sum := sha256Hex(edited)
			envelope.SHA256 = sum
			return edited
		}),
		"re-signed with a different key under the old keyid": alter(func(envelope *Envelope, payload []byte) []byte {
			edited := dropRefusals(payload)
			envelope.SHA256 = sha256Hex(edited)
			public := otherKey.Public().(ed25519.PublicKey)
			envelope.Signatures[0].PublicKey = base64.StdEncoding.EncodeToString(public)
			envelope.Signatures[0].Sig = base64.StdEncoding.EncodeToString(
				ed25519.Sign(otherKey, pae(PayloadType, edited)))
			return edited
		}),
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := Open(envelope); err == nil {
				t.Fatal("an altered capture was accepted")
			}
		})
	}

	intent := sealed(t, nil)
	payload, _ := base64.StdEncoding.DecodeString(intent.Payload)
	var bundle map[string]any
	_ = json.Unmarshal(payload, &bundle)
	bundle["plane"] = "INTENT"
	edited, _ := json.Marshal(bundle)
	intent.Payload = base64.StdEncoding.EncodeToString(edited)
	intent.SHA256 = sha256Hex(edited)
	if _, err := Open(intent); err == nil {
		t.Error("an envelope holding a non-CONFIGURED capture was accepted")
	}
}

func sha256Hex(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

// TestACommandsStderrNeverReachesTheReport runs a real process that
// prints a secret to stderr and fails. The error the runner returns, and
// so every skip built from it, names the command and the kind of failure
// and nothing else.
func TestACommandsStderrNeverReachesTheReport(t *testing.T) {
	if os.Getenv("CULPRIT_HELPER_PROCESS") == "1" {
		fmt.Fprintln(os.Stderr, "DATABASE_URL=postgresql://u:"+plantedPassword+"@db/orders")
		fmt.Fprintln(os.Stdout, "partial")
		os.Exit(3)
	}
	executable, err := os.Executable()
	if err != nil {
		t.Skip(err)
	}
	t.Setenv("CULPRIT_HELPER_PROCESS", "1")
	_, runErr := ExecRunner{Timeout: 20 * time.Second}.Run(context.Background(),
		[]string{executable, "-test.run=TestACommandsStderrNeverReachesTheReport"})
	if runErr == nil {
		t.Fatal("a failing command reported success")
	}
	if strings.Contains(runErr.Error(), plantedPassword) || strings.Contains(runErr.Error(), "partial") {
		t.Errorf("the error carries the command's output: %v", runErr)
	}
	if safeReason(runErr) != runErr.Error() {
		t.Errorf("safeReason did not render a RunError as itself")
	}

	_, missing := ExecRunner{}.Run(context.Background(), []string{"culprit-no-such-command-anywhere"})
	var kind *RunError
	if !errors.As(missing, &kind) || kind.Kind != RunNotFound {
		t.Errorf("a missing command: %v", missing)
	}
}

func TestAnUnexpectedErrorTypeRendersAsAFixedPhrase(t *testing.T) {
	if got := safeReason(fmt.Errorf("postgresql://u:%s@h/d", plantedPassword)); got != "an unexpected error" {
		t.Errorf("safeReason rendered an arbitrary error: %q", got)
	}
}

// TestAHandWrittenReasonCannotCarryACredential is the Phase 30 phase
// audit's tamper, as a test: put a DSN into a refusal's reason, re-hash the
// envelope so its digest still matches, and hand it to `culprit diff`.
// Opening it is refused; and a report that renders such a reason anyway —
// from a plugin's skip, say — redacts it. Two lines of defence for text
// the CLI did not write.
func TestAHandWrittenReasonCannotCarryACredential(t *testing.T) {
	envelope := sealed(t, nil)
	payload, _ := base64.StdEncoding.DecodeString(envelope.Payload)
	var raw map[string]any
	_ = json.Unmarshal(payload, &raw)
	dsn := "postgresql://orders:" + plantedPassword + "@db/orders"
	raw["refused"] = []map[string]any{{
		"capability": "db.metadata.read", "check": CheckSchema, "reason": "could not reach " + dsn,
	}}
	edited, _ := json.Marshal(raw)
	envelope.Payload = base64.StdEncoding.EncodeToString(edited)
	envelope.SHA256 = sha256Hex(edited)
	_, err := Open(envelope)
	if err == nil {
		t.Fatal("an envelope carrying a DSN in a refusal reason was opened")
	}
	if strings.Contains(err.Error(), plantedPassword) {
		t.Errorf("the refusal quoted the reason it refused: %v", err)
	}

	bundle := runCapture(t, loadManifest(t, composeManifest), "staging", Options{Runner: composeRunner()})
	bundle.Refused = append(bundle.Refused, model.Refusal{
		Capability: "db.metadata.read", Check: CheckSchema, Reason: "could not reach " + dsn,
	})
	bundle.Skipped = append(bundle.Skipped, model.Skip{
		Want: "db_schema", Component: "orders-api", Reason: "plugin said " + dsn,
	})
	for _, format := range []string{"text", "json", "sarif", "junit"} {
		var rendered bytes.Buffer
		if err := report.Render(&rendered, format, report.Input{Captures: []model.CaptureBundle{bundle}}); err != nil {
			t.Fatal(err)
		}
		if strings.Contains(rendered.String(), plantedPassword) {
			t.Errorf("%s rendered a credential from a reason", format)
		}
	}
}

// TestSARIFSaysWhatWasNotLookedAt: a diff with no grants must not be a
// clean-looking empty SARIF log. The first version was.
func TestSARIFSaysWhatWasNotLookedAt(t *testing.T) {
	noGrants := strings.Replace(composeManifest, `    grants:
      config.read.names: true
      deploy.metadata.read: true
      config.read.values: [orders-api/LOG_LEVEL]
`, "", 1)
	bundle := runCapture(t, loadManifest(t, noGrants), "staging", Options{Runner: composeRunner()})
	if len(bundle.Refused) == 0 {
		t.Fatal("a capture with no grants recorded no refusals")
	}
	var rendered bytes.Buffer
	if err := report.Render(&rendered, "sarif", report.Input{Captures: []model.CaptureBundle{bundle}}); err != nil {
		t.Fatal(err)
	}
	var log struct {
		Runs []struct {
			Invocations []struct {
				Notifications []struct {
					Message struct{ Text string } `json:"message"`
				} `json:"toolExecutionNotifications"`
			} `json:"invocations"`
		} `json:"runs"`
	}
	if err := json.Unmarshal(rendered.Bytes(), &log); err != nil {
		t.Fatal(err)
	}
	refused := 0
	for _, invocation := range log.Runs[0].Invocations {
		for _, notification := range invocation.Notifications {
			if strings.HasPrefix(notification.Message.Text, "Refused") {
				refused++
			}
		}
	}
	if refused != len(bundle.Refused) {
		t.Errorf("SARIF carries %d refusal(s); the capture has %d", refused, len(bundle.Refused))
	}
}

func TestAnAbsoluteComposeFileIsUsedAsWritten(t *testing.T) {
	absolute, _ := filepath.Abs(filepath.Join(t.TempDir(), "compose.yml"))
	adapter := composeAdapter{spec: extract.ComposeSpec{Project: "p", Files: []string{absolute, "relative.yml"}}, dir: "/repo"}
	argv := adapter.base()
	if argv[5] != absolute {
		t.Errorf("an absolute compose file was rewritten: %q", argv[5])
	}
	if argv[7] != filepath.Join("/repo", "relative.yml") {
		t.Errorf("a relative compose file was not resolved against the manifest: %q", argv[7])
	}
}
