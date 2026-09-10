package extract

import (
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Built-in artefact readers (D3: "Built-in artefact readers (in Go, no
// plugin needed) — OpenAPI, JSON Schema, .env.example, compose/k8s YAML,
// lockfiles, Terraform state").
//
// These are the reason `culprit intent` is useful with nothing
// installed, which is acceptance criterion 4. They read files that are
// already machine-readable declarations of intent — preference order
// rule 1 in .claude/rules/model.md — and never parse application code.
//
// Every reader has the same shape: given a root and a capture context,
// return facts and, when it looked and found nothing, a Skip saying so.
// "I found no OpenAPI document" is a different and more useful report
// line than silence.

// captureContext carries what every fact needs and no reader should have to
// thread through by hand.
type captureContext struct {
	Component  string
	Root       string
	CaptureID  string
	CapturedAt time.Time
	// Extractor is the identity written into every fact's provenance.
	Extractor string
}

// reader is one built-in artefact reader.
type reader struct {
	// want is the class of fact this reader contributes to, so a Skip it
	// produces lands under the right heading.
	want model.Want
	name string
	run  func(ctx captureContext) ([]model.Fact, []model.Skip)
}

// maxScanDepth bounds the directory walk. A repository with a vendored
// node_modules or a .venv contains tens of thousands of files that say
// nothing about this project's intent, and walking them turns a
// sub-second command into a minute. Bounded and documented rather than
// unbounded and surprising — see docs/LIMITS.md.
const maxScanDepth = 6

// skipDirs are never descended into. Third-party code, build output and
// caches: a dependency's own openapi.json is not this system's intent,
// and reading it would emit facts about routes this component does not
// serve.
var skipDirs = map[string]bool{
	".git":          true,
	"node_modules":  true,
	".venv":         true,
	"venv":          true,
	"__pycache__":   true,
	"site-packages": true,
	"dist":          true,
	"build":         true,
	".next":         true,
	".tox":          true,
	"target":        true,
	"vendor":        true,
	".mypy_cache":   true,
	".pytest_cache": true,
	".ruff_cache":   true,
}

// findFiles walks root looking for files whose base name matches, or
// whose name ends with one of the given suffixes.
//
// Deterministic order, always: filepath.WalkDir is lexical, and the
// results are used to build a fact list whose byte-for-byte stability
// across runs is acceptance criterion 2.
func findFiles(root string, match func(name string) bool) []string {
	var found []string
	rootDepth := strings.Count(filepath.Clean(root), string(filepath.Separator))
	_ = filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			// An unreadable directory is skipped, not fatal. A CI
			// checkout with an odd permission somewhere must still
			// produce a report.
			if entry != nil && entry.IsDir() {
				return fs.SkipDir
			}
			return nil
		}
		if entry.IsDir() {
			if path != root && skipDirs[entry.Name()] {
				return fs.SkipDir
			}
			if strings.Count(filepath.Clean(path), string(filepath.Separator))-rootDepth > maxScanDepth {
				return fs.SkipDir
			}
			return nil
		}
		if match(entry.Name()) {
			found = append(found, path)
		}
		return nil
	})
	return found
}

// relative renders a path for a fact's provenance.artefact. Always
// forward-slashed and always relative to the extraction root, so a fact
// captured on Windows and one captured in CI name the same artefact.
func relative(root, path string) string {
	rel, err := filepath.Rel(root, path)
	if err != nil {
		return filepath.ToSlash(path)
	}
	return filepath.ToSlash(rel)
}

func (c captureContext) provenance(kind model.SourceKind, artefact, locator string, rank int) model.Provenance {
	return model.Provenance{
		SourceKind:     kind,
		Extractor:      c.Extractor,
		Artefact:       artefact,
		Locator:        locator,
		ConfidenceRank: rank,
	}
}

// fact assembles an INTENT fact and validates it. A reader that builds
// an invalid fact drops it rather than emitting it: an unvalidated fact
// is one that will fail at the API boundary later, in a place with far
// less context about what produced it.
func (c captureContext) fact(subject, predicate string, value any, provenance model.Provenance) (model.Fact, bool) {
	candidate := model.Fact{
		Plane:      model.PlaneIntent,
		Subject:    subject,
		Predicate:  predicate,
		Value:      value,
		Provenance: provenance,
		CapturedAt: c.CapturedAt,
		CaptureID:  c.CaptureID,
	}
	if err := candidate.Validate(); err != nil {
		return model.Fact{}, false
	}
	return candidate, true
}

// configFact is the only way a reader may say anything about a config
// key. It takes a shape and has no parameter a literal could go through.
//
// The predicate is a parameter rather than a constant because a shape is
// only meaningful alongside what kind of shape it is — see
// model.PredicateValueShape for the false positive that taught us so.
func (c captureContext) configFact(
	key, predicate string, shape model.ValueShape, provenance model.Provenance,
) (model.Fact, bool) {
	candidate, err := model.NewConfigFact(
		model.PlaneIntent, c.Component, key, predicate,
		shape, provenance, c.CapturedAt, c.CaptureID)
	if err != nil {
		return model.Fact{}, false
	}
	return candidate, true
}

func readFile(path string) (string, bool) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", false
	}
	return string(data), true
}
