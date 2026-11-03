// Package probe runs probes: active readings taken at a chosen point.
//
// Phase 31. Passive comparison (internal/diverge) can tell you that two
// sources disagree about what should exist. It cannot tell you whether A
// can actually reach B from where A sits. That is the multimeter's
// defining property, and it needs a socket.
//
// # Why this is not in internal/check
//
// `internal/check` links no networking package at all — not `net`, not
// `net/http`, not `crypto/tls` — and `cli/cmd/culprit/check_test.go`
// asserts it against `go list -deps`. A package that cannot link a socket
// cannot open one, which is a stronger guarantee than any list of vendor
// names. Probes obviously must open sockets, so they live here, outside
// that boundary, exactly as `internal/capture` does and for the same
// reason. That test's own failure message says so: "if a later phase
// genuinely needs one, it belongs in its own package with its own
// capability gate — not linked into the comparator."
//
// # Every check asks the ledger first
//
// A probe never dials anything before `capability.Ledger` has said yes.
// What is not granted is a `refused` reading with a reason naming the
// missing capability — never an omission, and never a silent skip. This
// is the property Phase 30 established and the reason its refusals show
// up in reports.
//
// # Deterministic
//
// No LLM, here or anywhere near here (.claude/rules/determinism.md). A
// verdict is computed from what came back on the wire, compared against
// an expectation that came from a Fact. Nothing is judged.
package probe

import (
	"context"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Request is one thing a probe is asked to measure.
//
// Phase 31 field 17: nothing here chooses what to probe. A human or a
// script names the target; automatic probe selection is Phase 32.
type Request struct {
	// ProbeID names the probe in the catalogue.
	ProbeID string
	// Target is a subject URI (§2.3) — what is being measured.
	Target string
	// Environment is which deployment this reading is about. Readings are
	// OBSERVED-plane, so this is never empty.
	Environment string
	// Inputs are the probe's own parameters, validated against its
	// manifest's `inputs` schema.
	Inputs map[string]any
	// Expectation is the fact this reading is measured against, when one
	// was found. A probe with no expectation reports a measurement and
	// leaves the comparison to whoever asked.
	Expectation *model.Fact
}

// Outcome is what a probe returns. The runner turns it into a Reading,
// stamping the parts a probe must not choose for itself — when it ran,
// which agent ran it, and which grants it actually used.
//
// Keeping those out of the probe's hands is deliberate: a probe that can
// write its own `grants_used` is a probe that can claim an authority it
// was never given.
type Outcome struct {
	Verdict        model.Verdict
	Measured       map[string]any
	Expected       map[string]any
	ExpectedSource *model.Provenance
	Evidence       []model.Evidence
	// Reason is required when the verdict is inconclusive or refused.
	// Reading.Validate enforces it; the runner checks before emitting so
	// a probe bug surfaces as a loud failure rather than a dropped row.
	Reason string
	// ExpiresAt marks a reading whose answer has a known shelf life — a
	// TLS expiry check, say. Optional.
	ExpiresAt *time.Time
}

// Probe is one measurement a `culprit` binary knows how to take.
//
// Implementations must be pure with respect to their Deps: everything
// that touches the outside world arrives through Deps, so every probe is
// testable against a fake and every probe has a fixture for all three of
// pass, fail and inconclusive (field 13).
type Probe interface {
	// Manifest describes the probe: its effect, the capabilities it
	// needs, its timeout, and what it produces. Manifests are data, so
	// the catalogue is extensible without recompiling the engine.
	Manifest() model.ProbeManifest
	// Run takes the measurement. It must not dial anything the manifest
	// did not declare a capability for — the runner has already checked
	// those, and a probe that reaches further is a probe that escaped its
	// grant.
	//
	// Run returns an Outcome rather than an error: "I could not tell" is
	// a verdict (inconclusive), not a failure of the program.
	Run(ctx context.Context, request Request, deps Deps) Outcome
}

// inconclusive is the constructor every probe uses when its preconditions
// are unmet. Field 14 requires it of all of them: "Every probe returns
// inconclusive with a reason rather than a guess when its preconditions
// are unmet."
func inconclusive(reason string) Outcome {
	return Outcome{Verdict: model.VerdictInconclusive, Reason: reason}
}

// pass and fail keep the catalogue readable; measured is the evidence a
// human checks the verdict against.
func pass(measured map[string]any) Outcome {
	return Outcome{Verdict: model.VerdictPass, Measured: measured}
}

func fail(measured map[string]any, reason string) Outcome {
	return Outcome{Verdict: model.VerdictFail, Measured: measured, Reason: reason}
}
