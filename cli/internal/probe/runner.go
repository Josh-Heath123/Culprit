package probe

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/capability"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// DefaultConcurrency is how many probes run at once. Low on purpose: a
// probe opens a socket to somebody else's production system, and the
// tool's job is to diagnose a fault, not add to it.
const DefaultConcurrency = 4

// Runner executes probes and emits readings.
//
// It owns the three things a probe must not decide for itself:
//
//   - whether it is allowed to run at all (the capability ledger),
//   - how long it may take (the manifest's timeout),
//   - what goes in the parts of a Reading that describe the run rather
//     than the measurement (`taken_at`, `agent_id`, `grants_used`).
//
// The last one matters more than it looks. If a probe wrote its own
// `grants_used`, a reading could claim an authority nobody granted, and
// the audit trail the permission model rests on would be self-reported.
type Runner struct {
	catalogue   *Catalogue
	ledger      *capability.Ledger
	deps        Deps
	agentID     string
	concurrency int
	// overrides carry culprit.yaml's `probes:` section: enable/disable
	// and timeout overrides, per probe id.
	overrides map[string]Override
	// expectations are the facts readings are measured against
	// (expect.go). Nil means none were supplied, which every probe that
	// compares against a declaration reports as inconclusive.
	expectations *Expectations
}

// Override is one entry of culprit.yaml's `probes:` section (field 10).
type Override struct {
	Enabled   *bool
	TimeoutMS int
	// Environments restricts a probe to named environments. Empty means
	// every environment.
	Environments []string
}

// Options configures a Runner.
type Options struct {
	Catalogue   *Catalogue
	Ledger      *capability.Ledger
	Deps        Deps
	AgentID     string
	Concurrency int
	Overrides   map[string]Override
	// Expectations, when set, are resolved for every request that does
	// not already carry one.
	Expectations *Expectations
}

// NewRunner builds a Runner. A nil catalogue means the built-in one.
func NewRunner(options Options) *Runner {
	catalogue := options.Catalogue
	if catalogue == nil {
		catalogue = BuiltIn()
	}
	concurrency := options.Concurrency
	if concurrency <= 0 {
		concurrency = DefaultConcurrency
	}
	agent := options.AgentID
	if agent == "" {
		agent = "culprit-cli"
	}
	deps := options.Deps
	if deps.Now == nil {
		deps.Now = time.Now
	}
	return &Runner{
		catalogue:    catalogue,
		ledger:       options.Ledger,
		deps:         deps,
		agentID:      agent,
		concurrency:  concurrency,
		overrides:    options.Overrides,
		expectations: options.Expectations,
	}
}

// Run executes every request and returns one reading per request.
//
// The result is sorted by (probe_id, target) so two runs over the same
// inputs produce the same output in the same order — `culprit` is a
// tool people diff, and concurrency must not show up in the diff.
func (r *Runner) Run(ctx context.Context, requests []Request) []model.Reading {
	readings := make([]model.Reading, len(requests))
	semaphore := make(chan struct{}, r.concurrency)
	var wait sync.WaitGroup

	for index, request := range requests {
		wait.Add(1)
		go func(index int, request Request) {
			defer wait.Done()
			semaphore <- struct{}{}
			defer func() { <-semaphore }()
			readings[index] = r.runOne(ctx, request)
		}(index, request)
	}
	wait.Wait()

	sort.SliceStable(readings, func(i, j int) bool {
		if readings[i].ProbeID != readings[j].ProbeID {
			return readings[i].ProbeID < readings[j].ProbeID
		}
		return readings[i].Target < readings[j].Target
	})
	return readings
}

// runOne is the whole lifecycle of a single probe: look it up, check it
// is permitted, check it is enabled here, run it under its timeout, and
// stamp the result.
func (r *Runner) runOne(ctx context.Context, request Request) model.Reading {
	probe, found := r.catalogue.Get(request.ProbeID)
	if !found {
		return r.emit(request, model.ProbeManifest{ID: request.ProbeID, Version: 0},
			inconclusive(fmt.Sprintf(
				"no probe %q in the catalogue; `culprit probe --list` shows what there is",
				request.ProbeID)), nil)
	}

	manifest := probe.Manifest()

	if reason, disabled := r.disabled(manifest.ID, request.Environment); disabled {
		return r.emit(request, manifest, inconclusive(reason), nil)
	}

	// The capability gate. Nothing has been dialled yet and nothing will
	// be if this refuses — that is the whole point of asking here rather
	// than inside the probe.
	granted, missing := r.permitted(manifest, request)
	if !granted {
		return r.emit(request, manifest, Outcome{
			Verdict: model.VerdictRefused,
			Reason: fmt.Sprintf("%s is not granted for this environment",
				strings.Join(missing, " and ")),
		}, nil)
	}

	timeout := time.Duration(manifest.TimeoutMS) * time.Millisecond
	if override, ok := r.overrides[manifest.ID]; ok && override.TimeoutMS > 0 {
		timeout = time.Duration(override.TimeoutMS) * time.Millisecond
	}
	runCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	// Resolve the expectation after the capability gate, so a refused
	// probe never even looks for one, and before Run, so the probe
	// measures against it. A caller that set one keeps it.
	var conflicts []model.Fact
	if request.Expectation == nil {
		resolution := r.expectations.Resolve(manifest, request)
		request.Expectation = resolution.Fact
		request.NoExpectation = resolution.Missing
		conflicts = resolution.Conflicts
	}

	outcome := probe.Run(runCtx, request, r.deps)

	// expected_source is the reading's link back to the claim it was
	// measured against, so only the probe can set it: only the probe knows
	// whether it compared against the fact it was handed, or against an
	// explicit input that overrode it, or against nothing at all. Stamping
	// it here whenever a fact was *found* made a reading run with
	// `--input expect_columns=id` cite the migration it ignored (found by
	// the Phase 31.1 invariant audit). The conflict evidence follows the
	// same rule: it is about the source the reading cites.
	if outcome.ExpectedSource != nil && request.Expectation != nil &&
		outcome.Verdict != model.VerdictRefused {
		outcome.Evidence = append(outcome.Evidence,
			conflictEvidence(request.Expectation, conflicts)...)
	}

	// A probe that overran its own timeout reports that as the reason it
	// could not tell, rather than as a failure of the thing it measured.
	// "The database did not answer within 2s" and "the database is
	// broken" are different findings and only one of them is evidence.
	if runCtx.Err() != nil && outcome.Verdict == model.VerdictFail {
		outcome = inconclusive(fmt.Sprintf(
			"probe did not complete within %s; no verdict was reached", timeout))
	}

	return r.emit(request, manifest, outcome, manifest.Capabilities)
}

// permitted asks the ledger about every capability the manifest declares.
//
// Every one is asked about even after the first refusal, so the ledger
// records the full set of what was missing. A report that names one
// missing grant when two are needed sends the reader round the loop
// twice.
func (r *Runner) permitted(manifest model.ProbeManifest, request Request) (bool, []string) {
	if len(manifest.Capabilities) == 0 {
		return true, nil
	}
	if r.ledger == nil {
		return false, manifest.Capabilities
	}

	component := componentOf(request.Target)
	var missing []string
	for _, name := range manifest.Capabilities {
		// An unknown capability name is treated as missing, never as
		// satisfied. A typo in a manifest must close a door, not open one.
		if !capability.Known(name) {
			missing = append(missing, name)
			continue
		}
		if !r.ledger.Require(capability.Capability(name), component, manifest.ID) {
			missing = append(missing, name)
		}
	}
	return len(missing) == 0, missing
}

// disabled applies culprit.yaml's `probes:` section.
func (r *Runner) disabled(probeID, environment string) (string, bool) {
	override, ok := r.overrides[probeID]
	if !ok {
		return "", false
	}
	if override.Enabled != nil && !*override.Enabled {
		return fmt.Sprintf("%s is disabled in culprit.yaml", probeID), true
	}
	if len(override.Environments) > 0 && environment != "" {
		for _, name := range override.Environments {
			if name == environment {
				return "", false
			}
		}
		return fmt.Sprintf("%s is not enabled for environment %q in culprit.yaml",
			probeID, environment), true
	}
	return "", false
}

// emit stamps the run-describing fields and validates before returning.
//
// A reading that fails validation is replaced by an inconclusive one
// naming the bug, rather than being dropped or returned invalid. Dropping
// it would make a probe failure look like a probe that was never asked
// to run, which is the one outcome a diagnostic tool must never produce.
func (r *Runner) emit(
	request Request,
	manifest model.ProbeManifest,
	outcome Outcome,
	grants []string,
) model.Reading {
	version := manifest.Version
	if version < 1 {
		version = 1
	}
	used := grants
	if outcome.Verdict == model.VerdictRefused {
		used = nil
	}

	// Redaction happens here, once, before the Reading exists as a value —
	// not in a renderer. The first cut of this phase redacted in the text
	// report and `--format json` promptly printed a password, which is the
	// same defect Phase 30's audit found in `culprit diff` arriving on a
	// new path. Everything downstream (text, JSON, POST /readings, and
	// whatever a third party does with that JSON) now receives a reading
	// that never carried the credential.
	reading := model.RedactReading(model.Reading{
		ProbeID:        manifest.ID,
		ProbeVersion:   version,
		Target:         request.Target,
		Environment:    request.Environment,
		Verdict:        outcome.Verdict,
		Measured:       outcome.Measured,
		Expected:       outcome.Expected,
		ExpectedSource: outcome.ExpectedSource,
		Evidence:       outcome.Evidence,
		Reason:         outcome.Reason,
		TakenAt:        r.deps.Now().UTC(),
		ExpiresAt:      outcome.ExpiresAt,
		AgentID:        r.agentID,
		GrantsUsed:     used,
	})

	if err := reading.Validate(); err != nil {
		return model.Reading{
			ProbeID:      manifest.ID,
			ProbeVersion: version,
			Target:       request.Target,
			Environment:  request.Environment,
			Verdict:      model.VerdictInconclusive,
			Reason: fmt.Sprintf(
				"probe %s produced a reading that does not validate (%v); "+
					"this is a bug in the probe, not a finding about the system",
				manifest.ID, err),
			TakenAt: r.deps.Now().UTC(),
			AgentID: r.agentID,
		}
	}
	return reading
}

// componentOf pulls the component name out of a subject URI, for the
// ledger's refusal records — "which component was I looking at when I
// found I could not do this".
func componentOf(subject string) string {
	kind, parts, err := model.ParseSubject(subject)
	if err != nil {
		return subject
	}
	switch kind {
	case model.KindConnection, model.KindAuth:
		return parts["from_component"]
	case model.KindComponent, model.KindImage:
		// These two key their part "name", not "component" (see
		// model/subjects.go). Reading "component" here returned empty, so
		// every refusal against a component target was recorded with no
		// component at all — the ledger entry said which capability was
		// missing but not what we were looking at. Found by the Phase 31
		// phase audit, in a reason string that read "... is not set for ,".
		return parts["name"]
	default:
		return parts["component"]
	}
}
