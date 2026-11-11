package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/josh-heath123/culprit/cli/internal/capability"
	"github.com/josh-heath123/culprit/cli/internal/capture"
	"github.com/josh-heath123/culprit/cli/internal/check"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/probe"
	"github.com/josh-heath123/culprit/cli/internal/report"
)

// `culprit probe` — Phase 31.
//
// The first command in this binary that takes an active reading: it asks
// a running system a question rather than comparing two descriptions of
// one.
//
// Field 17 draws the line this command stops at. It runs the probes a
// human or a script names. It does not choose them — there is no
// selection logic here, no fault tree, and nothing that decides what is
// worth asking next. That is Phase 32, and building it early would mean
// shipping a tool that looks like it is reasoning when it is guessing.

func newProbeCommand() *cobra.Command {
	var (
		manifestPath string
		environment  string
		format       string
		outputPath   string
		probeIDs     []string
		inputPairs   []string
		timeout      time.Duration
		list         bool
		agentID      string
		capturePath  string
		noPlugins    bool
		pluginTime   time.Duration
	)

	command := &cobra.Command{
		Use:   "probe [target]",
		Short: "Take an active reading against a running system",
		Long: `Runs named probes against a subject and reports what came back.

A target is a subject URI: a component (component:orders-api), a
connection (connection:orders-api->payments-api), or an auth relationship
(auth:web->orders-api/audience).

Every probe declares the capabilities it needs, and the runner refuses to
execute one whose capabilities this environment does not grant — that
refusal is reported, not skipped. A probe whose preconditions are unmet
returns inconclusive with a reason rather than a guess.

Nothing here writes to the system under test. No probe declares
effect: mutate, no *.write capability exists, and the HTTP client has no
method that can send a body.

Examples:
  culprit probe --list
  culprit probe connection:orders-api->payments-api --env staging
  culprit probe component:orders-api -p probe.net.tls_validity \
      --input host=orders.example.com --input port=443`,
		Args: cobra.MaximumNArgs(1),
		RunE: func(command *cobra.Command, args []string) error {
			catalogue := probe.BuiltIn()

			if list {
				return renderCatalogue(command.OutOrStdout(), format, catalogue)
			}
			if len(args) == 0 {
				return fmt.Errorf(
					"a target is required, e.g. `culprit probe component:orders-api`; " +
						"`culprit probe --list` shows the available probes")
			}
			target := args[0]
			if _, _, err := model.ParseSubject(target); err != nil {
				return fmt.Errorf(
					"%q is not a subject URI (%w). Targets look like "+
						"component:orders-api or connection:orders-api->payments-api",
					target, err)
			}

			inputs, err := parseInputs(inputPairs)
			if err != nil {
				return err
			}
			readings, ledger, err := runProbe(command.Context(), probeInput{
				ManifestPath: manifestPath, Environment: environment, Target: target, ProbeIDs: probeIDs,
				Inputs: inputs, AgentID: agentID, CapturePath: capturePath, NoPlugins: noPlugins,
				PluginTimeout: pluginTime, Timeout: timeout,
			})
			if err != nil {
				return err
			}

			if err := writeReadings(command, format, outputPath, readings, ledger); err != nil {
				return err
			}

			// The same exit-code contract every other command keeps:
			// 0 clean, 1 findings, 2 execution error. A failing probe is a
			// finding; inconclusive and refused are not, because neither
			// established that anything is wrong.
			failures := 0
			for _, reading := range readings {
				if reading.Verdict == model.VerdictFail {
					failures++
				}
			}
			if failures > 0 {
				return &findingsError{count: failures, threshold: "fail"}
			}
			return nil
		},
	}

	command.Flags().StringVarP(&manifestPath, "file", "f", "culprit.yaml",
		"path to culprit.yaml")
	command.Flags().StringVar(&environment, "env", "",
		"which environment declared under environments: this reading is about")
	command.Flags().StringVar(&format, "format", "text", "text|json")
	command.Flags().StringVarP(&outputPath, "output", "o", "",
		"write to this file instead of stdout")
	command.Flags().StringSliceVarP(&probeIDs, "probe", "p", nil,
		"probe id to run (repeatable); default is every probe in the catalogue")
	command.Flags().StringSliceVar(&inputPairs, "input", nil,
		"probe input as key=value (repeatable)")
	command.Flags().DurationVar(&timeout, "timeout", 10*time.Second,
		"per-operation network timeout")
	command.Flags().BoolVar(&list, "list", false,
		"list the probe catalogue and exit")
	command.Flags().StringVar(&agentID, "agent-id", "culprit-cli",
		"identifies who took these readings")
	command.Flags().StringVar(&capturePath, "capture", "",
		"a sealed capture of --env (culprit env capture -o), used as the CONFIGURED "+
			"expectation for probes measured against configuration")
	command.Flags().BoolVar(&noPlugins, "no-plugins", false,
		"resolve expectations from the built-in artefact readers only, skipping extractor plugins")
	command.Flags().DurationVar(&pluginTime, "plugin-timeout", extract.DefaultPluginTimeout,
		"how long any one extractor plugin may run before it is skipped")

	return command
}

// probeInput is one run of named probes, as `culprit probe` and the
// culprit_probe tool both ask for it.
type probeInput struct {
	ManifestPath, Environment, Target, AgentID, CapturePath string
	// ProbeIDs are the probes to run; none means every probe in the
	// catalogue (the command's default).
	ProbeIDs               []string
	Inputs                 map[string]any
	NoPlugins              bool
	PluginTimeout, Timeout time.Duration
	// Through, when set, is what probes reach the network through; nil is
	// the real network. Only tests set it.
	Through *wire
}

// runProbe runs the named probes against one target, under the
// environment's grants, and returns the readings and the ledger that
// decided them.
func runProbe(ctx context.Context, in probeInput) ([]model.Reading, *capability.Ledger, error) {
	catalogue := probe.BuiltIn()
	resolved, err := resolveManifestPath(in.ManifestPath)
	if err != nil {
		return nil, nil, err
	}
	manifest, err := extract.LoadManifest(resolved)
	if err != nil {
		return nil, nil, err
	}

	grants, err := grantsFor(manifest, in.Environment)
	if err != nil {
		return nil, nil, err
	}
	ledger := capability.NewLedger(grants)

	// What the readings are measured against (Phase 31.1). INTENT comes
	// from the very pipeline `culprit check` runs — the same extractors
	// and invariants, not a second extraction path — so a probe and a
	// check cannot disagree about what the code declares. CONFIGURED
	// comes from a Phase 30 capture, when one is given.
	intent, err := check.Run(ctx, check.Options{
		ManifestPath:  resolved,
		Now:           captureTime(),
		PluginTimeout: in.PluginTimeout,
		SkipPlugins:   in.NoPlugins,
		Version:       Version,
	})
	if err != nil {
		return nil, nil, err
	}
	factSets := [][]model.Fact{intent.Bundle.Facts}
	if in.CapturePath != "" {
		verified, err := capture.ReadEnvelope(in.CapturePath)
		if err != nil {
			return nil, nil, err
		}
		captured := ""
		if verified.Bundle.Environment != nil {
			captured = *verified.Bundle.Environment
		}
		if captured != in.Environment {
			return nil, nil, fmt.Errorf(
				"%s is a capture of environment %q, and these readings are about %q",
				in.CapturePath, captured, in.Environment)
		}
		factSets = append(factSets, verified.Bundle.Facts)
	}

	selected := in.ProbeIDs
	if len(selected) == 0 {
		selected = catalogue.IDs()
	}
	requests := make([]probe.Request, 0, len(selected))
	for _, id := range selected {
		requests = append(requests, probe.Request{
			ProbeID:     id,
			Target:      in.Target,
			Environment: in.Environment,
			Inputs:      in.Inputs,
		})
	}

	through := wire{Network: probe.NewRealNetwork(in.Timeout), HTTP: probe.NewRealHTTPClient(in.Timeout)}
	if in.Through != nil {
		through = *in.Through
	}
	deps := probe.Deps{Network: through.Network, HTTP: through.HTTP, Now: time.Now}
	// The database, config and dependency probes read the named
	// environment through the Phase 30 capture machinery. Without an
	// environment there is no environment to read, and they say so.
	// Impedance has no source here on purpose: it is produced by the
	// worker (docs/PROBES.md), and field 17 of Phase 31.1 keeps it that
	// way.
	if in.Environment != "" {
		sources := &probe.Sources{
			Environment: in.Environment,
			Spec:        manifest.Environments[in.Environment],
			ManifestDir: filepath.Dir(resolved),
			Grants:      grants,
			Ledger:      ledger,
			Runner:      capture.ExecRunner{Timeout: in.Timeout},
			Reader:      capture.PostgresReader{Timeout: in.Timeout},
		}
		deps.Database = sources.Database()
		deps.Config = sources.Config()
		deps.Packages = sources.Packages()
	}

	runner := probe.NewRunner(probe.Options{
		Catalogue:    catalogue,
		Ledger:       ledger,
		AgentID:      in.AgentID,
		Overrides:    overridesFrom(manifest),
		Deps:         deps,
		Expectations: probe.NewExpectations(factSets...),
	})
	return runner.Run(ctx, requests), ledger, nil
}

// grantsFor pulls one environment's capability grants out of the manifest.
//
// An unnamed environment gets no grants at all, which means every probe
// returns refused. That is deliberate: running probes against an
// unspecified target with ambient authority is how a diagnostic tool
// becomes an incident.
func grantsFor(manifest *extract.Manifest, environment string) (capability.Grants, error) {
	if environment == "" {
		return capability.Grants{}, nil
	}
	spec, found := manifest.Environments[environment]
	if !found {
		return capability.Grants{}, fmt.Errorf(
			"culprit.yaml declares no environment %q; it has %s",
			environment, strings.Join(manifest.EnvironmentNames(), ", "))
	}
	return spec.ParsedGrants()
}

// overridesFrom translates culprit.yaml's `probes:` section into what the
// runner needs.
func overridesFrom(manifest *extract.Manifest) map[string]probe.Override {
	if len(manifest.Probes) == 0 {
		return nil
	}
	overrides := make(map[string]probe.Override, len(manifest.Probes))
	for id, spec := range manifest.Probes {
		overrides[id] = probe.Override{
			Enabled:      spec.Enabled,
			TimeoutMS:    spec.TimeoutMS,
			Environments: spec.Environments,
		}
	}
	return overrides
}

// parseInputs turns repeated --input key=value flags into probe inputs.
//
// Values that parse as integers become integers, because `port=443` must
// reach a probe as a number; everything else stays a string. A malformed
// pair is an error rather than a silently ignored flag — a probe that
// runs without the input you thought you gave it produces a confident
// answer to the wrong question.
// Repeating a key builds a list, which is how the probes that take one
// (`expect_fields`, `expect_columns`) are supplied:
//
//	--input expect_fields=sku --input expect_fields=quantity
//
// Without this those two probes were unsatisfiable from the command line
// and could only ever return inconclusive — found by the Phase 31 phase
// audit.
func parseInputs(pairs []string) (map[string]any, error) {
	inputs := map[string]any{}
	for _, pair := range pairs {
		key, value, found := strings.Cut(pair, "=")
		if !found || strings.TrimSpace(key) == "" {
			return nil, fmt.Errorf(
				"--input %q is not key=value", pair)
		}

		parsed := any(value)
		var number int
		if _, err := fmt.Sscanf(value, "%d", &number); err == nil &&
			fmt.Sprintf("%d", number) == value {
			parsed = number
		}

		existing, seen := inputs[key]
		if !seen {
			inputs[key] = parsed
			continue
		}
		// A second occurrence turns the value into a list, and a third
		// appends. Silently overwriting would run the probe against the
		// last value only, which is a confident answer to a question the
		// caller did not ask.
		if list, ok := existing.([]any); ok {
			inputs[key] = append(list, parsed)
			continue
		}
		inputs[key] = []any{existing, parsed}
	}
	return inputs, nil
}

func writeReadings(
	command *cobra.Command,
	format, outputPath string,
	readings []model.Reading,
	ledger *capability.Ledger,
) error {
	writer := command.OutOrStdout()
	if outputPath != "" {
		file, err := os.Create(outputPath)
		if err != nil {
			return fmt.Errorf("could not write to %s: %w", outputPath, err)
		}
		defer func() { _ = file.Close() }()
		writer = file
	}

	switch format {
	case "json":
		encoder := json.NewEncoder(writer)
		encoder.SetIndent("", "  ")
		return encoder.Encode(map[string]any{
			"readings": readings,
			"refused":  ledger.Refusals(),
		})
	case "text":
		return report.RenderReadings(writer, readings)
	default:
		return fmt.Errorf("unknown --format %q; expected text or json", format)
	}
}

func renderCatalogue(writer interface{ Write([]byte) (int, error) },
	format string, catalogue *probe.Catalogue,
) error {
	manifests := catalogue.Manifests()
	sort.Slice(manifests, func(i, j int) bool { return manifests[i].ID < manifests[j].ID })

	if format == "json" {
		encoder := json.NewEncoder(writer)
		encoder.SetIndent("", "  ")
		return encoder.Encode(manifests)
	}
	for _, manifest := range manifests {
		capabilities := "none"
		if len(manifest.Capabilities) > 0 {
			capabilities = strings.Join(manifest.Capabilities, ", ")
		}
		if _, err := fmt.Fprintf(writer, "%-34s %-13s %s\n    needs: %s\n",
			manifest.ID, manifest.Effect, manifest.Cost, capabilities); err != nil {
			return err
		}
	}
	return nil
}
