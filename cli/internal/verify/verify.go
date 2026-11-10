// Package verify is the verification loop (docs/DIAGNOSTIC_PLAN.md Phase
// 34): after someone applies a change, it measures again every reading an
// investigation took, compares the environment with the record of it kept
// at diagnosis, and judges whether the change fixed the fault.
//
// It is deterministic and links no network package. Probes are run through
// the Runner interface that cmd/culprit supplies, as internal/isolate's
// are, and the captures before and after arrive as arguments, as they do
// for internal/check's Diff — so TestTheNetworkBoundaryIsAnAllowlist holds
// with no change to its allowlist.
//
// # The full reading set, measured again
//
// Every reading the investigation took is taken again, twice, from the
// request the walk recorded for it: the same probe, target, inputs and
// environment, under that environment's grants. No stored reading is
// reused. The verdict is model.Judge's, and is a pure function of what
// this package measured and compared; it decides nothing else.
package verify

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/diverge"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// RecordVersion is the version of the record `culprit diagnose` keeps.
const RecordVersion = 1

// Request is the request behind one reading of an investigation.
type Request struct {
	ReadingID   string         `json:"reading_id"`
	ProbeID     string         `json:"probe_id"`
	Target      string         `json:"target"`
	Environment string         `json:"environment"`
	Inputs      map[string]any `json:"inputs"`
}

// Record is what `culprit diagnose` keeps beside an investigation so it
// can be verified: where it ran, the request behind every reading, and
// whether a record of the environment before was taken.
type Record struct {
	Version         int    `json:"version"`
	InvestigationID string `json:"investigation_id"`
	Environment     string `json:"environment"`
	// Vantage is the component the walk ran inside (--from), or "".
	Vantage  string    `json:"vantage"`
	Requests []Request `json:"requests"`
	// BeforeCapture is the capture id of the environment as diagnosis
	// found it; BeforeAbsent says why there is none.
	BeforeCapture string `json:"before_capture,omitempty"`
	BeforeAbsent  string `json:"before_absent,omitempty"`
}

// Check holds a record to its investigation: one request per reading, each
// for the probe, target and environment that reading measured. A record
// that does not cover every reading cannot re-run the full set, and is
// refused rather than verified on part of it.
func (r Record) Check(investigation model.Investigation) error {
	if r.Version != RecordVersion {
		return fmt.Errorf("the record of %s is version %d; this binary reads version %d",
			investigation.ID, r.Version, RecordVersion)
	}
	if r.InvestigationID != investigation.ID || r.Environment != investigation.Environment {
		return fmt.Errorf("the record is of %s in %s, not %s in %s",
			r.InvestigationID, r.Environment, investigation.ID, investigation.Environment)
	}
	if (r.BeforeCapture == "") == (r.BeforeAbsent == "") {
		return fmt.Errorf("the record of %s must name its capture before, or say why there is none", investigation.ID)
	}
	byID := map[string]Request{}
	for _, request := range r.Requests {
		if _, twice := byID[request.ReadingID]; twice {
			return fmt.Errorf("the record holds two requests for reading %s", request.ReadingID)
		}
		byID[request.ReadingID] = request
	}
	if len(byID) != len(investigation.Readings) {
		return fmt.Errorf("the record holds %d requests for the %d readings of %s",
			len(byID), len(investigation.Readings), investigation.ID)
	}
	for _, item := range investigation.Readings {
		request, ok := byID[item.ID]
		if !ok {
			return fmt.Errorf("the record holds no request for reading %s", item.ID)
		}
		if request.ProbeID != item.Reading.ProbeID || request.Target != item.Reading.Target ||
			request.Environment != item.Reading.Environment {
			return fmt.Errorf("the request for reading %s is %s on %s in %s; the reading is %s on %s in %s",
				item.ID, request.ProbeID, request.Target, request.Environment,
				item.Reading.ProbeID, item.Reading.Target, item.Reading.Environment)
		}
	}
	return nil
}

// Runner runs one probe in one environment and returns its reading.
// cmd/culprit adapts internal/probe to this, under that environment's
// grants; tests count executions through it.
type Runner interface {
	Run(ctx context.Context, request Request) model.Reading
}

// Options are one verification.
type Options struct {
	ID            string
	Investigation model.Investigation
	Record        Record
	Changes       []model.Change
	// Before and After are the environment's captures at diagnosis and
	// now. Before is nil when the investigation has none; After is then
	// not taken.
	Before *model.CaptureBundle
	After  *model.CaptureBundle
	Runner Runner
	Now    func() time.Time
}

// Run measures every reading again, twice, compares the captures, and
// returns the judged verification. It returns an error only when it
// cannot verify at all — an investigation and record that do not match.
func Run(ctx context.Context, options Options) (model.Verification, error) {
	inv, record := options.Investigation, options.Record
	if err := record.Check(inv); err != nil {
		return model.Verification{}, err
	}
	if options.Before != nil && options.Before.CaptureID != record.BeforeCapture {
		return model.Verification{}, fmt.Errorf("the capture before is %s; the record names %s",
			options.Before.CaptureID, record.BeforeCapture)
	}
	if options.Before == nil && record.BeforeCapture != "" {
		return model.Verification{}, fmt.Errorf("the record names capture %s before, and it was not supplied",
			record.BeforeCapture)
	}
	now := options.Now
	if now == nil {
		now = time.Now
	}

	requests := map[string]Request{}
	for _, request := range record.Requests {
		requests[request.ReadingID] = request
	}
	// Two rounds over the full set, in the investigation's order: two
	// consecutive runs of every reading, so a pass that does not hold is
	// seen as the flip it is.
	runs := make([][2]model.Reading, len(inv.Readings))
	for round := 0; round < 2; round++ {
		for index, item := range inv.Readings {
			runs[index][round] = options.Runner.Run(ctx, requests[item.ID])
		}
	}
	reran := make([]model.Rerun, len(inv.Readings))
	for index, item := range inv.Readings {
		reran[index] = model.Rerun{
			ReadingID: item.ID, Was: item.Reading.Verdict, ProbeID: item.Reading.ProbeID,
			Target: item.Reading.Target, Environment: item.Reading.Environment, Runs: runs[index],
		}
	}

	var before, after *string
	var differences []model.Difference
	if options.Before != nil && options.After != nil {
		beforeID, afterID := options.Before.CaptureID, options.After.CaptureID
		before, after = &beforeID, &afterID
		differences = Differences(*options.Before, *options.After)
	}

	// Readings the walk took in a reference environment are measured again
	// there, with the rest, and judged with them; the captures compare the
	// investigation's own environment.
	verification, err := model.NewVerification(options.ID, inv.ID, inv.Environment, options.Changes,
		reran, before, after, differences, now().UTC(),
		func(judged model.Judgement) string {
			return describe(judged, reran, options.Changes, differences, record)
		})
	if err != nil {
		return model.Verification{}, fmt.Errorf("the verification does not validate: %w", err)
	}
	return verification, nil
}

// Differences compares the environment before and after with the engine
// `culprit diff` uses (diverge.CompareAll), the two captures standing in
// for two environments. Each question they answer differently, or a thing
// one enumerated and the other lacks, is one difference — subject and
// predicate, never a value.
func Differences(before, after model.CaptureBundle) []model.Difference {
	result := diverge.CompareAll([]model.CaptureBundle{
		renamed(before, "before"), renamed(after, "after"),
	}, diverge.Options{Now: before.StartedAt})
	seen := map[[2]string]bool{}
	var differences []model.Difference
	for _, divergence := range result.Divergences {
		if divergence.Kind != model.KindEnvVsEnv {
			continue
		}
		key := [2]string{divergence.Subject, divergence.Predicate}
		if seen[key] {
			continue
		}
		seen[key] = true
		differences = append(differences, model.Difference{Subject: divergence.Subject, Predicate: divergence.Predicate})
	}
	sort.Slice(differences, func(i, j int) bool {
		if differences[i].Subject != differences[j].Subject {
			return differences[i].Subject < differences[j].Subject
		}
		return differences[i].Predicate < differences[j].Predicate
	})
	return differences
}

// renamed gives one capture of an environment its own scope, so the
// comparator treats before and after as two environments.
func renamed(bundle model.CaptureBundle, side string) model.CaptureBundle {
	name := side
	copied := bundle
	copied.Environment = &name
	copied.Facts = make([]model.Fact, len(bundle.Facts))
	for index, fact := range bundle.Facts {
		fact.Environment = name
		copied.Facts[index] = fact
	}
	return copied
}

// ---- the reason, in words --------------------------------------------------

func describe(judged model.Judgement, reran []model.Rerun, changes []model.Change,
	differences []model.Difference, record Record,
) string {
	named := func(set []model.Rerun) string {
		var parts []string
		for _, rerun := range set {
			parts = append(parts, fmt.Sprintf("%s on %s (%s)", rerun.ProbeID, rerun.Target, rerun.ReadingID))
		}
		return strings.Join(parts, "; ")
	}
	where := func(was, now model.Verdict) []model.Rerun {
		var matched []model.Rerun
		for _, rerun := range reran {
			if rerun.Was == was && rerun.Now() == now {
				matched = append(matched, rerun)
			}
		}
		return matched
	}

	switch judged.Verdict {
	case model.VerificationNotResolved:
		return "still failing on both runs: " + named(where(model.VerdictFail, model.VerdictFail))
	case model.VerificationRegressed:
		return "the readings that failed pass now, but these passed before and fail now: " +
			named(where(model.VerdictPass, model.VerdictFail))
	case model.VerificationChangedUnderneath:
		var unexplained []string
		for _, difference := range differences {
			if model.Explain(difference, changes).ExplainedBy == nil {
				unexplained = append(unexplained, difference.Subject+" ("+difference.Predicate+")")
			}
		}
		return fmt.Sprintf("the readings that failed pass now, but the environment changed where %s does not explain it: %s",
			changeList(changes), strings.Join(unexplained, ", "))
	case model.VerificationVerified:
		failed := where(model.VerdictFail, model.VerdictPass)
		since := "nothing the capture records changed since diagnosis"
		if len(differences) > 0 {
			since = fmt.Sprintf("every difference since diagnosis (%d) is explained by %s", len(differences), changeList(changes))
		}
		return fmt.Sprintf("every reading that failed passes on both runs (%s), every reading that passed still passes, and %s",
			named(failed), since)
	}

	// Inconclusive: the first thing that stopped it, in the order Judge asks.
	failed, unsettled := 0, []model.Rerun{}
	for _, rerun := range reran {
		if rerun.Was == model.VerdictFail {
			failed++
		}
		if rerun.Now() == "" {
			unsettled = append(unsettled, rerun)
		}
	}
	switch {
	case failed == 0:
		return "the investigation has no failing reading, so there is nothing a change can be seen to fix"
	case len(unsettled) > 0:
		var parts []string
		for _, rerun := range unsettled {
			first, second := rerun.Runs[0], rerun.Runs[1]
			if first.Verdict != second.Verdict {
				parts = append(parts, fmt.Sprintf("%s on %s (%s) was %s, then %s",
					rerun.ProbeID, rerun.Target, rerun.ReadingID, first.Verdict, second.Verdict))
				continue
			}
			parts = append(parts, fmt.Sprintf("%s on %s (%s) was %s: %s",
				rerun.ProbeID, rerun.Target, rerun.ReadingID, first.Verdict, first.Reason))
		}
		return "not every reading could be settled: " + strings.Join(parts, "; ")
	case len(changes) == 0:
		return "the readings that failed pass now, but no change was named (--change), so nothing says what fixed it"
	case record.BeforeAbsent != "":
		return "the readings that failed pass now, but there is no record of the environment before to compare with: " +
			record.BeforeAbsent
	}
	for _, rerun := range reran {
		if rerun.Now() == model.VerdictFail {
			return fmt.Sprintf("%s on %s (%s) could not answer at diagnosis and fails now", rerun.ProbeID, rerun.Target, rerun.ReadingID)
		}
	}
	return "the readings do not settle it"
}

func changeList(changes []model.Change) string {
	var labels []string
	for _, change := range changes {
		labels = append(labels, change.Label())
	}
	if len(labels) == 0 {
		return "no change named"
	}
	return strings.Join(labels, ", ")
}
