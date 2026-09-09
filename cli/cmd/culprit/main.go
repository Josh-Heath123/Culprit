// Command culprit is the Culprit CLI and, from Phase 31, the probe agent
// (D2 — one static binary, two subcommands).
//
// Phase 28 ships exactly one working subcommand: `culprit intent`, which
// builds an INTENT fact set for a repository and prints it. It compares
// nothing, opens no socket, and reads no environment (field 17). The
// entire value proposition of this phase is that a developer can run one
// command in a checkout with nothing installed and get a truthful
// inventory of what their system claims to be, including an explicit
// list of what could not be established and why.
package main

import (
	"context"
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

// Exit codes. Named because they are a contract with CI: a script
// distinguishing "the command failed" from "the command ran and found
// something" needs them to be stable from the first release.
//
// exitFindings (2) is deliberately reserved and unused this phase.
// `culprit intent` has no findings to report — that is Phase 29 — and
// allocating the code now means Phase 29 does not have to renumber
// anything a user has already written a CI condition against.
const (
	exitOK        = 0
	exitError     = 1
	_exitFindings = 2 //nolint:unused // reserved for Phase 29
)

func main() {
	if err := newRootCommand().Execute(); err != nil {
		fmt.Fprintln(os.Stderr, "culprit:", err)
		os.Exit(exitError)
	}
	os.Exit(exitOK)
}

func newRootCommand() *cobra.Command {
	root := &cobra.Command{
		Use:   "culprit",
		Short: "Find out what your system is supposed to do, and what it actually does",
		Long: `culprit builds three planes of truth about a system —
INTENT (what it is supposed to do), CONFIGURED (what an environment is
set up to do) and OBSERVED (what actually happened) — and reports where
they diverge.

This build implements the INTENT plane only. See docs/DIAGNOSTIC_PLAN.md.`,
		SilenceUsage:  true,
		SilenceErrors: true,
		Version:       Version,
	}
	root.AddCommand(newIntentCommand())
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
