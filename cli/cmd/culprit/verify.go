package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/josh-heath123/culprit/cli/internal/capability"
	"github.com/josh-heath123/culprit/cli/internal/capture"
	"github.com/josh-heath123/culprit/cli/internal/check"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/isolate"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/probe"
	"github.com/josh-heath123/culprit/cli/internal/report"
	"github.com/josh-heath123/culprit/cli/internal/verify"
)

// `culprit verify` — Phase 34 part 1: the loop, in the binary.
//
// `culprit diagnose` keeps three files for every investigation in a state
// directory: the investigation, the record of the request behind each of
// its readings, and a capture of the environment as it was found ("before").
// `culprit verify` reads them back, measures every reading again twice,
// captures the environment again, and judges.
//
// Nothing is changed and nothing is uploaded. Culprit verifies a change
// someone else applied; it never applies one.

// verificationError: the verification ran and its verdict is not
// `verified`. Not a failure of the command; its answer. Exit status 1.
type verificationError struct{ verdict model.VerificationVerdict }

func (e *verificationError) Error() string {
	return "the verdict is " + string(e.verdict)
}

// ---- the state directory ----------------------------------------------------------

// defaultStateDir is where investigations are kept for verification:
// $CULPRIT_STATE_DIR, else the user's state directory. Never the
// repository: a capture can carry a value config.read.values allowlists.
func defaultStateDir() string {
	if dir := os.Getenv("CULPRIT_STATE_DIR"); dir != "" {
		return dir
	}
	if runtime.GOOS == "windows" {
		if dir, err := os.UserCacheDir(); err == nil { // %LocalAppData%
			return filepath.Join(dir, "culprit")
		}
	}
	if dir := os.Getenv("XDG_STATE_HOME"); dir != "" {
		return filepath.Join(dir, "culprit")
	}
	if home, err := os.UserHomeDir(); err == nil {
		return filepath.Join(home, ".local", "state", "culprit")
	}
	return ""
}

var investigationIDPattern = regexp.MustCompile(`^inv-[0-9a-f]{16}$`)

func investigationDir(stateDir, id string) (string, error) {
	if stateDir == "" {
		return "", fmt.Errorf("no state directory: set --state-dir or CULPRIT_STATE_DIR")
	}
	if !investigationIDPattern.MatchString(id) {
		return "", fmt.Errorf("%q is not an investigation id (inv- and 16 hex characters)", id)
	}
	return filepath.Join(stateDir, "investigations", id), nil
}

// writePrivate writes a file only its owner can read, creating its
// directory the same way.
func writePrivate(path string, value any) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	encoded, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(encoded, '\n'), 0o600)
}

func readJSON(path string, into any) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	return json.Unmarshal(data, into)
}

// ---- what `culprit diagnose` keeps ---------------------------------------------------

// captureBefore records the environment as diagnosis finds it, under the
// environment's own grants — or, for an agent, under the grants it holds
// (grants non-nil). It returns the bundle, or why there is none:
// a capture that could see nothing at all is not a record of anything,
// and comparing two of them would call every change "nothing changed".
func captureBefore(ctx context.Context, manifest *extract.Manifest, manifestPath, environment string,
	grants *capability.Grants,
) (*model.CaptureBundle, string) {
	bundle, err := capture.Run(ctx, capture.Options{
		Manifest: manifest, ManifestDir: filepath.Dir(manifestPath), Environment: environment,
		Now: captureTime(), Version: Version,
		Runner: capture.ExecRunner{Timeout: 30 * time.Second}, Network: capture.RealNetwork{},
		Database: capture.PostgresReader{}, Grants: grants,
	})
	if err != nil {
		return nil, "the environment could not be captured: " + err.Error()
	}
	if len(bundle.Facts) == 0 {
		var refused []string
		for _, refusal := range bundle.Refused {
			refused = append(refused, refusal.Capability)
		}
		reason := "the capture of " + environment + " recorded nothing"
		if len(refused) > 0 {
			reason += " (refused: " + strings.Join(uniqueSorted(refused), ", ") + ")"
		}
		return nil, reason
	}
	return &bundle, ""
}

func uniqueSorted(values []string) []string {
	seen := map[string]bool{}
	var kept []string
	for _, value := range values {
		if !seen[value] {
			seen[value] = true
			kept = append(kept, value)
		}
	}
	for i := 1; i < len(kept); i++ {
		for j := i; j > 0 && kept[j] < kept[j-1]; j-- {
			kept[j], kept[j-1] = kept[j-1], kept[j]
		}
	}
	return kept
}

// keepForVerification writes the investigation, its record and the
// capture before into the state directory, and says in the rubric's
// `verified` reason what a verification can do with them. If they cannot
// be kept, the reason says that instead, and the error is returned for a
// warning: the diagnosis itself stands. how says, in the reason, how a
// verification is asked for: a command, or a task for the agent.
func keepForVerification(stateDir string, investigation *model.Investigation, requests map[string]isolate.Recorded,
	vantage string, before *model.CaptureBundle, absent, how string,
) error {
	record := verify.Record{
		Version: verify.RecordVersion, InvestigationID: investigation.ID,
		Environment: investigation.Environment, Vantage: vantage,
	}
	for _, item := range investigation.Readings {
		recorded := requests[item.ID]
		record.Requests = append(record.Requests, verify.Request{
			ReadingID: item.ID, ProbeID: recorded.Request.ProbeID, Target: recorded.Request.Target,
			Environment: recorded.Environment, Inputs: recorded.Request.Inputs,
		})
	}
	if before != nil {
		record.BeforeCapture = before.CaptureID
	} else {
		record.BeforeAbsent = absent
	}

	setVerified := func(reason string) {
		if investigation.Diagnosis != nil {
			investigation.Diagnosis.Confidence.Verified.Reason = reason
		}
	}
	if before != nil {
		setVerified("not yet verified: after a fix is applied, " + how + " measures every reading again " +
			"and compares the environment with the record of it taken at diagnosis")
	} else {
		setVerified("not yet verified, and a verification can be inconclusive at best: " +
			"there is no record of the environment before, because " + absent)
	}

	dir, err := investigationDir(stateDir, investigation.ID)
	if err == nil {
		err = record.Check(*investigation)
	}
	if err == nil && before != nil {
		var envelope capture.Envelope
		if envelope, err = capture.Seal(*before, nil); err == nil {
			err = writePrivate(filepath.Join(dir, "before.json"), envelope)
		}
	}
	if err == nil {
		err = writePrivate(filepath.Join(dir, "record.json"), record)
	}
	if err == nil {
		err = writePrivate(filepath.Join(dir, "investigation.json"), investigation)
	}
	if err != nil {
		// The cause goes to stderr, not into the investigation: it can name
		// local paths, and the investigation is printed and uploaded.
		setVerified("not verifiable: the investigation could not be kept in the state directory for verification")
		return err
	}
	return nil
}

// ---- `culprit verify` ----------------------------------------------------------------

func newVerifyCommand() *cobra.Command {
	var (
		manifestPath  string
		stateDir      string
		from          string
		changes       []string
		format        string
		outputPath    string
		agentID       string
		noPlugins     bool
		pluginTimeout time.Duration
		timeout       time.Duration
	)
	command := &cobra.Command{
		Use:   "verify <investigation-id>",
		Short: "Check whether a change fixed what an investigation found",
		Long: `After a fix is applied, measures again every reading the investigation took
— each twice, from the request the walk recorded, under the environment's
grants — and compares the environment with the record of it taken at
diagnosis.

Name what was applied with --change, repeatable:
  image:<component>             a new image for a component
  config:<component>/<key>      a config key changed for a component
  commit:<sha>                  a commit (explains nothing a capture records)
  action:<what was done>        anything else — a rule removed, a flag
                                cleared, a restart — in words (explains
                                nothing a capture records)

Verdicts: verified (what failed passes on both runs, what passed still
passes, and every change in the environment is explained by the change
named), not_resolved, regressed, changed_underneath, inconclusive.

Run it from where the diagnosis ran, and say so with --from as diagnose
did: probes see what their vantage sees, and a verification run anywhere
else is refused rather than judged. Nothing is changed and nothing is
uploaded.

Exit codes: 0 verified, 1 any other verdict, 2 the command could not run.`,
		Args: cobra.ExactArgs(1),
		RunE: func(command *cobra.Command, args []string) error {
			if format != "text" && format != "json" {
				return fmt.Errorf("unknown --format %q; expected text or json", format)
			}
			named, err := parseChanges(changes)
			if err != nil {
				return err
			}
			dir, err := investigationDir(stateDir, args[0])
			if err != nil {
				return err
			}
			var investigation model.Investigation
			if err := readJSON(filepath.Join(dir, "investigation.json"), &investigation); err != nil {
				return fmt.Errorf("investigation %s is not in %s (diagnose keeps it there): %w", args[0], stateDir, err)
			}
			if err := investigation.Validate(); err != nil {
				return fmt.Errorf("investigation %s does not validate: %w", args[0], err)
			}
			var record verify.Record
			if err := readJSON(filepath.Join(dir, "record.json"), &record); err != nil {
				return fmt.Errorf("the record of %s cannot be read: %w", args[0], err)
			}
			if err := record.Check(investigation); err != nil {
				return err
			}
			// The vantage is the diagnosis's: an edge, a token or a process
			// environment measured from anywhere else is a different
			// measurement, and could pass where nothing was fixed.
			if from != record.Vantage {
				return fmt.Errorf("%s was diagnosed from %s; verify it from there (--from %s), not from %s",
					investigation.ID, vantageWords(record.Vantage), record.Vantage, vantageWords(from))
			}

			resolved, err := resolveManifestPath(manifestPath)
			if err != nil {
				return err
			}
			manifest, err := extract.LoadManifest(resolved)
			if err != nil {
				return err
			}
			for _, request := range record.Requests {
				if _, declared := manifest.Environments[request.Environment]; !declared {
					return fmt.Errorf("environment %q is not declared under environments: in %s", request.Environment, resolved)
				}
			}

			var before, after *model.CaptureBundle
			if record.BeforeCapture != "" {
				envelope, err := capture.ReadEnvelope(filepath.Join(dir, "before.json"))
				if err != nil {
					return fmt.Errorf("the capture before cannot be read: %w", err)
				}
				before = &envelope.Bundle
				taken, absent := captureBefore(command.Context(), manifest, resolved, record.Environment, nil)
				if taken == nil {
					return fmt.Errorf("the environment cannot be captured again to compare with: %s", absent)
				}
				after = taken
			}

			intent, err := check.Run(command.Context(), check.Options{
				ManifestPath: resolved, Now: captureTime(), PluginTimeout: pluginTimeout,
				SkipPlugins: noPlugins, Version: Version,
			})
			if err != nil {
				return err
			}
			runner := &verifyRunner{
				manifest: manifest, manifestPath: resolved, agentID: agentID, timeout: timeout,
				catalogue: probe.BuiltIn(), facts: intent.Bundle.Facts, runners: map[string]*probe.Runner{},
			}
			verification, err := verify.Run(command.Context(), verify.Options{
				ID: newVerificationID(), Investigation: investigation, Record: record, Changes: named,
				Before: before, After: after, Runner: runner,
			})
			if err != nil {
				return err
			}
			if runner.err != nil {
				return runner.err
			}
			if err := writePrivate(filepath.Join(dir, "verifications", verification.ID+".json"), verification); err != nil {
				fmt.Fprintf(command.ErrOrStderr(), "culprit: the verification was not kept: %v\n", err)
			}
			if err := writeVerification(command.OutOrStdout(), format, outputPath, verification); err != nil {
				return err
			}
			if verification.Verdict != model.VerificationVerified {
				return &verificationError{verdict: verification.Verdict}
			}
			return nil
		},
	}
	command.SilenceUsage = true
	command.Flags().StringVarP(&manifestPath, "file", "f", "", "path to culprit.yaml (default: search upward from the working directory)")
	command.Flags().StringVar(&stateDir, "state-dir", defaultStateDir(), "where `culprit diagnose` kept the investigation ($CULPRIT_STATE_DIR)")
	command.Flags().StringVar(&from, "from", "", "the component this binary runs inside — the same as the diagnosis's --from")
	command.Flags().StringArrayVar(&changes, "change", nil, "what was applied: image:<component>, config:<component>/<key>, commit:<sha> or action:<what was done> (repeatable)")
	command.Flags().StringVar(&format, "format", "text", "text|json")
	command.Flags().StringVarP(&outputPath, "output", "o", "", "write to this file instead of stdout")
	command.Flags().StringVar(&agentID, "agent-id", "culprit-cli", "identifies who took these readings")
	command.Flags().BoolVar(&noPlugins, "no-plugins", false, "extract INTENT with the built-in artefact readers only")
	command.Flags().DurationVar(&pluginTimeout, "plugin-timeout", 90*time.Second, "how long any one extractor plugin may run")
	command.Flags().DurationVar(&timeout, "timeout", 10*time.Second, "per-operation network timeout")
	return command
}

func vantageWords(component string) string {
	if component == "" {
		return "outside every component"
	}
	return "inside " + component
}

// parseChanges reads --change values into changes, with subjects built,
// never formatted by hand.
func parseChanges(values []string) ([]model.Change, error) {
	var changes []model.Change
	for _, value := range values {
		kind, rest, found := strings.Cut(value, ":")
		if !found {
			return nil, fmt.Errorf("--change %q: want image:<component>, config:<component>/<key>, commit:<sha> or action:<what was done>", value)
		}
		var change model.Change
		switch kind {
		case "commit":
			change = model.Change{Kind: model.ChangeCommit, Ref: strings.ToLower(strings.TrimSpace(rest))}
		case "action":
			change = model.Change{Kind: model.ChangeAction, Description: strings.TrimSpace(rest)}
		case "image":
			subject, err := model.BuildSubject(model.KindImage, model.Parts{"component": rest})
			if err != nil {
				return nil, fmt.Errorf("--change %q: %w", value, err)
			}
			change = model.Change{Kind: model.ChangeImage, Subject: subject}
		case "config":
			component, key, ok := strings.Cut(rest, "/")
			if !ok {
				return nil, fmt.Errorf("--change %q: want config:<component>/<key>", value)
			}
			subject, err := model.BuildSubject(model.KindConfig, model.Parts{"component": component, "key": key})
			if err != nil {
				return nil, fmt.Errorf("--change %q: %w", value, err)
			}
			change = model.Change{Kind: model.ChangeConfig, Subject: subject}
		default:
			return nil, fmt.Errorf("--change %q: %q is not image, config, commit or action", value, kind)
		}
		if err := change.Validate(); err != nil {
			return nil, fmt.Errorf("--change %q: %w", value, err)
		}
		changes = append(changes, change)
	}
	return changes, nil
}

// verifyRunner adapts internal/probe to verify.Runner: one probe runner
// per environment, under that environment's grants from culprit.yaml.
// Every reading still goes through probe.Runner — the ledger, the
// timeout, the redaction.
type verifyRunner struct {
	manifest     *extract.Manifest
	manifestPath string
	agentID      string
	timeout      time.Duration
	catalogue    *probe.Catalogue
	facts        []model.Fact
	runners      map[string]*probe.Runner
	through      *wire
	err          error
}

func (r *verifyRunner) Run(ctx context.Context, request verify.Request) model.Reading {
	runner, ok := r.runners[request.Environment]
	if !ok {
		grants, err := grantsFor(r.manifest, request.Environment)
		if err != nil && r.err == nil {
			r.err = err
		}
		through := realWire(r.timeout)
		if r.through != nil {
			through = *r.through
		}
		runner = probeRunnerUnder(r.manifest, r.manifestPath, request.Environment, r.agentID, r.timeout,
			r.catalogue, r.facts, grants, through)
		r.runners[request.Environment] = runner
	}
	return runner.Run(ctx, []probe.Request{{
		ProbeID: request.ProbeID, Target: request.Target, Environment: request.Environment, Inputs: request.Inputs,
	}})[0]
}

func writeVerification(stdout io.Writer, format, outputPath string, verification model.Verification) error {
	writer, closer, err := outputWriter(stdout, outputPath)
	if err != nil {
		return err
	}
	defer func() { _ = closer() }()
	switch format {
	case "json":
		encoder := json.NewEncoder(writer)
		encoder.SetIndent("", "  ")
		return encoder.Encode(verification)
	case "text":
		return report.RenderVerification(writer, verification)
	}
	return fmt.Errorf("unknown --format %q; expected text or json", format)
}

func newVerificationID() string {
	return "ver-" + strings.TrimPrefix(newInvestigationID(), "inv-")
}
