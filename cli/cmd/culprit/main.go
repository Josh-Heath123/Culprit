// Command culprit is the Culprit CLI and, from Phase 31, the probe agent
// (D2 — one static binary, two subcommands).
//
// `culprit intent` (Phase 28) prints what a repository says the system is
// supposed to do; `culprit check` (Phase 29) compares that with itself.
// Neither opens a socket or reads an environment. `culprit env capture`
// and `culprit diff` (Phase 30) are the first commands that do — reading
// a running environment's configuration under the capability grants
// `culprit.yaml` declares for it, once, and never sending a request into
// the system under test.
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"time"

	"github.com/spf13/cobra"

	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/render"
)

// Version is stamped at build time with -ldflags. The fallback is
// "dev" rather than a plausible-looking number, so an unstamped binary
// is obvious in a bug report instead of claiming to be a release.
var Version = "dev"

// Exit codes — Phase 29 field 7, verbatim: `0` clean, `1` divergences at
// or above the configured severity, `2` execution error.
//
// **This corrects Phase 28, which had 1 and 2 the other way round.** That
// binary reserved 2 for findings and used 1 for errors, on the reasonable
// but wrong assumption that "error" is the lower code. The plan is the
// contract and it says otherwise, and the plan is right: the useful
// distinction for a CI script is `if culprit check; then` — clean — with
// 1 meaning "the tool worked and your build has a problem" and 2 meaning
// "the tool itself could not run", which is a different alert entirely.
// Nothing depends on the old numbering: `culprit intent` has no findings
// and Phase 28 is unreleased.
const (
	exitOK       = 0
	exitFindings = 1
	exitError    = 2
)

func main() {
	if err := newRootCommand().Execute(); err != nil {
		// A findingsError is not a failure of the command; it is the
		// command's answer. It has already printed its report, so it exits
		// quietly with the code CI reads rather than printing an error
		// line that would make a real finding look like a crash.
		var findings *findingsError
		if errors.As(err, &findings) {
			os.Exit(exitFindings)
		}
		var partial *partialDiagnosisError
		if errors.As(err, &partial) {
			os.Exit(exitFindings)
		}
		var unverified *verificationError
		if errors.As(err, &unverified) {
			os.Exit(exitFindings)
		}
		fmt.Fprintln(os.Stderr, "culprit:", err)
		os.Exit(exitError)
	}
	os.Exit(exitOK)
}

// findingsError signals "the run succeeded and found something at or
// above --fail-on". A sentinel error rather than a direct os.Exit from
// inside RunE, so the cobra command stays testable in-process: a test
// asserts on the returned error, and only main turns it into a status.
type findingsError struct {
	count     int
	threshold model.Severity
}

func (e *findingsError) Error() string {
	return fmt.Sprintf("%d divergence(s) at or above %s", e.count, e.threshold)
}

func newRootCommand() *cobra.Command {
	root := &cobra.Command{
		Use:   "culprit",
		Short: "Find out what your system is supposed to do, and what it actually does",
		Long: `culprit builds three planes of truth about a system —
INTENT (what it is supposed to do), CONFIGURED (what an environment is
set up to do) and OBSERVED (what actually happened) — and reports where
they diverge.

This build implements the INTENT plane (culprit intent, culprit check),
the CONFIGURED plane (culprit env capture, culprit diff) and the
OBSERVED plane (culprit probe). See docs/DIAGNOSTIC_PLAN.md,
docs/PROBES.md for what each probe asks of a running system, and
docs/PERMISSIONS.md before granting it access to an environment.`,
		SilenceUsage:  true,
		SilenceErrors: true,
		Version:       Version,
	}
	root.AddCommand(newIntentCommand())
	root.AddCommand(newCheckCommand())
	root.AddCommand(newEnvCommand())
	root.AddCommand(newDiffCommand())
	root.AddCommand(newProbeCommand())
	root.AddCommand(newDiagnoseCommand())
	root.AddCommand(newVerifyCommand())
	root.AddCommand(newAgentCommand())
	root.AddCommand(newMCPCommand())
	return root
}

func newIntentCommand() *cobra.Command {
	var (
		manifestPath string
		format       string
		only         []string
		wants        []string
		noPlugins    bool
		timeout      time.Duration
	)

	command := &cobra.Command{
		Use:   "intent",
		Short: "Extract what this repository says the system is supposed to do",
		Long: `Reads culprit.yaml, runs the built-in artefact readers and any
configured extractor plugins, and prints an INTENT fact set.

Nothing is compared and nothing is uploaded. With no extractor
installed this still reports every fact the committed artefacts support,
and says precisely what it could not establish and why — a skipped
source is a visible gap in the report, never a silent one.`,
		Args: cobra.NoArgs,
		RunE: func(command *cobra.Command, _ []string) error {
			resolved, err := resolveManifestPath(manifestPath)
			if err != nil {
				return err
			}
			manifest, err := extract.LoadManifest(resolved)
			if err != nil {
				return err
			}

			parsedWants := make([]model.Want, 0, len(wants))
			for _, want := range wants {
				parsedWants = append(parsedWants, model.Want(want))
			}

			bundle, err := extract.Run(context.Background(), extract.Options{
				Manifest:      manifest,
				ManifestDir:   filepath.Dir(resolved),
				Only:          only,
				Want:          parsedWants,
				Now:           captureTime(),
				PluginTimeout: timeout,
				SkipPlugins:   noPlugins,
				Version:       Version,
			})
			if err != nil {
				return err
			}

			switch format {
			case "json":
				return render.JSON(command.OutOrStdout(), bundle)
			case "text":
				return render.Text(command.OutOrStdout(), bundle)
			default:
				return fmt.Errorf("unknown --format %q (want json or text)", format)
			}
		},
	}

	command.Flags().StringVarP(&manifestPath, "file", "f", "",
		"path to culprit.yaml (default: search upward from the working directory)")
	command.Flags().StringVar(&format, "format", "text", "output format: text or json")
	command.Flags().StringSliceVar(&only, "component", nil,
		"extract only these components (repeatable)")
	command.Flags().StringSliceVar(&wants, "want", nil,
		"extract only these classes of fact (repeatable): "+
			"http_routes, db_schema, config_keys, client_calls, test_assertions, dependencies")
	command.Flags().BoolVar(&noPlugins, "no-plugins", false,
		"run the built-in artefact readers only, skipping every extractor plugin")
	command.Flags().DurationVar(&timeout, "plugin-timeout", extract.DefaultPluginTimeout,
		"how long any one extractor plugin may run before it is skipped")
	return command
}

// captureTime is the instant stamped on every fact in a run.
//
// `SOURCE_DATE_EPOCH` overrides it, honouring the reproducible-builds
// convention rather than inventing a flag. Acceptance criterion 2 is
// that "running it twice on an unchanged tree produces byte-identical
// output", and a capture legitimately records *when* it was taken —
// `captured_at` and the content-derived capture id both move with the
// clock, so two runs seconds apart differ in exactly those fields and
// nothing else.
//
// Pinning the clock makes the criterion literally checkable by a person
// at a terminal, not only by a test with an injected clock:
//
//	SOURCE_DATE_EPOCH=0 culprit intent --format json > a.json
//	SOURCE_DATE_EPOCH=0 culprit intent --format json > b.json
//	diff a.json b.json     # empty
//
// An unparseable value is ignored rather than fatal: this is a
// reproducibility aid, and refusing to run because of a malformed
// environment variable would be a worse failure than not honouring it.
func captureTime() time.Time {
	if raw := os.Getenv("SOURCE_DATE_EPOCH"); raw != "" {
		if seconds, err := strconv.ParseInt(raw, 10, 64); err == nil {
			return time.Unix(seconds, 0).UTC()
		}
	}
	return time.Now().UTC()
}

// resolveManifestPath finds culprit.yaml.
//
// Searching upward from the working directory, rather than requiring
// -f, because the command has to work when run from a subdirectory of a
// repository — which in CI is most of the time. The search stops at the
// filesystem root and reports what it looked for, so "not found" names
// the actual problem rather than failing on a nil manifest later.
func resolveManifestPath(explicit string) (string, error) {
	if explicit != "" {
		absolute, err := filepath.Abs(explicit)
		if err != nil {
			return "", err
		}
		if _, err := os.Stat(absolute); err != nil {
			return "", fmt.Errorf("%s: %w", explicit, err)
		}
		return absolute, nil
	}

	directory, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		for _, name := range []string{"culprit.yaml", "culprit.yml"} {
			candidate := filepath.Join(directory, name)
			if _, err := os.Stat(candidate); err == nil {
				return candidate, nil
			}
		}
		parent := filepath.Dir(directory)
		if parent == directory {
			return "", fmt.Errorf(
				"no culprit.yaml found here or in any parent directory. " +
					"Create one describing your components, or pass -f. " +
					"See docs/EXTRACTOR_PROTOCOL.md")
		}
		directory = parent
	}
}
