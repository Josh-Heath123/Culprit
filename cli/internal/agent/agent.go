package agent

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/capability"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Executor runs one task under grants the agent has already decided. It
// must call record for every reading it takes, before using the reading:
// that is how every executed probe gets its audit entry. cmd/culprit
// supplies the real one, which is where probes and the walk live.
type Executor interface {
	Execute(ctx context.Context, task Task, config Config, grants capability.Grants,
		record func(model.Reading) error) (Result, error)
}

// Agent is the loop: take a task, decide what it may do, run it, record
// it, answer it.
type Agent struct {
	ConfigPath string
	Source     Source
	Audit      *AuditLog
	Executor   Executor
	// Poll is how long Run waits when the source has nothing.
	Poll time.Duration
	Now  func() time.Time
	// Logf reports what happened to each task, one line each. Never a
	// value: task ids, outcomes and reasons only.
	Logf func(format string, args ...any)
}

func (a *Agent) now() time.Time {
	if a.Now != nil {
		return a.Now().UTC()
	}
	return time.Now().UTC()
}

func (a *Agent) logf(format string, args ...any) {
	if a.Logf != nil {
		a.Logf(format, args...)
	}
}

// Run takes tasks until ctx ends.
func (a *Agent) Run(ctx context.Context) error {
	poll := a.Poll
	if poll <= 0 {
		poll = 2 * time.Second
	}
	for {
		handled, err := a.Drain(ctx)
		if err != nil {
			return err
		}
		if handled > 0 {
			continue
		}
		select {
		case <-ctx.Done():
			return nil
		case <-time.After(poll):
		}
	}
}

// Drain handles every task waiting now, then returns how many. An error
// is the agent unable to keep its own record — an audit entry or a
// result that could not be written — and stops it: an agent that cannot
// audit must not act.
func (a *Agent) Drain(ctx context.Context) (int, error) {
	handled := 0
	for ctx.Err() == nil {
		incoming, err := a.Source.Next(ctx)
		if err != nil {
			return handled, err
		}
		if incoming == nil {
			return handled, nil
		}
		if err := a.Handle(ctx, incoming); err != nil {
			return handled, err
		}
		handled++
	}
	return handled, nil
}

// Handle runs one task to its recorded result.
func (a *Agent) Handle(ctx context.Context, incoming *Incoming) error {
	started := a.now()
	task := incoming.Task
	result := Result{TaskID: task.ID, Environment: task.Environment, Kind: task.Kind, StartedAt: started, GrantsHeld: []string{}}

	finish := func(outcome, reason string) error {
		result.Outcome, result.Reason = outcome, reason
		result.FinishedAt = a.now()
		if _, err := a.Audit.Append(Entry{
			Time: result.FinishedAt, AgentID: result.AgentID, TaskID: task.ID, Kind: EntryTask,
			Environment: task.Environment, Grants: result.GrantsHeld, Outcome: outcome, Reason: reason,
		}); err != nil {
			return err
		}
		if err := a.Source.Complete(ctx, incoming, result); err != nil {
			return err
		}
		a.logf("task %s: %s%s", task.ID, outcome, suffix(reason))
		return nil
	}

	// The configuration, read now: a grant removed since the last task
	// is gone for this one, with no restart.
	config, err := LoadConfig(a.ConfigPath)
	if err != nil {
		return finish(OutcomeError, "the agent's configuration does not load, so nothing was run: "+err.Error())
	}
	result.AgentID = config.AgentID

	if incoming.Unreadable != "" {
		return finish(OutcomeError, incoming.Unreadable)
	}
	if err := task.Validate(); err != nil {
		return finish(OutcomeError, err.Error())
	}
	held, configured := config.Environments[task.Environment]
	if !configured {
		return finish(OutcomeRefused, fmt.Sprintf(
			"this agent is not configured for environment %q, so it holds no grant there", task.Environment))
	}
	grants, ignored := held.Narrow(task.Allowance)
	result.GrantsHeld = grants.Names()
	result.AllowanceIgnored = ignored

	record := func(reading model.Reading) error {
		_, err := a.Audit.Append(Entry{
			Time: a.now(), AgentID: config.AgentID, TaskID: task.ID, Kind: EntryProbe,
			Environment: task.Environment, ProbeID: reading.ProbeID, Target: reading.Target,
			Grants: reading.GrantsUsed, Verdict: string(reading.Verdict), Reason: reading.Reason,
		})
		if err != nil {
			return &AuditFailure{Err: err}
		}
		return nil
	}
	executed, err := a.Executor.Execute(ctx, task, config, grants, record)
	if err != nil {
		if isAuditFailure(err) {
			return err
		}
		return finish(OutcomeError, err.Error())
	}
	result.Readings, result.Investigation = executed.Readings, executed.Investigation

	reason := ""
	if len(ignored) > 0 {
		reason = "the task's allowance named " + strings.Join(ignored, ", ") +
			", which this agent does not hold; an allowance can only narrow its grants"
	}
	outcome := OutcomeCompleted
	if executed.Outcome != "" {
		outcome = executed.Outcome
	}
	if executed.Reason != "" {
		reason = strings.TrimSpace(executed.Reason + "; " + reason)
		reason = strings.TrimSuffix(reason, ";")
	}
	return finish(outcome, reason)
}

// AuditFailure wraps an error from writing the audit log, so Handle can
// tell "the task failed" from "the agent cannot keep its record".
type AuditFailure struct{ Err error }

func (e *AuditFailure) Error() string { return "the audit log could not be written: " + e.Err.Error() }
func (e *AuditFailure) Unwrap() error { return e.Err }

func isAuditFailure(err error) bool {
	var failure *AuditFailure
	return errors.As(err, &failure)
}

func suffix(reason string) string {
	if reason == "" {
		return ""
	}
	return " — " + reason
}
