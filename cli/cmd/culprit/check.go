package main

import (
	"fmt"
	"io"
	"os"
	"time"

	"github.com/spf13/cobra"

	"github.com/josh-heath123/culprit/cli/internal/check"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/report"
)

// `culprit check` — Phase 29's whole product.
//
// It extracts, compares, classifies, suppresses and reports, in that
// order, and exits with a code CI can branch on. No environment access,
// no probes, no network: the only thing it opens is files in the
// repository it was pointed at.
//
// The pipeline is deliberately visible in one function rather than
// hidden behind an orchestrator object. Six named steps a reader can
// follow is worth more here than an abstraction, because the order is
// load-bearing — suppression must come after severity (a suppressed
// finding still records how bad it would have been), and severity must
// come after comparison (it classifies findings, not facts).

func newCheckCommand() *cobra.Command {
	var (
		manifestPath string
		format       string
		outputPath   string
		failOn       string
		unverifiable bool
		only         []string
		noPlugins    bool
		timeout      time.Duration
	)

	command := &cobra.Command{
		Use:   "check",
		Short: "Compare everything this repository says about itself, and report the disagreements",
		Long: `Extracts an INTENT fact set the way ` + "`culprit intent`" + ` does, then
compares every fact against every other fact about the same subject and
reports where two sources disagree.

No environment is read, no service is contacted and no model provider is
called. Everything it knows comes from files in the repository, which is
why it works in a pull-request check on a fork with no secrets.

Exit codes: 0 clean, 1 findings at or above --fail-on, 2 the command
could not run.`,
		Args: cobra.NoArgs,
		RunE: func(command *cobra.Command, _ []string) error {
			threshold, err := parseFailOn(failOn)
			if err != nil {
				return err
			}
			if !report.KnownFormat(format) {
				return fmt.Errorf(
					"unknown --format %q (want text, json, sarif or junit)", format)
			}

			resolved, err := resolveManifestPath(manifestPath)
			if err != nil {
				return err
			}

			result, err := check.Run(command.Context(), check.Options{
				ManifestPath:  resolved,
				Only:          only,
				Now:           captureTime(),
				PluginTimeout: timeout,
				SkipPlugins:   noPlugins,
				Version:       Version,
			})
			if err != nil {
				return err
			}

			writer, closer, err := outputWriter(command.OutOrStdout(), outputPath)
			if err != nil {
				return err
			}
			if err := report.Render(writer, format, report.Input{
				Result:           result.Result,
				Bundle:           result.Bundle,
				Version:          Version,
				Root:             result.BaseDir,
				ShowUnverifiable: unverifiable,
			}); err != nil {
				_ = closer()
				return err
			}
			if err := closer(); err != nil {
				return err
			}

			warnExpiredSuppressions(command.ErrOrStderr(), result.Manifest, captureTime())

			count := check.CountAtOrAbove(result.Result.Divergences, threshold)
			if count > 0 {
				return &findingsError{count: count, threshold: threshold}
			}
			return nil
		},
	}

	command.Flags().StringVarP(&manifestPath, "file", "f", "",
		"path to culprit.yaml (default: search upward from the working directory)")
	command.Flags().StringVar(&format, "format", "text",
		"output format: text, json, sarif or junit")
	command.Flags().StringVarP(&outputPath, "output", "o", "",
		"write the report to this file instead of stdout")
	command.Flags().StringVar(&failOn, "fail-on", "degrades",
		"exit 1 when a finding reaches this severity: breaks_request_path, degrades or any")
	command.Flags().BoolVar(&unverifiable, "unverifiable", false,
		"also report subjects only one source describes, where nothing could catch a mistake")
	command.Flags().StringSliceVar(&only, "component", nil,
		"check only these components (repeatable)")
	command.Flags().BoolVar(&noPlugins, "no-plugins", false,
		"run the built-in artefact readers only, skipping every extractor plugin")
	command.Flags().DurationVar(&timeout, "plugin-timeout", extract.DefaultPluginTimeout,
		"how long any one extractor plugin may run before it is skipped")
	return command
}

// parseFailOn maps the flag onto a severity threshold.
//
// The default is `degrades`, not `any`. A tool whose out-of-the-box
// setting fails a build on a cosmetic dependency-version disagreement
// gets its default changed to `any`-off by the second afternoon, and
// after that nobody trusts it. `degrades` fails on the two severities
// that mean something is actually wrong and stays quiet on the rest,
// which are still reported — they are just not a build failure.
func parseFailOn(value string) (model.Severity, error) {
	switch value {
	case "breaks_request_path":
		return model.SeverityBreaksRequestPath, nil
	case "degrades":
		return model.SeverityDegrades, nil
	case "any":
		// `cosmetic` has rank 0, so every severity is at or above it —
		// including `unknown`, which is the point of ranking unknown
		// above cosmetic rather than below.
		return model.SeverityCosmetic, nil
	default:
		return "", fmt.Errorf(
			"unknown --fail-on %q (want breaks_request_path, degrades or any)", value)
	}
}

// warnExpiredSuppressions says so on stderr, never on stdout.
//
// stdout carries the report, which may be JSON or SARIF a machine is
// parsing; a friendly note printed into it would corrupt the artefact.
// An expired suppression is worth a word because the line is still
// sitting in `culprit.yaml` looking as though it does something.
func warnExpiredSuppressions(writer io.Writer, manifest *extract.Manifest, now time.Time) {
	expired := manifest.ExpiredSuppressions(now)
	for _, suppression := range expired {
		fmt.Fprintf(writer,
			"culprit: the suppression for %s expired on %s and no longer applies (%s)\n",
			suppression.Subject, suppression.Expires, suppression.Reason)
	}
}

// outputWriter returns the destination and a closer that is safe to call
// exactly once, whether the destination is a file or stdout.
func outputWriter(stdout io.Writer, path string) (io.Writer, func() error, error) {
	if path == "" {
		return stdout, func() error { return nil }, nil
	}
	file, err := os.Create(path)
	if err != nil {
		return nil, nil, fmt.Errorf("cannot write %s: %w", path, err)
	}
	closed := false
	return file, func() error {
		if closed {
			return nil
		}
		closed = true
		return file.Close()
	}, nil
}
