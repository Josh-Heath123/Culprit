package extract

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The build reader (Phase 38 part 1), on the recorded build in
// cli/testdata/build/vite: index.html statically imports a shared chunk and
// lists a stylesheet, and dynamically imports the largest file; admin.html
// imports the same shared chunk.

var buildClock = time.Date(2026, 11, 17, 12, 0, 0, 0, time.UTC)

const viteFixture = "../../testdata/build/vite"

func builtManifest(path string) *Manifest {
	return &Manifest{Components: []ManifestComponent{{
		Name: "web", Kind: "frontend", Build: &ComponentBuild{ViteManifest: path},
	}}}
}

func readFixture(t *testing.T) BuildRead {
	t.Helper()
	return ReadBuilds(builtManifest("out/.vite/manifest.json"), viteFixture, nil, buildClock, "capture-1")
}

// sizes is each fixture file's raw and gzipped size, measured here the way
// the rule says: each file through compress/gzip at BestCompression.
func sizes(t *testing.T, files ...string) (int64, int64) {
	t.Helper()
	var raw, gzipped int64
	for _, file := range files {
		contents, err := os.ReadFile(filepath.Join(viteFixture, "out", file))
		if err != nil {
			t.Fatal(err)
		}
		var buffer bytes.Buffer
		writer, _ := gzip.NewWriterLevel(&buffer, gzip.BestCompression)
		_, _ = writer.Write(contents)
		_ = writer.Close()
		raw += int64(len(contents))
		gzipped += int64(buffer.Len())
	}
	return raw, gzipped
}

func factValue(t *testing.T, facts []model.Fact, subject, predicate string) any {
	t.Helper()
	for _, fact := range facts {
		if fact.Subject == subject && fact.Predicate == predicate {
			return fact.Value
		}
	}
	t.Fatalf("no %s fact on %s", predicate, subject)
	return nil
}

func TestABuildIsReadAsItsInitialDownload(t *testing.T) {
	read := readFixture(t)
	if len(read.NotChecked) != 0 {
		t.Fatalf("not checked: %+v", read.NotChecked)
	}
	index := model.MustBuildSubject(model.KindBundle, model.Parts{"component": "web", "entry": "index.html"})
	admin := model.MustBuildSubject(model.KindBundle, model.Parts{"component": "web", "entry": "admin.html"})

	// index.html: its own file, the shared chunk its static import reaches,
	// and its stylesheet. Not the lazy chunk, which only a dynamic import
	// names, although it is the largest file in the build.
	raw, gzipped := sizes(t, "assets/index-a1b2.js", "assets/shared-c3d4.js", "assets/index-9f8e.css")
	if got := factValue(t, read.Facts, index, model.PredicateBundleRawBytes); got != raw {
		t.Errorf("index.html raw: %v, want %d", got, raw)
	}
	if got := factValue(t, read.Facts, index, model.PredicateBundleGzipBytes); got != gzipped {
		t.Errorf("index.html gzip: %v, want %d", got, gzipped)
	}
	if gzipped >= raw {
		t.Errorf("gzip %d is not smaller than raw %d: the fixture is not compressible text", gzipped, raw)
	}
	// admin.html counts the same shared chunk, once.
	if raw, _ := sizes(t, "assets/admin-0a1b.js", "assets/shared-c3d4.js"); factValue(t, read.Facts, admin, model.PredicateBundleRawBytes) != raw {
		t.Errorf("admin.html raw: want %d", raw)
	}

	largest, _ := factValue(t, read.Facts, index, model.PredicateBundleLargestChunks).([]any)
	var names []string
	for _, item := range largest {
		names = append(names, item.(map[string]any)["file"].(string))
	}
	for _, name := range names {
		if strings.Contains(name, "lazy") {
			t.Errorf("the dynamically imported chunk is among index.html's largest: %v", names)
		}
	}
	if len(names) != 3 || !reflect.DeepEqual(append([]string(nil), names...), sortedByGzip(t, names)) {
		t.Errorf("largest: %v, want the three files by gzipped size", names)
	}

	for _, fact := range read.Facts {
		if fact.Plane != model.PlaneObserved || fact.Environment != model.BuildEnvironment {
			t.Errorf("%s %s: plane %s environment %q, want OBSERVED in build", fact.Subject, fact.Predicate, fact.Plane, fact.Environment)
		}
		if err := fact.Validate(); err != nil {
			t.Errorf("%s %s: %v", fact.Subject, fact.Predicate, err)
		}
	}
}

// TestADynamicImportIsNotCounted: the same build, with index.html's static
// import turned into a dynamic one, downloads less at first.
func TestADynamicImportIsNotCounted(t *testing.T) {
	dir := t.TempDir()
	if err := os.CopyFS(dir, os.DirFS(viteFixture)); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "out", ".vite", "manifest.json")
	var chunks map[string]map[string]any
	raw, _ := os.ReadFile(path)
	if err := json.Unmarshal(raw, &chunks); err != nil {
		t.Fatal(err)
	}
	chunks["index.html"]["imports"] = []any{}
	chunks["index.html"]["dynamicImports"] = []any{"src/lazy.tsx", "_shared-c3d4.js"}
	rewritten, _ := json.Marshal(chunks)
	if err := os.WriteFile(path, rewritten, 0o644); err != nil {
		t.Fatal(err)
	}
	read := ReadBuilds(builtManifest("out/.vite/manifest.json"), dir, nil, buildClock, "capture-1")
	index := model.MustBuildSubject(model.KindBundle, model.Parts{"component": "web", "entry": "index.html"})
	want, _ := sizes(t, "assets/index-a1b2.js", "assets/index-9f8e.css")
	if got := factValue(t, read.Facts, index, model.PredicateBundleRawBytes); got != want {
		t.Errorf("index.html raw with the shared chunk imported dynamically: %v, want %d", got, want)
	}
}

func sortedByGzip(t *testing.T, names []string) []string {
	t.Helper()
	type sized struct {
		name string
		gzip int64
	}
	var all []sized
	for _, name := range names {
		_, gzipped := sizes(t, name)
		all = append(all, sized{name, gzipped})
	}
	for i := range all {
		for j := i + 1; j < len(all); j++ {
			if all[j].gzip > all[i].gzip || (all[j].gzip == all[i].gzip && all[j].name < all[i].name) {
				all[i], all[j] = all[j], all[i]
			}
		}
	}
	out := make([]string, 0, len(all))
	for _, item := range all {
		out = append(out, item.name)
	}
	return out
}

// TestTheSameBuildGivesTheSameFactsTwice is the determinism criterion.
func TestTheSameBuildGivesTheSameFactsTwice(t *testing.T) {
	first, _ := json.Marshal(readFixture(t))
	second, _ := json.Marshal(readFixture(t))
	if !bytes.Equal(first, second) {
		t.Fatalf("two reads of one build differ:\n%s\n%s", first, second)
	}
}

// TestABuildsContentsAreNeverKept: the shared chunk holds secret-looking
// strings; the facts hold its name and sizes, and none of them.
func TestABuildsContentsAreNeverKept(t *testing.T) {
	contents, err := os.ReadFile(filepath.Join(viteFixture, "out", "assets", "shared-c3d4.js"))
	if err != nil {
		t.Fatal(err)
	}
	secrets := []string{"AKIAIOSFODNN7EXAMPLE", "ghp_abcdefghijklmnopqrstuvwxyz0123456789", "BEGIN PRIVATE KEY", "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC"}
	for _, secret := range secrets {
		if !bytes.Contains(contents, []byte(secret)) {
			t.Fatalf("the fixture no longer holds %q, so this test shows nothing", secret)
		}
	}
	encoded, _ := json.Marshal(readFixture(t))
	for _, secret := range secrets {
		if bytes.Contains(encoded, []byte(secret)) {
			t.Errorf("a fact holds %q from a chunk's contents", secret)
		}
	}
	if !bytes.Contains(encoded, []byte("assets/shared-c3d4.js")) {
		t.Error("the shared chunk is not named at all")
	}
	// Every value is a size, or a list of names and sizes.
	for _, fact := range readFixture(t).Facts {
		switch value := fact.Value.(type) {
		case int64:
		case []any:
			for _, item := range value {
				entry := item.(map[string]any)
				if len(entry) != 2 || entry["file"] == nil || entry["gzip_bytes"] == nil {
					t.Errorf("%s: a largest-chunk entry is not a name and a size: %v", fact.Subject, entry)
				}
			}
		default:
			t.Errorf("%s %s: value of type %T", fact.Subject, fact.Predicate, value)
		}
	}
}

func TestABuildThatCannotBeReadIsNotChecked(t *testing.T) {
	for name, setup := range map[string]struct {
		manifest string
		write    map[string]string
		want     string
	}{
		"no manifest":      {manifest: "out/.vite/manifest.json", want: "no build manifest at out/.vite/manifest.json"},
		"not a manifest":   {manifest: "m.json", write: map[string]string{"m.json": "[1, 2]"}, want: "is not a Vite build manifest"},
		"no entry":         {manifest: "m.json", write: map[string]string{"m.json": `{"a.js": {"file": "a.js"}}`}, want: "names no entry"},
		"a missing file":   {manifest: "m.json", write: map[string]string{"m.json": `{"index.html": {"file": "gone.js", "isEntry": true}}`}, want: "missing from the build"},
		"an unknown chunk": {manifest: "m.json", write: map[string]string{"m.json": `{"index.html": {"file": "a.js", "isEntry": true, "imports": ["_nope.js"]}}`, "a.js": "x"}, want: "not in the manifest"},
		"a path outside":   {manifest: "m.json", write: map[string]string{"m.json": `{"index.html": {"file": "../../secret.txt", "isEntry": true}}`}, want: "outside the build's output directory"},
	} {
		t.Run(name, func(t *testing.T) {
			dir := t.TempDir()
			for file, contents := range setup.write {
				if err := os.WriteFile(filepath.Join(dir, file), []byte(contents), 0o644); err != nil {
					t.Fatal(err)
				}
			}
			read := ReadBuilds(builtManifest(setup.manifest), dir, nil, buildClock, "capture-1")
			if len(read.Facts) != 0 || len(read.NotChecked) != 1 || !strings.Contains(read.NotChecked[0].Reason, setup.want) {
				t.Fatalf("facts %d, not checked %+v; want one line saying %q", len(read.Facts), read.NotChecked, setup.want)
			}
			if read.NotChecked[0].Component != "web" {
				t.Errorf("the line names %q, not the component", read.NotChecked[0].Component)
			}
		})
	}
}

func TestOnlyAnUndeclaredBuildIsUnread(t *testing.T) {
	manifest := &Manifest{Components: []ManifestComponent{{Name: "web", Kind: "frontend"}}}
	read := ReadBuilds(manifest, viteFixture, nil, buildClock, "capture-1")
	if len(read.Facts) != 0 || len(read.NotChecked) != 0 {
		t.Fatalf("a component with no build: %d facts, %+v", len(read.Facts), read.NotChecked)
	}
	read = ReadBuilds(builtManifest("out/.vite/manifest.json"), viteFixture, []string{"api"}, buildClock, "capture-1")
	if len(read.Facts) != 0 {
		t.Fatalf("--only api read web's build")
	}
}
