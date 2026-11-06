package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/signal"
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
walk from a symptom — is read from <tasks>/inbox, run, written to the audit
log, and answered in <tasks>/outbox.

What the agent may do is set by its configuration file alone (--config),
which lists grants explicitly per environment and is read again before every
task: remove a grant and the next task runs without it. A task may carry an
allowance that narrows those grants; nothing can widen them. A task that needs
a grant the agent does not hold is refused before anything is dialled, and
the refusal is a reading and an audit entry.

The audit log is append-only and hash-chained; ` + "`culprit agent verify`" + ` checks it.

Nothing here writes to the system under test, and nothing is uploaded.`,
		Args: cobra.NoArgs,
		RunE: func(command *cobra.Command, _ []string) error {
			if configPath == "" || tasksDir == "" || auditPath == "" {
				return fmt.Errorf("--config, --tasks and --audit are all required")
			}
			// Refuse to start on a configuration that does not load: an
			// operator should learn that now, not from the first task.
			if _, err := agent.LoadConfig(configPath); err != nil {
				return err
			}
			source := agent.DirSource{Dir: tasksDir}
			if err := source.Prepare(); err != nil {
				return err
			}
			audit, err := agent.OpenAudit(auditPath)
			if err != nil {
				return err
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
	command.Flags().StringVar(&tasksDir, "tasks", "", "the task directory: inbox/, outbox/ and done/ beneath it")
	command.Flags().StringVar(&auditPath, "audit", "", "the audit log, appended to and never rewritten")
	command.Flags().BoolVar(&once, "once", false, "handle the tasks waiting now, then exit")
	command.Flags().DurationVar(&poll, "poll", 2*time.Second, "how often to look for new tasks")
	command.Flags().DurationVar(&timeout, "timeout", 10*time.Second, "per-operation network timeout")
	command.AddCommand(newAgentVerifyCommand())
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
