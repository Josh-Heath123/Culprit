package main

import (
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/spf13/cobra"

	"github.com/josh-heath123/culprit/cli/internal/agent"
	"github.com/josh-heath123/culprit/cli/internal/capability"
	"github.com/josh-heath123/culprit/cli/internal/check"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/isolate"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/probe"
	"github.com/josh-heath123/culprit/cli/internal/transport"
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
				Executor:   &agentExecutor{timeout: timeout, wire: realWire},
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

// agentExecutor runs a task's probes through the same runner and walk the
// commands use, under the grants the agent decided.
type agentExecutor struct {
	timeout time.Duration
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
		return agent.Result{Investigation: &investigation}, nil
	}
	return agent.Result{}, fmt.Errorf("task kind %q is not one this agent runs", task.Kind)
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
	reading := r.inner.Run(ctx, request)
	if r.err == nil {
		if err := r.record(reading); err != nil {
			r.err = err
			r.cancel()
		}
	}
	return reading
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
