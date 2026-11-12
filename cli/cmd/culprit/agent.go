package main

import (
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/spf13/cobra"

	"github.com/josh-heath123/culprit/cli/internal/agent"
	"github.com/josh-heath123/culprit/cli/internal/capability"
	"github.com/josh-heath123/culprit/cli/internal/capture"
	"github.com/josh-heath123/culprit/cli/internal/check"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/isolate"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/probe"
	"github.com/josh-heath123/culprit/cli/internal/transport"
	"github.com/josh-heath123/culprit/cli/internal/verify"
)

// `culprit agent` — Phase 33, part 1: the agent, standing alone.
//
// It takes tasks from a local directory (part 2 adds the transport to the
// control plane behind the same interface), runs each under the grants its
// own configuration gives — never those in culprit.yaml — and writes every
// task and every probe to a hash-chained audit log before it answers.

func newAgentCommand() *cobra.Command {
	var (
		configPath string
		tasksDir   string
		auditPath  string
		stateDir   string
		once       bool
		poll       time.Duration
		timeout    time.Duration
	)
	command := &cobra.Command{
		Use:   "agent",
		Short: "Run probes and walks as tasks, under this agent's own grants",
		Long: `Runs as a long-lived process. Each task — a named probe on a target, or a
walk from a symptom — is claimed from the control plane the configuration
names (control_plane.url), or read from <tasks>/inbox with --tasks; run;
written to the audit log; and answered.

Pair once first: ` + "`culprit agent init`" + ` writes the agent's key, and
` + "`culprit agent pair --code <code>`" + ` registers it with a code an admin made.
Every request after pairing is signed with that key. The agent only ever
connects out, to the one address its configuration names.

What the agent may do is set by its configuration file alone (--config),
which lists grants explicitly per environment and is read again before every
task: remove a grant and the next task runs without it. A task may carry an
allowance that narrows those grants; nothing can widen them. A task that needs
a grant the agent does not hold is refused before anything is dialled, and
the refusal is a reading and an audit entry.

The audit log is append-only and hash-chained; ` + "`culprit agent verify`" + ` checks it.

For every walk it runs, the agent keeps what a verification needs — the
request behind each reading, and a capture of the environment as the walk
found it, taken under the agent's own grants — in its state directory
(--state-dir; beside the audit log by default). A verify task measures an
investigation it diagnosed again against that record. Asked to verify one
it did not diagnose, it answers inconclusive: it holds no record of before.

Nothing here writes to the system under test. Readings, investigations and
the audit log go to the control plane, and only to it.`,
		Args: cobra.NoArgs,
		RunE: func(command *cobra.Command, _ []string) error {
			if configPath == "" || auditPath == "" {
				return fmt.Errorf("--config and --audit are required")
			}
			// Refuse to start on a configuration that does not load: an
			// operator should learn that now, not from the first task.
			config, err := agent.LoadConfig(configPath)
			if err != nil {
				return err
			}
			reportPlainHTTP(command.ErrOrStderr(), config)
			audit, err := agent.OpenAudit(auditPath)
			if err != nil {
				return err
			}
			var source agent.Source
			switch {
			case tasksDir != "" && config.ControlPlane != "":
				return fmt.Errorf("--tasks and a control_plane in %s are two sources; use one", configPath)
			case tasksDir != "":
				local := agent.DirSource{Dir: tasksDir}
				if err := local.Prepare(); err != nil {
					return err
				}
				source = local
			case config.ControlPlane != "":
				client, err := controlPlaneClient(config, timeout)
				if err != nil {
					return err
				}
				source = &transport.Source{Client: client, Audit: audit}
			default:
				return fmt.Errorf("no task source: give --tasks, or name control_plane.url in %s", configPath)
			}
			stderr := command.ErrOrStderr()
			runner := &agent.Agent{
				ConfigPath: configPath,
				Source:     source,
				Audit:      audit,
				Executor:   &agentExecutor{timeout: timeout, wire: realWire, stateDir: agentStateDir(stateDir, auditPath)},
				Poll:       poll,
				Logf:       func(format string, args ...any) { fmt.Fprintf(stderr, format+"\n", args...) },
			}
			ctx, stop := signal.NotifyContext(command.Context(), os.Interrupt, syscall.SIGTERM)
			defer stop()
			if once {
				handled, err := runner.Drain(ctx)
				fmt.Fprintf(stderr, "%d task(s) handled\n", handled)
				return err
			}
			return runner.Run(ctx)
		},
	}
	command.SilenceUsage = true
	command.Flags().StringVar(&configPath, "config", "", "the agent's configuration file (its grants)")
	command.Flags().StringVar(&tasksDir, "tasks", "", "a local task directory (inbox/, outbox/, done/) instead of a control plane")
	command.Flags().StringVar(&auditPath, "audit", "", "the audit log, appended to and never rewritten")
	command.Flags().StringVar(&stateDir, "state-dir", "", "where the agent keeps what verifying its walks needs (default: state/ beside --audit)")
	command.Flags().BoolVar(&once, "once", false, "handle the tasks waiting now, then exit")
	command.Flags().DurationVar(&poll, "poll", 2*time.Second, "how often to look for new tasks")
	command.Flags().DurationVar(&timeout, "timeout", 10*time.Second, "per-operation network timeout")
	command.AddCommand(newAgentVerifyCommand(), newAgentInitCommand(), newAgentPairCommand())
	return command
}

func newAgentVerifyCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "verify <audit-log>",
		Short: "Check an audit log's hash chain",
		Long: `Reads the whole log and checks every entry's hash and its link to the entry
before it. An edited, removed or reordered entry is named by its line.
Exit 0 intact, 1 broken, 2 unreadable.`,
		Args:         cobra.ExactArgs(1),
		SilenceUsage: true,
		RunE: func(command *cobra.Command, args []string) error {
			count, err := agent.VerifyAudit(args[0])
			if errors.Is(err, agent.ErrAuditUnreadable) {
				return err // exit 2: nothing was checked
			}
			if err != nil {
				// Exit 1, the way a finding exits: the command ran, and what
				// it found is that the chain is broken.
				fmt.Fprintln(command.ErrOrStderr(), "culprit: the audit log is broken:", err)
				return &findingsError{}
			}
			fmt.Fprintf(command.OutOrStdout(), "%s: %d entries, chain intact\n", args[0], count)
			return nil
		},
	}
}

// agentStateDir is --state-dir, else state/ beside the audit log: the one
// place an agent is already sure to be able to write, and keep (the
// recipes' audit volume).
func agentStateDir(flag, auditPath string) string {
	if flag != "" {
		return flag
	}
	return filepath.Join(filepath.Dir(auditPath), "state")
}

// agentExecutor runs a task's probes through the same runner and walk the
// commands use, under the grants the agent decided.
type agentExecutor struct {
	// stateDir is where each walk's record is kept for verify tasks; ""
	// keeps nothing, and every verification is then inconclusive.
	stateDir string
	timeout  time.Duration
	// wire builds the network a probe reaches through; a test passes one
	// that counts dials.
	wire func(time.Duration) wire
}

func (e *agentExecutor) Execute(ctx context.Context, task agent.Task, config agent.Config,
	grants capability.Grants, record func(model.Reading) error,
) (agent.Result, error) {
	// The model is read again too, beside the configuration.
	manifest, err := extract.LoadManifest(config.Manifest)
	if err != nil {
		return agent.Result{}, fmt.Errorf("the manifest the configuration names does not load: %w", err)
	}
	spec, declared := manifest.Environments[task.Environment]
	if !declared {
		return agent.Result{}, fmt.Errorf("environment %q is not declared in %s", task.Environment, config.Manifest)
	}
	// INTENT from the built-in artefact readers only: an extractor plugin
	// imports the target project's code, which an agent on a production
	// host has no business running (docs/LIMITS.md).
	intent, err := check.Run(ctx, check.Options{
		ManifestPath: config.Manifest, Now: captureTime(), SkipPlugins: true, Version: Version,
	})
	if err != nil {
		return agent.Result{}, fmt.Errorf("INTENT could not be read from %s: %w", config.Manifest, err)
	}
	facts := intent.Bundle.Facts
	catalogue := probe.BuiltIn()
	through := e.wire(e.timeout)

	switch task.Kind {
	case agent.TaskProbe:
		runner := probeRunnerUnder(manifest, config.Manifest, task.Environment, config.AgentID, e.timeout,
			catalogue, facts, grants, through)
		readings := runner.Run(ctx, []probe.Request{{
			ProbeID: task.Probe.ProbeID, Target: task.Probe.Target,
			Environment: task.Environment, Inputs: task.Probe.Inputs,
		}})
		for _, reading := range readings {
			if err := record(reading); err != nil {
				return agent.Result{}, err
			}
		}
		result := agent.Result{Readings: readings}
		if len(readings) == 1 && readings[0].Verdict == model.VerdictRefused {
			result.Outcome, result.Reason = agent.OutcomeRefused, readings[0].Reason
		}
		return result, nil

	case agent.TaskDiagnose:
		symptom, entry, err := parseSymptom(task.Diagnose.Symptom, manifest, spec)
		if err != nil {
			return agent.Result{}, err
		}
		from := task.Diagnose.From
		if from != "" {
			if _, ok := componentNamed(manifest, from); !ok {
				return agent.Result{}, fmt.Errorf("from %q is not a component in %s", from, config.Manifest)
			}
		}
		walkCtx, cancel := context.WithCancel(ctx)
		defer cancel()
		recorded := &recordingRunner{
			inner: walkRunnerUnder(manifest, config.Manifest, task.Environment, config.AgentID, e.timeout,
				catalogue, facts, grants, through),
			record: record, cancel: cancel,
		}
		options := isolate.Options{Environment: task.Environment}
		options.MaxProbes, options.MaxWallClock = manifest.IsolationBudget(task.Environment)
		components, connections := walkModel(manifest)
		walk := isolate.New(components, connections, facts, catalogue.Manifests(), recorded,
			newPlacement(manifest, spec, from, facts), options)
		opened := captureTime()
		// The record of before, ahead of the walk, as `culprit diagnose`
		// takes it — under the grants this task holds, not culprit.yaml's.
		before, absent := captureBefore(ctx, manifest, config.Manifest, task.Environment, &grants)
		investigation, err := walk.Diagnose(walkCtx, symptom, entry)
		if recorded.err != nil {
			return agent.Result{}, recorded.err
		}
		if err != nil {
			return agent.Result{}, err
		}
		closed := time.Now().UTC()
		investigation.ID, investigation.OpenedAt, investigation.ClosedAt = newInvestigationID(), opened, &closed
		if err := investigation.Validate(); err != nil {
			return agent.Result{}, fmt.Errorf("the walk produced an investigation the model rejects: %w", err)
		}
		how := "a verify task for " + investigation.ID + ", sent to agent " + config.AgentID + ","
		if err := keepForVerification(e.stateDir, &investigation, walk.Requests(), from, before, absent, how); err != nil {
			// The diagnosis stands; its `verified` reason says it cannot be
			// verified, and why goes to the agent's log, never the record.
			fmt.Fprintf(os.Stderr, "culprit agent: %s was not kept for verification: %v\n", investigation.ID, err)
		}
		if err := investigation.Validate(); err != nil {
			return agent.Result{}, fmt.Errorf("the investigation does not validate once kept: %w", err)
		}
		return agent.Result{Investigation: &investigation}, nil

	case agent.TaskVerify:
		return e.verify(ctx, task, config, manifest, catalogue, facts, grants, through, record)
	}
	return agent.Result{}, fmt.Errorf("task kind %q is not one this agent runs", task.Kind)
}

// verify runs a verify task: the record this agent kept when it diagnosed
// the investigation, measured again under the grants this task holds, and
// judged by verify.Run — `culprit verify`, as a task.
func (e *agentExecutor) verify(ctx context.Context, task agent.Task, config agent.Config,
	manifest *extract.Manifest, catalogue *probe.Catalogue, facts []model.Fact,
	grants capability.Grants, through wire, record func(model.Reading) error,
) (agent.Result, error) {
	id := task.Verify.InvestigationID
	noRecord := func(why string) (agent.Result, error) {
		return agent.Result{
			Verdict: model.VerificationInconclusive,
			Reason: "inconclusive: this agent holds no record of before for " + id + " — " + why +
				". Only the agent that diagnosed an investigation can verify it; nothing was measured",
		}, nil
	}
	dir, err := investigationDir(e.stateDir, id)
	if err != nil {
		return noRecord("it keeps no state directory")
	}
	var investigation model.Investigation
	if err := readJSON(filepath.Join(dir, "investigation.json"), &investigation); err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return noRecord("it did not diagnose it")
		}
		return agent.Result{}, fmt.Errorf("the investigation this agent kept for %s cannot be read: %w", id, err)
	}
	if err := investigation.Validate(); err != nil {
		return agent.Result{}, fmt.Errorf("the investigation this agent kept for %s does not validate: %w", id, err)
	}
	if investigation.Environment != task.Environment {
		return agent.Result{}, fmt.Errorf("%s is an investigation of %s; the task is for %s",
			id, investigation.Environment, task.Environment)
	}
	var kept verify.Record
	if err := readJSON(filepath.Join(dir, "record.json"), &kept); err != nil {
		return agent.Result{}, fmt.Errorf("the record of %s cannot be read: %w", id, err)
	}
	if err := kept.Check(investigation); err != nil {
		return agent.Result{}, err
	}

	var before, after *model.CaptureBundle
	if kept.BeforeCapture != "" {
		envelope, err := capture.ReadEnvelope(filepath.Join(dir, "before.json"))
		if err != nil {
			return agent.Result{}, fmt.Errorf("the capture before cannot be read: %w", err)
		}
		before = &envelope.Bundle
		taken, absent := captureBefore(ctx, manifest, config.Manifest, kept.Environment, &grants)
		if taken == nil {
			return agent.Result{}, fmt.Errorf("the environment cannot be captured again to compare with: %s", absent)
		}
		after = taken
	}
	runner := &agentVerifyRunner{
		environment: task.Environment, grants: grants, record: record, runners: map[string]*probe.Runner{},
		build: func(environment string, under capability.Grants) *probe.Runner {
			return probeRunnerUnder(manifest, config.Manifest, environment, config.AgentID, e.timeout,
				catalogue, facts, under, through)
		},
	}
	verification, err := verify.Run(ctx, verify.Options{
		ID: newVerificationID(), Investigation: investigation, Record: kept, Changes: task.Verify.Changes,
		Before: before, After: after, Runner: runner,
	})
	if runner.err != nil {
		return agent.Result{}, runner.err
	}
	if err != nil {
		return agent.Result{}, err
	}
	if err := writePrivate(filepath.Join(dir, "verifications", verification.ID+".json"), verification); err != nil {
		fmt.Fprintf(os.Stderr, "culprit agent: verification %s was not kept locally: %v\n", verification.ID, err)
	}
	return agent.Result{
		Verification: &verification, Verdict: verification.Verdict,
		Reason: string(verification.Verdict) + ": " + verification.Reason,
	}, nil
}

// agentVerifyRunner runs a verify task's re-runs: in the task's
// environment, under the grants the task holds; in any other (a
// counterfactual's reference environment), under none — an allowance is
// per environment, and nothing widens one — so such a re-run is refused
// and the verdict cannot be verified. Every reading is recorded in the
// audit log before it is used.
type agentVerifyRunner struct {
	environment string
	grants      capability.Grants
	record      func(model.Reading) error
	build       func(environment string, under capability.Grants) *probe.Runner
	runners     map[string]*probe.Runner
	err         error
}

func (r *agentVerifyRunner) Run(ctx context.Context, request verify.Request) model.Reading {
	return r.RunSet(ctx, request)[0]
}

// RunSet is every reading one run gave, each recorded before it is used.
func (r *agentVerifyRunner) RunSet(ctx context.Context, request verify.Request) []model.Reading {
	runner, ok := r.runners[request.Environment]
	if !ok {
		under := capability.Grants{}
		if request.Environment == r.environment {
			under = r.grants
		}
		runner = r.build(request.Environment, under)
		r.runners[request.Environment] = runner
	}
	readings := runner.RunOne(ctx, probe.Request{
		ProbeID: request.ProbeID, Target: request.Target, Environment: request.Environment, Inputs: request.Inputs,
	})
	for _, reading := range readings {
		if r.err == nil {
			if err := r.record(reading); err != nil {
				r.err = err
			}
		}
	}
	return readings
}

// recordingRunner is the walk's runner with the audit in front of it:
// each reading is recorded before the walk sees it. If the record cannot
// be written, the walk is stopped and the task fails with that error.
type recordingRunner struct {
	inner  walkRunner
	record func(model.Reading) error
	cancel context.CancelFunc
	err    error
}

func (r *recordingRunner) Run(ctx context.Context, request isolate.Request) model.Reading {
	return r.RunSet(ctx, request)[0]
}

// RunSet is every reading one run gave, each recorded before the walk sees
// it.
func (r *recordingRunner) RunSet(ctx context.Context, request isolate.Request) []model.Reading {
	readings := r.inner.RunSet(ctx, request)
	for _, reading := range readings {
		if r.err == nil {
			if err := r.record(reading); err != nil {
				r.err = err
				r.cancel()
			}
		}
	}
	return readings
}

// controlPlaneClient builds the transport from the configuration: its
// address, the agent's id and its key.
func controlPlaneClient(config agent.Config, timeout time.Duration) (*transport.Client, error) {
	data, err := os.ReadFile(config.Key)
	if err != nil {
		return nil, fmt.Errorf("the agent's key %s cannot be read (run `culprit agent init` first)", config.Key)
	}
	key, err := transport.ParseKey(data)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", config.Key, err)
	}
	return transport.New(config.ControlPlane, config.AgentID, key, timeout)
}

func newAgentInitCommand() *cobra.Command {
	var configPath string
	command := &cobra.Command{
		Use:   "init",
		Short: "Write this agent's signing key",
		Long: `Generates the agent's Ed25519 key and writes it to the file the
configuration's key: names, readable by its owner only (0600). It never
overwrites a key: an agent's key is its identity, and replacing it is
pairing a new agent. The private key never leaves that file; pairing sends
only its public half.`,
		Args:         cobra.NoArgs,
		SilenceUsage: true,
		RunE: func(command *cobra.Command, _ []string) error {
			config, err := agent.LoadConfig(configPath)
			if err != nil {
				return err
			}
			if config.Key == "" {
				return fmt.Errorf("%s names no key: add key: ./agent.key", configPath)
			}
			key, encoded, err := transport.GenerateKey()
			if err != nil {
				return err
			}
			file, err := os.OpenFile(config.Key, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
			if errors.Is(err, os.ErrExist) {
				return fmt.Errorf("%s already exists; an agent's key is never overwritten", config.Key)
			}
			if err != nil {
				return fmt.Errorf("%s cannot be created", config.Key)
			}
			if _, err := file.Write(encoded); err != nil {
				file.Close()
				return fmt.Errorf("%s could not be written", config.Key)
			}
			if err := file.Close(); err != nil {
				return err
			}
			public := base64.StdEncoding.EncodeToString(key.Public().(ed25519.PublicKey))
			fmt.Fprintf(command.OutOrStdout(), "wrote %s\npublic key: %s\n", config.Key, public)
			return nil
		},
	}
	command.Flags().StringVar(&configPath, "config", "", "the agent's configuration file")
	_ = command.MarkFlagRequired("config")
	return command
}

// reportPlainHTTP says, at every start of a command that reaches the
// control plane, that the operator has allowed plain http (Phase 33 part 3).
// The parser has already refused plain http to anything but loopback
// without it; this makes the consent visible in every log that follows.
func reportPlainHTTP(w io.Writer, config agent.Config) {
	if !config.AllowPlainHTTP {
		return
	}
	fmt.Fprintf(w, "warning: control_plane.allow_plain_http is set in %s: tasks, readings "+
		"and investigations to %s may travel unencrypted\n", config.Path, config.ControlPlane)
}

func newAgentPairCommand() *cobra.Command {
	var configPath, code string
	var timeout time.Duration
	command := &cobra.Command{
		Use:   "pair",
		Short: "Register this agent with the control plane, once",
		Long: `Spends a pairing code an admin made (it works once and expires after 15
minutes) to register this agent: its id, the public half of its key, and the
grants its configuration gives in each environment — what an operator may
later allow it, and never more. A newly paired agent's allowance is empty.`,
		Args:         cobra.NoArgs,
		SilenceUsage: true,
		RunE: func(command *cobra.Command, _ []string) error {
			config, err := agent.LoadConfig(configPath)
			if err != nil {
				return err
			}
			if config.ControlPlane == "" {
				return fmt.Errorf("%s names no control_plane to pair with", configPath)
			}
			reportPlainHTTP(command.ErrOrStderr(), config)
			client, err := controlPlaneClient(config, timeout)
			if err != nil {
				return err
			}
			data, err := os.ReadFile(config.Key)
			if err != nil {
				return fmt.Errorf("%s cannot be read", config.Key)
			}
			key, err := transport.ParseKey(data)
			if err != nil {
				return err
			}
			if code == "-" {
				// From stdin, so the code is in neither the shell's history
				// nor the process list.
				read, err := io.ReadAll(io.LimitReader(command.InOrStdin(), 256))
				if err != nil {
					return fmt.Errorf("the pairing code could not be read from stdin")
				}
				code = strings.TrimSpace(string(read))
			}
			registration := transport.NewRegistration(code, config.AgentID, key, config.GrantNames())
			if err := client.Register(command.Context(), registration); err != nil {
				return err
			}
			fmt.Fprintf(command.OutOrStdout(), "paired as %s with %s\n", config.AgentID, config.ControlPlane)
			return nil
		},
	}
	command.Flags().StringVar(&configPath, "config", "", "the agent's configuration file")
	command.Flags().StringVar(&code, "code", "", "the pairing code an admin made, or - to read it from stdin")
	command.Flags().DurationVar(&timeout, "timeout", 10*time.Second, "network timeout")
	_ = command.MarkFlagRequired("config")
	_ = command.MarkFlagRequired("code")
	return command
}
