package main

import (
	"crypto/ed25519"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/spf13/cobra"

	"github.com/josh-heath123/culprit/cli/internal/capture"
	"github.com/josh-heath123/culprit/cli/internal/check"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/report"
)

// `culprit env capture` and `culprit diff` — Phase 30.
//
// The first commands in this binary that read a running environment.
// Both are one-shot (field 17: "no agent daemon — capture is a one-shot
// CLI invocation this phase"), both read only what `culprit.yaml`'s
// grants for that environment allow, and both report what they were
// refused as plainly as what they found.

func newEnvCommand() *cobra.Command {
	command := &cobra.Command{
		Use:   "env",
		Short: "Read what an environment is actually configured to do",
	}
	command.AddCommand(newEnvCaptureCommand())
	return command
}

func newEnvCaptureCommand() *cobra.Command {
	var (
		manifestPath string
		format       string
		outputPath   string
		signKey      string
		only         []string
		timeout      time.Duration
	)
	command := &cobra.Command{
		Use:   "capture <environment>",
		Short: "Capture an environment's CONFIGURED facts as a sealed bundle",
		Long: `Reads one environment declared under culprit.yaml's environments: —
its environment variable names and shapes, image references and digests,
live table columns and migration version, installed packages, and
whether its endpoint resolves, connects and presents a valid certificate
— each only if its capability is granted there.

Config *values* are never captured, only their shape, unless a key is on
that environment's config.read.values allowlist. What was not granted is
listed as refused, never silently left out.

The default output is a sealed envelope (--format json): the capture's
exact bytes, their SHA-256 and, with --sign-key, an Ed25519 signature.
It holds names and shapes, and is safe to attach to a bug report —
unless config.read.values allowlists a key, whose literal value the
envelope then carries (never a report). --format text is for reading.`,
		Args: cobra.ExactArgs(1),
		RunE: func(command *cobra.Command, arguments []string) error {
			if format != "json" && format != "text" {
				return fmt.Errorf("unknown --format %q (want json or text)", format)
			}
			resolved, err := resolveManifestPath(manifestPath)
			if err != nil {
				return err
			}
			manifest, err := extract.LoadManifest(resolved)
			if err != nil {
				return err
			}
			var key ed25519.PrivateKey
			if signKey != "" {
				if key, err = capture.LoadSigningKey(signKey); err != nil {
					return err
				}
			}

			bundle, err := capture.Run(command.Context(), capture.Options{
				Manifest:    manifest,
				ManifestDir: filepath.Dir(resolved),
				Environment: arguments[0],
				Only:        only,
				Now:         captureTime(),
				Version:     Version,
				Runner:      capture.ExecRunner{Timeout: timeout},
				Network:     capture.RealNetwork{},
				Database:    capture.PostgresReader{},
			})
			if err != nil {
				return err
			}

			writer, closer, err := outputWriter(command.OutOrStdout(), outputPath)
			if err != nil {
				return err
			}
			defer func() { _ = closer() }()
			if format == "text" {
				return report.RenderCapture(writer, bundle)
			}
			envelope, err := capture.Seal(bundle, key)
			if err != nil {
				return err
			}
			encoder := json.NewEncoder(writer)
			encoder.SetIndent("", "  ")
			return encoder.Encode(envelope)
		},
	}
	command.Flags().StringVarP(&manifestPath, "file", "f", "",
		"path to culprit.yaml (default: search upward from the working directory)")
	command.Flags().StringVar(&format, "format", "json",
		"json (a sealed capture envelope) or text")
	command.Flags().StringVarP(&outputPath, "output", "o", "",
		"write to this file instead of stdout")
	command.Flags().StringVar(&signKey, "sign-key", "",
		"sign the envelope with this Ed25519 private key (PKCS#8 PEM, as `openssl genpkey -algorithm ed25519` writes)")
	command.Flags().StringSliceVar(&only, "component", nil,
		"capture only these components (repeatable)")
	command.Flags().DurationVar(&timeout, "command-timeout", 30*time.Second,
		"how long any one docker, kubectl or allowlisted command may run")
	return command
}

func newDiffCommand() *cobra.Command {
	var (
		manifestPath string
		format       string
		outputPath   string
		failOn       string
		only         []string
		noPlugins    bool
		pluginTime   time.Duration
		commandTime  time.Duration
	)
	command := &cobra.Command{
		Use:   "diff <a> <b>",
		Short: "Compare two environments with each other and with what the repository intends",
		Long: `Each of <a> and <b> is either an environment declared in culprit.yaml,
captured now, or the path to a capture envelope written earlier by
` + "`culprit env capture`" + ` — an envelope is verified before it is used.

Reports two kinds of finding: an environment that fails what the
repository declares (the code reads DATABASE_URL and production does not
set it; the live schema is behind the migration head), and two
environments that differ from each other (different image digests,
different installed versions, a key set to a different kind of value).

Everything the capture was refused is listed. Exit codes as for
` + "`culprit check`" + `: 0 clean, 1 findings at or above --fail-on, 2 error.`,
		Args: cobra.ExactArgs(2),
		RunE: func(command *cobra.Command, arguments []string) error {
			threshold, err := parseFailOn(failOn)
			if err != nil {
				return err
			}
			if !report.KnownFormat(format) {
				return fmt.Errorf("unknown --format %q (want text, json, sarif or junit)", format)
			}
			resolved, err := resolveManifestPath(manifestPath)
			if err != nil {
				return err
			}
			manifest, err := extract.LoadManifest(resolved)
			if err != nil {
				return err
			}

			now := captureTime()
			captures := make([]model.CaptureBundle, 0, 2)
			for _, argument := range arguments {
				bundle, err := obtainCapture(command, manifest, resolved, argument, only, now, commandTime)
				if err != nil {
					return err
				}
				captures = append(captures, bundle)
			}
			if captureName(captures[0]) == captureName(captures[1]) {
				return fmt.Errorf("both sides are environment %q; a diff needs two", captureName(captures[0]))
			}

			result, err := check.Diff(command.Context(), check.DiffOptions{
				ManifestPath:  resolved,
				Only:          only,
				Now:           now,
				PluginTimeout: pluginTime,
				SkipPlugins:   noPlugins,
				Version:       Version,
				Captures:      captures,
			})
			if err != nil {
				return err
			}

			writer, closer, err := outputWriter(command.OutOrStdout(), outputPath)
			if err != nil {
				return err
			}
			if err := report.Render(writer, format, report.Input{
				Result:   result.Result,
				Bundle:   result.Bundle,
				Version:  Version,
				Root:     result.BaseDir,
				Captures: result.Captures,
			}); err != nil {
				_ = closer()
				return err
			}
			if err := closer(); err != nil {
				return err
			}
			warnExpiredSuppressions(command.ErrOrStderr(), result.Manifest, now)

			if count := check.CountAtOrAbove(result.Result.Divergences, threshold); count > 0 {
				return &findingsError{count: count, threshold: threshold}
			}
			return nil
		},
	}
	command.Flags().StringVarP(&manifestPath, "file", "f", "",
		"path to culprit.yaml (default: search upward from the working directory)")
	command.Flags().StringVar(&format, "format", "text", "output format: text, json, sarif or junit")
	command.Flags().StringVarP(&outputPath, "output", "o", "", "write the report to this file instead of stdout")
	command.Flags().StringVar(&failOn, "fail-on", "degrades",
		"exit 1 when a finding reaches this severity: breaks_request_path, degrades or any")
	command.Flags().StringSliceVar(&only, "component", nil, "only these components (repeatable)")
	command.Flags().BoolVar(&noPlugins, "no-plugins", false,
		"extract INTENT with the built-in artefact readers only, skipping every extractor plugin")
	command.Flags().DurationVar(&pluginTime, "plugin-timeout", extract.DefaultPluginTimeout,
		"how long any one extractor plugin may run before it is skipped")
	command.Flags().DurationVar(&commandTime, "command-timeout", 30*time.Second,
		"how long any one docker, kubectl or allowlisted command may run")
	return command
}

// obtainCapture turns one diff argument into a CONFIGURED bundle: an
// existing file is an envelope to verify, anything else an environment to
// capture now.
//
// A file wins when both could apply, and the envelope is *verified*, not
// trusted: a capture whose digest or signature does not match is refused
// rather than compared, because a comparison against an altered capture
// is a finding about an environment nobody observed.
func obtainCapture(
	command *cobra.Command, manifest *extract.Manifest, manifestPath, argument string,
	only []string, now time.Time, commandTimeout time.Duration,
) (model.CaptureBundle, error) {
	if info, err := os.Stat(argument); err == nil && !info.IsDir() {
		verified, err := capture.ReadEnvelope(argument)
		if err != nil {
			return model.CaptureBundle{}, err
		}
		return verified.Bundle, nil
	}
	return capture.Run(command.Context(), capture.Options{
		Manifest:    manifest,
		ManifestDir: filepath.Dir(manifestPath),
		Environment: argument,
		Only:        only,
		Now:         now,
		Version:     Version,
		Runner:      capture.ExecRunner{Timeout: commandTimeout},
		Network:     capture.RealNetwork{},
		Database:    capture.PostgresReader{},
	})
}

func captureName(bundle model.CaptureBundle) string {
	if bundle.Environment != nil {
		return *bundle.Environment
	}
	return ""
}
