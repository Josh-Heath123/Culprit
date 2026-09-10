// Package check is the `culprit check` pipeline as a function.
//
// It lives here rather than inside the cobra command for one reason:
// the eval suite (Phase 29 field 13) has to run the *whole* pipeline
// against a fixture and assert the exact divergence set it produces. A
// pipeline that can only be reached by building a binary and parsing its
// stdout is a pipeline whose evals are slow, flaky and written against
// rendered text — and the eval suite is the thing that will tell us, for
// every phase after this one, whether a change made the tool better or
// merely different.
package check

import (
	"context"
	"path/filepath"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/diverge"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/severity"
)

// Options configure one check.
type Options struct {
	// ManifestPath is an absolute path to culprit.yaml.
	ManifestPath  string
	Only          []string
	Now           time.Time
	PluginTimeout time.Duration
	SkipPlugins   bool
	Version       string
}

// Report is everything one check produced.
type Report struct {
	Manifest *extract.Manifest
	Bundle   model.CaptureBundle
	Result   diverge.Result
	// Suppressed is how many findings a suppression silenced.
	Suppressed int
	BaseDir    string
}

// Run performs the six steps, in the order they must happen in.
//
// The order is load-bearing and is the reason this is a flat function
// rather than a set of independent helpers a caller composes:
//
//  1. extract — the same code path `culprit intent` uses, with artefact
//     paths rebased onto the repository so a report can point at a file
//     that resolves from the root.
//  2. add invariants as rank-100 facts, so the generic comparator sees
//     a developer's assertion as just another source.
//  3. compare.
//  4. classify severity — after comparison, because it classifies
//     findings, not facts.
//  5. suppress — after severity, so a suppressed finding still records
//     how bad it would have been.
func Run(ctx context.Context, options Options) (Report, error) {
	baseDir := filepath.Dir(options.ManifestPath)
	report := Report{BaseDir: baseDir}

	manifest, err := extract.LoadManifest(options.ManifestPath)
	if err != nil {
		return report, err
	}
	report.Manifest = manifest

	now := options.Now
	if now.IsZero() {
		now = time.Now().UTC()
	}

	bundle, err := extract.Run(ctx, extract.Options{
		Manifest:      manifest,
		ManifestDir:   baseDir,
		Only:          options.Only,
		Now:           now,
		PluginTimeout: options.PluginTimeout,
		SkipPlugins:   options.SkipPlugins,
		Version:       options.Version,
		// Report paths must resolve from the repository root, or a SARIF
		// annotation silently fails to land. Done inside extraction,
		// where the component that *produced* each fact is known — see
		// extract.rebaseTarget.
		RepoRelativeArtefacts: true,
	})
	if err != nil {
		return report, err
	}

	invariants, err := extract.InvariantFacts(
		manifest, filepath.Base(options.ManifestPath), now, bundle.CaptureID)
	if err != nil {
		return report, err
	}
	bundle.Facts = append(bundle.Facts, invariants...)
	report.Bundle = bundle

	report.Result = diverge.Compare(bundle, diverge.Options{Now: now})
	severity.NewClassifier(manifest, bundle).Apply(report.Result.Divergences)
	report.Suppressed = manifest.ApplySuppressions(report.Result.Divergences, now)
	return report, nil
}

// CountAtOrAbove counts the findings that should fail a build.
//
// Suppressed findings never count, whatever their severity. That is what
// a suppression is for, and the report still lists them with the reason
// somebody gave, so the decision stays visible rather than becoming
// invisible.
func CountAtOrAbove(divergences []model.Divergence, threshold model.Severity) int {
	count := 0
	for _, finding := range divergences {
		if finding.Status == model.StatusSuppressed {
			continue
		}
		if finding.Severity.AtLeast(threshold) {
			count++
		}
	}
	return count
}
