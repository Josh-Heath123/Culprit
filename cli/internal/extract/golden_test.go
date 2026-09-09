package extract

import (
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Golden-file tests over the fixture corpus (field 13).
//
// Four fixtures, two of them written by other people in stacks this repo
// does not use — see cli/testdata/fixtures/README.md for why that is a
// hard requirement rather than thoroughness.
//
// Two things are pinned deliberately, and both are the reason these
// tests can assert byte equality at all:
//
//   - `--no-plugins`. A golden run exercises the built-in artefact
//     readers only, so the test needs no Python and no Node toolchain.
//     That is also exactly the path acceptance criterion 4 is about —
//     "with no extractor installed, it still emits artefact-derived
//     facts and reports precisely what it skipped and why". The plugins
//     have their own tests in their own languages.
//   - The clock. `captured_at` and the derived capture id are both
//     functions of the capture time, so an unpinned clock would change
//     every golden file on every run and pin nothing.
//
// Update with `just cli-golden-update` (-update below). Read the diff
// before committing it: a golden file is a record of what the extractor
// currently believes, and updating one without looking is how a
// regression becomes the new expectation.

var updateGolden = flag.Bool("update", false, "rewrite the golden files instead of asserting them")

// goldenClock is the pinned capture time. An arbitrary fixed instant;
// what matters is only that it never moves.
var goldenClock = time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)

var fixtures = []string{
	"fastapi-orders",
	"react-web",
	"third-party/flask-tutorial",
	"third-party/express-route-separation",
}

func fixtureDir(t *testing.T, name string) string {
	t.Helper()
	path := filepath.Join("..", "..", "testdata", "fixtures", filepath.FromSlash(name))
	if _, err := os.Stat(filepath.Join(path, "culprit.yaml")); err != nil {
		t.Fatalf("fixture %s has no culprit.yaml (%v)", name, err)
	}
	return path
}

// runFixture extracts one fixture with the clock pinned and plugins off.
func runFixture(t *testing.T, name string) model.CaptureBundle {
	t.Helper()
	dir := fixtureDir(t, name)
	manifest, err := LoadManifest(filepath.Join(dir, "culprit.yaml"))
	if err != nil {
		t.Fatalf("loading %s/culprit.yaml: %v", name, err)
	}
	bundle, err := Run(context.Background(), Options{
		Manifest:    manifest,
		ManifestDir: dir,
		Now:         goldenClock,
		SkipPlugins: true,
		Version:     "test",
	})
	if err != nil {
		t.Fatalf("extracting %s: %v", name, err)
	}
	return bundle
}

// normalise removes the one thing that legitimately differs between
// machines: the absolute manifest directory, which feeds the derived
// capture id. Replaced with a constant so a golden file committed from a
// Windows checkout still matches a Linux CI run.
//
// **Every fact's capture id is rewritten with it.** The first version
// changed only the bundle's, which left the golden files internally
// inconsistent — a fact pointing at a capture id no capture had. They
// are supposed to be *real captures*, and one that cannot be posted to
// POST /facts/captures is not one: the endpoint refuses a fact whose
// capture id differs from its bundle's, deliberately, because that is
// either a client bug or two bundles spliced together. Found by
// api/tests/test_facts_api.py posting these very files.
func normalise(bundle model.CaptureBundle) model.CaptureBundle {
	const stable = "00000000-0000-5000-8000-000000000000"
	bundle.CaptureID = stable
	facts := make([]model.Fact, len(bundle.Facts))
	copy(facts, bundle.Facts)
	for index := range facts {
		facts[index].CaptureID = stable
	}
	bundle.Facts = facts
	return bundle
}

func encode(t *testing.T, bundle model.CaptureBundle) []byte {
	t.Helper()
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetIndent("", "  ")
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(bundle); err != nil {
		t.Fatalf("encoding: %v", err)
	}
	return buffer.Bytes()
}

func TestGoldenFixtures(t *testing.T) {
	for _, name := range fixtures {
		t.Run(name, func(t *testing.T) {
			actual := encode(t, normalise(runFixture(t, name)))
			goldenPath := filepath.Join(
				"..", "..", "testdata", "fixtures", "golden",
				filepath.FromSlash(name)+".json")

			if *updateGolden {
				if err := os.MkdirAll(filepath.Dir(goldenPath), 0o755); err != nil {
					t.Fatalf("creating golden directory: %v", err)
				}
				if err := os.WriteFile(goldenPath, actual, 0o644); err != nil {
					t.Fatalf("writing golden file: %v", err)
				}
				t.Logf("wrote %s", goldenPath)
				return
			}

			expected, err := os.ReadFile(goldenPath)
			if err != nil {
				t.Fatalf("no golden file for %s (%v). Run `just cli-golden-update`.", name, err)
			}
			// Line endings, not bytes: a Windows checkout without
			// .gitattributes rewrites the golden file's newlines, and a
			// test that fails on that is a test that fails for a reason
			// nobody can act on. CLAUDE.md's own CRLF warning is about
			// exactly this.
			if !bytes.Equal(stripCR(expected), stripCR(actual)) {
				t.Errorf("golden mismatch for %s.\n--- want ---\n%s\n--- got ---\n%s",
					name, expected, actual)
			}
		})
	}
}

func stripCR(data []byte) []byte {
	return bytes.ReplaceAll(data, []byte("\r\n"), []byte("\n"))
}

// TestExtractionIsByteIdentical is acceptance criterion 2, asserted
// directly rather than inferred from the golden files passing.
//
// The golden test proves the output matches a recorded expectation. This
// proves two *runs* match each other, which is the property the
// criterion states and the one that catches a non-determinism the golden
// file happens to have baked in.
func TestExtractionIsByteIdentical(t *testing.T) {
	for _, name := range fixtures {
		t.Run(name, func(t *testing.T) {
			first := encode(t, runFixture(t, name))
			second := encode(t, runFixture(t, name))
			if !bytes.Equal(first, second) {
				t.Errorf("two runs over an unchanged tree differ.\n--- first ---\n%s\n--- second ---\n%s",
					first, second)
			}
		})
	}
}

// TestNoFixtureLeaksAConfigValue is the corpus-wide form of acceptance
// criterion 3 and of field 12's redaction requirement.
//
// The fixtures' .env.example files contain real-looking values on
// purpose — a DSN with a password in it, an empty API key. This asserts
// none of them survives into a bundle, over every fixture at once, so a
// new reader that started copying values would fail here even if it had
// no test of its own.
func TestNoFixtureLeaksAConfigValue(t *testing.T) {
	// Substrings that appear in a fixture's .env.example and must never
	// appear in a capture.
	forbidden := []string{
		"postgresql://orders:placeholder@localhost:5432/orders",
		"placeholder@localhost",
		"change-me",
	}
	for _, name := range fixtures {
		t.Run(name, func(t *testing.T) {
			encoded := string(encode(t, runFixture(t, name)))
			for _, needle := range forbidden {
				if bytes.Contains([]byte(encoded), []byte(needle)) {
					t.Errorf("capture of %s contains the config value %q — "+
						"facts carry shapes, never values (§2.2)", name, needle)
				}
			}
		})
	}
}

// TestArtefactOnlyRunReportsItsGaps is acceptance criterion 4's second
// half: not just "it still emits facts", but "it reports precisely what
// it skipped and why".
//
// A capture that quietly produced fewer facts because a source was
// missing would look identical to a capture of a system that genuinely
// has less in it. Every skip therefore needs a non-empty reason, and
// this asserts it over the whole corpus.
func TestArtefactOnlyRunReportsItsGaps(t *testing.T) {
	for _, name := range fixtures {
		t.Run(name, func(t *testing.T) {
			bundle := runFixture(t, name)
			if len(bundle.Skipped) == 0 {
				t.Fatalf("%s produced no skips at all; an artefact-only run always "+
					"has gaps and must say so", name)
			}
			for _, skip := range bundle.Skipped {
				if skip.Reason == "" {
					t.Errorf("a skip of %q carries no reason", skip.Want)
				}
				if skip.Want == "" {
					t.Errorf("a skip with reason %q names nothing", skip.Reason)
				}
			}
		})
	}
}

// minArtefactFacts is what each fixture must yield from the built-in
// readers alone, with every plugin switched off.
//
// Stated per fixture rather than as one "> 0" floor, because one of them
// legitimately yields nothing and that is worth pinning rather than
// papering over. `express-route-separation` is an example *inside* the
// Express repository: upstream it has no package.json, no .env.example
// and no OpenAPI document, because its dependencies come from the
// repository around it. So an artefact-only run over it finds nothing at
// all — and reports a skip per want saying so, which is the correct
// behaviour and is asserted by TestArtefactOnlyRunReportsItsGaps.
//
// That fixture earns its place through the *Node extractor*, which finds
// the routes its four modules register against one `app` — see
// extractors/node/test/fixtures.test.js. Recording a hard zero here
// keeps both facts visible: the artefact readers cannot help with this
// tree, and something else must.
var minArtefactFacts = map[string]int{
	"fastapi-orders":                       20, // openapi + env + compose + alembic + deps
	"react-web":                            8,  // package.json + .env.example
	"third-party/flask-tutorial":           1,  // pyproject dependencies
	"third-party/express-route-separation": 0,  // see above
}

// TestEveryFixtureProducesFacts guards against the corpus quietly
// becoming decorative.
//
// A golden test passes just as happily against an empty bundle as
// against a full one, so a reader that broke and started returning
// nothing would be recorded as the new expectation the next time
// somebody ran -update. This is the floor that stops that.
func TestEveryFixtureProducesFacts(t *testing.T) {
	for _, name := range fixtures {
		t.Run(name, func(t *testing.T) {
			minimum, declared := minArtefactFacts[name]
			if !declared {
				t.Fatalf("fixture %s has no entry in minArtefactFacts; "+
					"say what it is expected to yield", name)
			}
			bundle := runFixture(t, name)
			if len(bundle.Facts) < minimum {
				t.Fatalf("%s produced %d fact(s) from its committed artefacts, expected at least %d",
					name, len(bundle.Facts), minimum)
			}
			if minimum == 0 && len(bundle.Facts) != 0 {
				// A fixture recorded as artefact-barren that starts
				// producing facts is a change worth looking at, not a
				// silent improvement: either a reader got better or it
				// started reading something it should not.
				t.Fatalf("%s is recorded as yielding nothing from artefact readers "+
					"and produced %d fact(s); update minArtefactFacts and say why",
					name, len(bundle.Facts))
			}
		})
	}
}
