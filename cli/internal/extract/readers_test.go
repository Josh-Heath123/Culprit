package extract

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Unit tests for the built-in artefact readers and the orchestration
// around them. The golden tests pin whole-fixture output; these pin the
// specific behaviours that output depends on, so a failure names the
// reader rather than showing a 30 KB diff.

func TestParsePyprojectHandlesExtras(t *testing.T) {
	// The regression. `sqlalchemy[asyncio]>=2.0`'s closing bracket used
	// to end the dependency array, silently dropping everything after it
	// — two dependencies out of four, one of them mangled into
	// `sqlalchemy = "[asyncio"`. The fastapi-orders fixture caught it;
	// this pins it, because the symptom (a short dependency list) is
	// indistinguishable from a project that simply has few dependencies.
	source := `[project]
name = "orders-api"
dependencies = [
    "fastapi>=0.115",
    "sqlalchemy[asyncio]>=2.0",
    "alembic>=1.13",
    "pydantic>=2.9",
]

[project.optional-dependencies]
test = ["pytest"]
`
	dependencies := parsePyprojectToml(source)
	expected := map[string]string{
		"fastapi":    ">=0.115",
		"sqlalchemy": ">=2.0",
		"alembic":    ">=1.13",
		"pydantic":   ">=2.9",
	}
	if len(dependencies) != len(expected) {
		t.Fatalf("got %d dependencies %v, want %d", len(dependencies), dependencies, len(expected))
	}
	for name, version := range expected {
		if dependencies[name] != version {
			t.Errorf("%s = %q, want %q", name, dependencies[name], version)
		}
	}
	// `[project.optional-dependencies]` is a different table and is not
	// read: half-reading a project's dependency set produces a list that
	// looks complete and is not.
	if _, present := dependencies["pytest"]; present {
		t.Error("optional-dependencies were read; only [project] dependencies should be")
	}
}

func TestParsePyprojectSingleLineArray(t *testing.T) {
	dependencies := parsePyprojectToml("[project]\ndependencies = [\"flask\"]\n")
	if dependencies["flask"] != "*" {
		t.Fatalf("got %v, want flask with an unconstrained specifier", dependencies)
	}
}

func TestParseRequirementsSkipsMarkersAndUrls(t *testing.T) {
	source := `# a comment
fastapi>=0.115
uvicorn[standard]>=0.32  # inline comment
tomli>=2.0; python_version < "3.11"
-e .
git+https://github.com/example/pkg.git#egg=pkg
`
	dependencies := parseRequirementsTxt(source)
	if dependencies["fastapi"] != ">=0.115" {
		t.Errorf("fastapi = %q", dependencies["fastapi"])
	}
	if dependencies["uvicorn"] != ">=0.32" {
		t.Errorf("uvicorn = %q, want the specifier without the inline comment", dependencies["uvicorn"])
	}
	if dependencies["tomli"] != ">=2.0" {
		t.Errorf("tomli = %q, want the specifier without the environment marker", dependencies["tomli"])
	}
	if len(dependencies) != 3 {
		t.Errorf("got %v; an editable install and a URL reference are not version claims", dependencies)
	}
}

func TestDotenvParsing(t *testing.T) {
	cases := []struct {
		line    string
		key     string
		value   string
		matched bool
	}{
		{"DATABASE_URL=postgres://u:p@h/db", "DATABASE_URL", "postgres://u:p@h/db", true},
		{"export PORT=8000", "PORT", "8000", true},
		{`QUOTED="hello world"`, "QUOTED", "hello world", true},
		{"EMPTY=", "EMPTY", "", true},
		{"# a comment", "", "", false},
		{"", "", "", false},
		{"NOT A KEY", "", "", false},
	}
	for _, testCase := range cases {
		key, value, ok := parseDotenvLine(testCase.line)
		if ok != testCase.matched {
			t.Errorf("parseDotenvLine(%q) matched=%v, want %v", testCase.line, ok, testCase.matched)
			continue
		}
		if ok && (key != testCase.key || value != testCase.value) {
			t.Errorf("parseDotenvLine(%q) = (%q, %q), want (%q, %q)",
				testCase.line, key, value, testCase.key, testCase.value)
		}
	}
}

func TestAlembicHeadIsTheRevisionNothingPointsAt(t *testing.T) {
	root := t.TempDir()
	versions := filepath.Join(root, "migrations", "versions")
	if err := os.MkdirAll(versions, 0o755); err != nil {
		t.Fatal(err)
	}
	write := func(name, revision, down string) {
		body := "revision: str = \"" + revision + "\"\n"
		if down == "" {
			body += "down_revision: str | None = None\n"
		} else {
			body += "down_revision: str | None = \"" + down + "\"\n"
		}
		if err := os.WriteFile(filepath.Join(versions, name), []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	write("a.py", "aaa", "")
	write("b.py", "bbb", "aaa")
	write("c.py", "ccc", "bbb")

	ctx := captureContext{Component: "svc", Root: root, CapturedAt: time.Now(),
		CaptureID: "00000000-0000-5000-8000-000000000000", Extractor: "test"}
	facts, skips := readMigrationHead(ctx)
	if len(skips) != 0 {
		t.Fatalf("unexpected skips: %v", skips)
	}
	if len(facts) != 1 {
		t.Fatalf("got %d facts, want 1", len(facts))
	}
	heads, ok := facts[0].Value.([]string)
	if !ok || len(heads) != 1 || heads[0] != "ccc" {
		t.Fatalf("head = %v, want [ccc]", facts[0].Value)
	}
}

func TestAlembicBranchedHeadsAreBothReported(t *testing.T) {
	// Alembic genuinely supports branched heads. Picking one silently
	// would hide a real problem — two heads where a project expects one
	// is a finding Phase 29 can make, and only if this does not choose.
	root := t.TempDir()
	versions := filepath.Join(root, "migrations", "versions")
	if err := os.MkdirAll(versions, 0o755); err != nil {
		t.Fatal(err)
	}
	files := map[string]string{
		"a.py": "revision: str = \"aaa\"\ndown_revision: str | None = None\n",
		"b.py": "revision: str = \"bbb\"\ndown_revision: str | None = \"aaa\"\n",
		"c.py": "revision: str = \"ccc\"\ndown_revision: str | None = \"aaa\"\n",
	}
	for name, body := range files {
		if err := os.WriteFile(filepath.Join(versions, name), []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	ctx := captureContext{Component: "svc", Root: root, CapturedAt: time.Now(),
		CaptureID: "00000000-0000-5000-8000-000000000000", Extractor: "test"}
	facts, _ := readMigrationHead(ctx)
	if len(facts) != 1 {
		t.Fatalf("got %d facts, want 1", len(facts))
	}
	heads, _ := facts[0].Value.([]string)
	if len(heads) != 2 || heads[0] != "bbb" || heads[1] != "ccc" {
		t.Fatalf("heads = %v, want both [bbb ccc]", heads)
	}
}

func TestManifestRejectsAnExtractEntryForAnUndeclaredComponent(t *testing.T) {
	// Refused rather than ignored: ignoring it means the author believes
	// a source root is being scanned that is not, and every fact they
	// expected is simply absent — which reads as "nothing wrong there".
	root := t.TempDir()
	path := filepath.Join(root, "culprit.yaml")
	body := `version: 1
components:
  - name: web
extract:
  components:
    api:
      root: api
`
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadManifest(path); err == nil {
		t.Fatal("an extract entry for an undeclared component was accepted")
	} else if !strings.Contains(err.Error(), "api") {
		t.Errorf("the error does not name the offending component: %v", err)
	}
}

func TestManifestRejectsCallsToAnUndeclaredComponent(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "culprit.yaml")
	body := `version: 1
components:
  - name: web
extract:
  components:
    web:
      root: .
      calls_to: orders-api
`
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadManifest(path); err == nil {
		t.Fatal("calls_to naming an undeclared component was accepted")
	}
}

func TestComponentWithNoRootIsReportedNotSilentlySkipped(t *testing.T) {
	// The behaviour the fixture corpus forced. A component with no
	// declared root used to default to the manifest directory, so every
	// reader ran once per component over the same tree and `orders-db`
	// was credited with the API's routes and Alembic head.
	root := t.TempDir()
	path := filepath.Join(root, "culprit.yaml")
	body := `version: 1
components:
  - name: orders-api
  - name: orders-db
extract:
  components:
    orders-api:
      root: .
`
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	manifest, err := LoadManifest(path)
	if err != nil {
		t.Fatal(err)
	}
	bundle, err := Run(context.Background(), Options{
		Manifest: manifest, ManifestDir: root, SkipPlugins: true,
		Now: time.Unix(0, 0).UTC(), Version: "test",
	})
	if err != nil {
		t.Fatal(err)
	}
	for _, fact := range bundle.Facts {
		if strings.Contains(fact.Subject, "orders-db") {
			t.Errorf("a fact was attributed to the rootless component: %s", fact.Subject)
		}
	}
	named := false
	for _, skip := range bundle.Skipped {
		if strings.Contains(skip.Reason, "orders-db") && strings.Contains(skip.Reason, "no source root") {
			named = true
		}
	}
	if !named {
		t.Errorf("orders-db was skipped without being named: %v", bundle.Skipped)
	}
}

func TestMissingPluginDegradesToSkipsAndNeverFails(t *testing.T) {
	// Acceptance criterion 4, at the plugin boundary. The command a real
	// user has not installed yet.
	result := RunPlugin(context.Background(), ExtractorSpec{
		Name:    "python",
		Command: []string{"culprit-extract-python-that-is-not-installed"},
	}, model.ExtractorRequest{
		Protocol: model.ExtractorProtocolVersion,
		Root:     t.TempDir(),
		Want:     []model.Want{model.WantHTTPRoutes, model.WantConfigKeys},
	}, 5*time.Second)

	if len(result.Facts) != 0 {
		t.Errorf("a missing extractor produced facts: %v", result.Facts)
	}
	if len(result.Skipped) != 2 {
		t.Fatalf("got %d skips, want one per requested want: %v", len(result.Skipped), result.Skipped)
	}
	for _, skip := range result.Skipped {
		if skip.Reason == "" {
			t.Errorf("skip of %q has no reason", skip.Want)
		}
		if !strings.Contains(skip.Reason, "python") {
			t.Errorf("skip reason does not name the extractor: %q", skip.Reason)
		}
	}
}

func TestPluginFactsAreValidatedNotTrusted(t *testing.T) {
	// An extractor is a third-party program running in someone else's
	// virtualenv. A fact from one that carries an ungranted config
	// literal is dropped and reported, never stored. This is the one
	// place the config-value guarantee meets untrusted input.
	response := `{"protocol":1,"extractor":"evil@1.0","facts":[
      {"plane":"INTENT","subject":"config:svc/DATABASE_URL","predicate":"value",
       "value":"postgresql://u:hunter2@db/orders",
       "provenance":{"source_kind":"static","extractor":"evil@1.0","confidence_rank":60},
       "captured_at":"2026-01-01T00:00:00Z","capture_id":"00000000-0000-5000-8000-000000000000"},
      {"plane":"INTENT","subject":"component:svc","predicate":"exists","value":true,
       "provenance":{"source_kind":"static","extractor":"evil@1.0","confidence_rank":60},
       "captured_at":"2026-01-01T00:00:00Z","capture_id":"00000000-0000-5000-8000-000000000000"}
    ],"skipped":[]}`

	spec := fakeExtractor(t, response)
	result := RunPlugin(context.Background(), spec, model.ExtractorRequest{
		Protocol: model.ExtractorProtocolVersion,
		Root:     t.TempDir(),
		Want:     []model.Want{model.WantConfigKeys},
	}, 20*time.Second)

	for _, fact := range result.Facts {
		if strings.Contains(toJSON(t, fact), "hunter2") {
			t.Fatal("an ungranted config literal from an extractor was accepted")
		}
	}
	if len(result.Facts) != 1 {
		t.Errorf("got %d facts, want only the valid one: %v", len(result.Facts), result.Facts)
	}
	rejected := false
	for _, skip := range result.Skipped {
		if strings.Contains(skip.Reason, "rejected as invalid") {
			rejected = true
		}
	}
	if !rejected {
		t.Errorf("the rejection was not reported: %v", result.Skipped)
	}
}

func TestPluginWithWrongProtocolIsRefused(t *testing.T) {
	spec := fakeExtractor(t, `{"protocol":99,"extractor":"future@1.0","facts":[],"skipped":[]}`)
	result := RunPlugin(context.Background(), spec, model.ExtractorRequest{
		Protocol: model.ExtractorProtocolVersion,
		Root:     t.TempDir(),
		Want:     []model.Want{model.WantHTTPRoutes},
	}, 20*time.Second)
	if len(result.Skipped) == 0 || !strings.Contains(result.Skipped[0].Reason, "protocol") {
		t.Fatalf("a protocol mismatch was not refused: %v", result.Skipped)
	}
}

func TestPluginWithGarbageOutputDegradesToASkip(t *testing.T) {
	spec := fakeExtractor(t, "this is not JSON")
	result := RunPlugin(context.Background(), spec, model.ExtractorRequest{
		Protocol: model.ExtractorProtocolVersion,
		Root:     t.TempDir(),
		Want:     []model.Want{model.WantHTTPRoutes},
	}, 20*time.Second)
	if len(result.Facts) != 0 {
		t.Error("garbage output produced facts")
	}
	if len(result.Skipped) != 1 || !strings.Contains(result.Skipped[0].Reason, "JSON") {
		t.Fatalf("unhelpful skip for garbage output: %v", result.Skipped)
	}
}

// fakeExtractor builds a spec that runs `go` itself as a trivial
// extractor, printing a canned response.
//
// A real subprocess rather than an interface seam, because what is being
// tested is the subprocess contract: the pipe, the exit code, the
// parsing. A mock would test the mock.
func fakeExtractor(t *testing.T, output string) ExtractorSpec {
	t.Helper()
	dir := t.TempDir()
	source := filepath.Join(dir, "main.go")
	program := "package main\n\nimport \"fmt\"\n\nfunc main() {\n\tfmt.Print(`" + output + "`)\n}\n"
	if err := os.WriteFile(source, []byte(program), 0o644); err != nil {
		t.Fatal(err)
	}
	return ExtractorSpec{Name: "fake", Command: []string{"go", "run", source}}
}

func toJSON(t *testing.T, value any) string {
	t.Helper()
	var builder strings.Builder
	if err := writeJSON(&builder, value); err != nil {
		t.Fatal(err)
	}
	return builder.String()
}

func writeJSON(builder *strings.Builder, value any) error {
	encoder := json.NewEncoder(builder)
	return encoder.Encode(value)
}

func TestBoundedBufferStopsAtTheLimit(t *testing.T) {
	// The cap has to be a cap, not a post-hoc measurement. The first
	// version read everything into a bytes.Buffer and checked its size
	// afterwards, by which point a runaway extractor had already
	// allocated the memory the cap exists to prevent.
	buffer := &boundedBuffer{limit: 10}

	written, err := buffer.Write([]byte("12345"))
	if err != nil || written != 5 {
		t.Fatalf("Write returned (%d, %v)", written, err)
	}
	if buffer.overflowed {
		t.Fatal("overflowed before the limit was reached")
	}

	// Straddles the limit: accepted from the caller's point of view, but
	// only the part that fits is kept.
	written, err = buffer.Write([]byte("67890ABCDE"))
	if err != nil {
		t.Fatalf("Write errored: %v", err)
	}
	if written != 10 {
		// The child process must see a complete write. Reporting a short
		// write hands it a broken pipe mid-run and turns a legible
		// "produced too much output" into whatever that extractor does
		// when its stdout breaks.
		t.Fatalf("Write reported %d bytes; the child must see the whole write", written)
	}
	if !buffer.overflowed {
		t.Fatal("the overflow was not recorded")
	}
	if got := len(buffer.Bytes()); got != 10 {
		t.Fatalf("buffered %d bytes, want the limit of 10", got)
	}
	if string(buffer.Bytes()) != "1234567890" {
		t.Fatalf("kept %q, want the first 10 bytes", buffer.Bytes())
	}

	// Every subsequent write is discarded, not appended.
	if _, err := buffer.Write([]byte("more")); err != nil {
		t.Fatalf("Write after overflow errored: %v", err)
	}
	if got := len(buffer.Bytes()); got != 10 {
		t.Fatalf("buffered %d bytes after overflow, want 10", got)
	}
}

func TestAnOverproducingPluginIsSkippedNotParsed(t *testing.T) {
	// Truncated output is never parsed: half a JSON document read as if
	// it were whole is how a partial fact set silently becomes a
	// complete-looking one.
	original := maxPluginOutput
	maxPluginOutput = 64
	defer func() { maxPluginOutput = original }()

	big := strings.Repeat("x", 4096)
	spec := fakeExtractor(t, `{"protocol":1,"extractor":"loud@1.0","facts":[],"skipped":[]}`+big)

	result := RunPlugin(context.Background(), spec, model.ExtractorRequest{
		Protocol: model.ExtractorProtocolVersion,
		Root:     t.TempDir(),
		Want:     []model.Want{model.WantHTTPRoutes},
	}, 30*time.Second)

	if len(result.Facts) != 0 {
		t.Errorf("facts were taken from output that could not be trusted: %v", result.Facts)
	}
	if len(result.Skipped) == 0 {
		t.Fatal("an overproducing extractor produced no skip")
	}
	if !strings.Contains(result.Skipped[0].Reason, "more than") {
		t.Errorf("the skip does not say what happened: %q", result.Skipped[0].Reason)
	}
}
