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

// Diff is `culprit diff <a> <b>` as a function (Phase 30), for the same
// reason Run is one: the eval suite drives it with committed captures.
//
// # It takes captures; it does not take them
//
// The CONFIGURED bundles arrive as arguments. Capturing an environment
// needs the network, a database driver and `docker` or `kubectl`, and
// this package is `culprit check`'s pipeline — the one
// `cmd/culprit/check_test.go` asserts links no networking package at
// all. So `cmd/culprit` does the capturing (internal/capture) and hands
// the results here, and `internal/check` stays exactly as unable to open
// a socket as Phase 29 made it.
//
// # What it reports
//
// Findings that involve an environment: `intent_vs_configured` ("the code
// reads DATABASE_URL and production does not set it") and `env_vs_env`
// ("staging and production run different image digests"). Intent
// conflicts are `culprit check`'s job and are left out here, so the two
// commands answer two different questions instead of one answering both
// noisily.
type DiffOptions struct {
	ManifestPath  string
	Only          []string
	Now           time.Time
	PluginTimeout time.Duration
	SkipPlugins   bool
	Version       string
	// Captures are the environments to compare, one CONFIGURED bundle
	// each, in the order the user named them.
	Captures []model.CaptureBundle
}

// DiffReport is a Report plus the captures it compared.
type DiffReport struct {
	Report
	Captures []model.CaptureBundle
}

// Diff extracts INTENT, compares it with every capture and every capture
// with every other, classifies, suppresses, and keeps the findings that
// involve an environment.
func Diff(ctx context.Context, options DiffOptions) (DiffReport, error) {
	baseDir := filepath.Dir(options.ManifestPath)
	report := DiffReport{Report: Report{BaseDir: baseDir}, Captures: options.Captures}

	manifest, err := extract.LoadManifest(options.ManifestPath)
	if err != nil {
		return report, err
	}
	report.Manifest = manifest

	now := options.Now
	if now.IsZero() {
		now = time.Now().UTC()
	}
	intent, err := extract.Run(ctx, extract.Options{
		Manifest:              manifest,
		ManifestDir:           baseDir,
		Only:                  options.Only,
		Now:                   now,
		PluginTimeout:         options.PluginTimeout,
		SkipPlugins:           options.SkipPlugins,
		Version:               options.Version,
		RepoRelativeArtefacts: true,
	})
	if err != nil {
		return report, err
	}
	invariants, err := extract.InvariantFacts(
		manifest, filepath.Base(options.ManifestPath), now, intent.CaptureID)
	if err != nil {
		return report, err
	}
	intent.Facts = append(intent.Facts, invariants...)
	report.Bundle = intent

	report.Result = Compare(manifest, intent, options.Captures, now)
	return report, nil
}

// Compare is the part of Diff after extraction: comparison, severity,
// suppression and the environment filter. Exported for the eval suite,
// which supplies a committed INTENT bundle rather than extracting one.
func Compare(
	manifest *extract.Manifest, intent model.CaptureBundle, captures []model.CaptureBundle, now time.Time,
) diverge.Result {
	bundles := append([]model.CaptureBundle{intent}, captures...)
	result := diverge.CompareAll(bundles, diverge.Options{Now: now})

	// Severity reads which keys the code references and which have
	// defaults; those facts are all on the INTENT side, and the classifier
	// is handed everything so it sees them.
	merged := intent
	for _, capture := range captures {
		merged.Facts = append(merged.Facts, capture.Facts...)
	}
	severity.NewClassifier(manifest, merged).Apply(result.Divergences)
	manifest.ApplySuppressions(result.Divergences, now)

	kept := result.Divergences[:0]
	for _, finding := range result.Divergences {
		if finding.Kind != model.KindIntentConflict {
			kept = append(kept, finding)
		}
	}
	result.Divergences = kept
	// The unverifiable surface is a statement about INTENT alone and is
	// `culprit check --unverifiable`'s to report.
	result.Unverifiable = []diverge.Unverifiable{}
	return result
}
