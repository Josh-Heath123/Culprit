package extract

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The build reader (Phase 38 part 1, P6 as amended 2026-11-17).
//
// A component may declare where its frontend build is:
//
//	components:
//	  - name: web
//	    build:
//	      vite_manifest: frontend/dist/.vite/manifest.json
//
// and this reads it: Vite's build manifest, and the size of every file it
// names. It runs no project code, needs no Node, and keeps no file's
// contents — a fact holds names and byte counts, nothing else. It is built
// into the binary rather than asked of the Node extractor because extractor
// protocol 1 is INTENT only, and what a build measured is OBSERVED.
//
// For each entry (a chunk with `isEntry: true`) the reader measures its
// initial download: the entry's file, the files of every chunk reachable by
// static `imports`, and the `css` each of those lists. `dynamicImports` are
// left out, because the browser loads them later, if at all. Each file is
// counted once however many chunks import it. Its gzipped size is the
// file through compress/gzip at BestCompression; the entry's is the sum.
//
// Nothing searches for a build. A component that declares none is not
// read, and nothing is said of it.

// BuildExtractor names the build reader in a fact's provenance.
const BuildExtractor = "culprit-build"

// largestChunks is how many of an entry's files the reader names.
const largestChunks = 3

// maxBuildFileBytes is the largest file the reader reads: a file is read
// whole to be compressed, and no file a page loads first is this large.
const maxBuildFileBytes = 256 << 20

// viteChunk is the part of one Vite manifest entry the reader uses.
type viteChunk struct {
	File           string   `json:"file"`
	IsEntry        bool     `json:"isEntry"`
	Imports        []string `json:"imports"`
	DynamicImports []string `json:"dynamicImports"`
	CSS            []string `json:"css"`
}

// BuildChunk is one file of an entry's initial download, by name and size.
type BuildChunk struct {
	File      string `json:"file"`
	GzipBytes int64  `json:"gzip_bytes"`
}

// BuildRead is everything the build reader found: OBSERVED facts in the
// environment `build`, and a line for each declared build it could not
// read.
type BuildRead struct {
	Facts      []model.Fact
	NotChecked []model.Skip
}

// ReadBuilds reads every build manifest declares, in component order. only,
// when non-empty, restricts it to those components, as it restricts
// extraction (`culprit check --only`).
func ReadBuilds(manifest *Manifest, manifestDir string, only []string, capturedAt time.Time, captureID string) BuildRead {
	read := BuildRead{Facts: []model.Fact{}, NotChecked: []model.Skip{}}
	if manifest == nil {
		return read
	}
	wanted := map[string]bool{}
	for _, name := range only {
		wanted[model.CanonicalComponent(name)] = true
	}
	for _, component := range manifest.Components {
		if component.Build == nil || (len(wanted) > 0 && !wanted[component.Name]) {
			continue
		}
		facts, skip := readBuild(component.Name, manifestDir, component.Build.ViteManifest, capturedAt, captureID)
		read.Facts = append(read.Facts, facts...)
		if skip != nil {
			read.NotChecked = append(read.NotChecked, *skip)
		}
	}
	return read
}

func buildSkip(component, reason string) *model.Skip {
	return &model.Skip{Want: "build", Reason: reason, Component: component, Extractor: BuildExtractor}
}

// readBuild reads one component's build. A build that cannot be read is
// one "Not checked" line, never an error: the rest of the check stands.
func readBuild(component, manifestDir, declared string, capturedAt time.Time, captureID string) ([]model.Fact, *model.Skip) {
	manifestPath := filepath.Join(manifestDir, filepath.FromSlash(declared))
	raw, err := os.ReadFile(manifestPath)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, buildSkip(component, fmt.Sprintf(
			"no build manifest at %s (components[].build.vite_manifest): build the component before `culprit check`", declared))
	}
	if err != nil {
		return nil, buildSkip(component, fmt.Sprintf("the build manifest %s cannot be read: %v", declared, err))
	}
	var chunks map[string]viteChunk
	if err := json.Unmarshal(raw, &chunks); err != nil {
		return nil, buildSkip(component, fmt.Sprintf("%s is not a Vite build manifest: %v", declared, err))
	}

	// Vite 5 writes the manifest inside the output directory, at
	// .vite/manifest.json; Vite 4 wrote manifest.json at its top. The
	// files it names are relative to the output directory either way.
	outDir := filepath.Dir(manifestPath)
	if filepath.Base(outDir) == ".vite" {
		outDir = filepath.Dir(outDir)
	}

	var entries []string
	for key, chunk := range chunks {
		if chunk.IsEntry {
			entries = append(entries, key)
		}
	}
	if len(entries) == 0 {
		return nil, buildSkip(component, fmt.Sprintf("%s names no entry (no chunk with isEntry)", declared))
	}
	sort.Strings(entries)

	sizes := map[string][2]int64{} // file -> raw, gzip; each file read once
	var facts []model.Fact
	for _, entry := range entries {
		files, err := initialDownload(chunks, entry)
		if err != nil {
			return nil, buildSkip(component, fmt.Sprintf("%s: %v", declared, err))
		}
		var raw, gzipped int64
		var named []BuildChunk
		for _, file := range files {
			size, seen := sizes[file]
			if !seen {
				if size, err = measure(outDir, file); err != nil {
					return nil, buildSkip(component, fmt.Sprintf("%s names %s: %v", declared, file, err))
				}
				sizes[file] = size
			}
			raw += size[0]
			gzipped += size[1]
			named = append(named, BuildChunk{File: file, GzipBytes: size[1]})
		}
		sort.Slice(named, func(i, j int) bool {
			if named[i].GzipBytes != named[j].GzipBytes {
				return named[i].GzipBytes > named[j].GzipBytes
			}
			return named[i].File < named[j].File
		})
		if len(named) > largestChunks {
			named = named[:largestChunks]
		}
		largest := make([]any, 0, len(named))
		for _, chunk := range named {
			largest = append(largest, map[string]any{"file": chunk.File, "gzip_bytes": chunk.GzipBytes})
		}

		subject, err := model.BuildSubject(model.KindBundle, model.Parts{"component": component, "entry": entry})
		if err != nil {
			return nil, buildSkip(component, fmt.Sprintf("%s: the entry %q cannot be a subject: %v", declared, entry, err))
		}
		for _, measured := range []struct {
			predicate string
			value     any
		}{
			{model.PredicateBundleRawBytes, raw},
			{model.PredicateBundleGzipBytes, gzipped},
			{model.PredicateBundleLargestChunks, largest},
		} {
			facts = append(facts, model.Fact{
				Plane:       model.PlaneObserved,
				Environment: model.BuildEnvironment,
				Subject:     subject,
				Predicate:   measured.predicate,
				Value:       measured.value,
				Provenance: model.Provenance{
					SourceKind: model.SourceObservation,
					Extractor:  BuildExtractor,
					Artefact:   filepath.ToSlash(declared),
					Locator:    entry,
					// The build's own files, read directly. Rank orders
					// two INTENT sources; nothing compares across planes
					// by it.
					ConfidenceRank: model.RankRuntimeIntrospection,
				},
				CapturedAt: capturedAt,
				CaptureID:  captureID,
			})
		}
	}
	return facts, nil
}

// initialDownload is every file the browser fetches to start entry: the
// entry's file, the files of the chunks its static imports reach, and the
// css each lists, in a fixed order, each once.
func initialDownload(chunks map[string]viteChunk, entry string) ([]string, error) {
	visited := map[string]bool{}
	seen := map[string]bool{}
	var files []string
	add := func(file string) {
		if file != "" && !seen[file] {
			seen[file] = true
			files = append(files, file)
		}
	}
	var visit func(key string) error
	visit = func(key string) error {
		if visited[key] {
			return nil
		}
		visited[key] = true
		chunk, ok := chunks[key]
		if !ok {
			return fmt.Errorf("an import names %q, which is not in the manifest", key)
		}
		if chunk.File == "" {
			return fmt.Errorf("the chunk %q names no file", key)
		}
		add(chunk.File)
		for _, css := range chunk.CSS {
			add(css)
		}
		imports := append([]string(nil), chunk.Imports...)
		sort.Strings(imports)
		for _, imported := range imports {
			if err := visit(imported); err != nil {
				return err
			}
		}
		return nil
	}
	if err := visit(entry); err != nil {
		return nil, err
	}
	sort.Strings(files)
	return files, nil
}

// measure is one file's size, raw and gzipped. The file is read to be
// compressed and its contents are dropped; only the two counts leave.
// A path that would leave the output directory is refused, never read.
func measure(outDir, file string) ([2]int64, error) {
	clean := path.Clean(strings.ReplaceAll(file, `\`, "/"))
	if path.IsAbs(clean) || clean == ".." || strings.HasPrefix(clean, "../") || windowsDrive.MatchString(clean) {
		return [2]int64{}, fmt.Errorf("a path outside the build's output directory, which is not read")
	}
	full := filepath.Join(outDir, filepath.FromSlash(clean))
	info, err := os.Stat(full)
	if errors.Is(err, fs.ErrNotExist) {
		return [2]int64{}, fmt.Errorf("the file is missing from the build")
	}
	if err != nil {
		return [2]int64{}, err
	}
	if info.Size() > maxBuildFileBytes {
		return [2]int64{}, fmt.Errorf("the file is over %d bytes, and is not read", maxBuildFileBytes)
	}
	contents, err := os.ReadFile(full)
	if err != nil {
		return [2]int64{}, err
	}
	var compressed bytes.Buffer
	writer, err := gzip.NewWriterLevel(&compressed, gzip.BestCompression)
	if err != nil {
		return [2]int64{}, err
	}
	if _, err := writer.Write(contents); err != nil {
		return [2]int64{}, err
	}
	if err := writer.Close(); err != nil {
		return [2]int64{}, err
	}
	return [2]int64{int64(len(contents)), int64(compressed.Len())}, nil
}
