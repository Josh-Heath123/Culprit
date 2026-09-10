package model

import (
	"strings"
	"time"
)

// Divergence — two facts about the same thing that disagree (§2.5).
// The Go mirror of `shared/culprit_model/facts.py`'s Divergence.
//
// This is the finding. Everything else in the product exists to produce
// one of these honestly, or to explain one.

// DivergenceKind names which two planes disagreed.
//
// **Phase 29 emits exactly one of these: INTENT_CONFLICT.** Every fact
// the CLI can produce today is on the INTENT plane, so every
// disagreement it can find is between two intent sources. The other
// kinds need CONFIGURED (Phase 30) or OBSERVED (Phase 31) facts to
// exist, and emitting one before then would be a claim about a plane
// nothing has read.
//
// That is not a limitation worth apologising for. §0.3 makes the point
// directly: two sources of intent disagreeing is *usually itself the
// bug*, and it is detectable before anything is deployed.
type DivergenceKind string

const (
	KindIntentConflict      DivergenceKind = "intent_conflict"
	KindIntentVsConfigured  DivergenceKind = "intent_vs_configured"
	KindIntentVsObserved    DivergenceKind = "intent_vs_observed"
	KindConfiguredVsObserve DivergenceKind = "configured_vs_observed"
	KindEnvVsEnv            DivergenceKind = "env_vs_env"
	KindBaselineDeviation   DivergenceKind = "baseline_deviation"
)

// Severity is computed deterministically from the system model (§2.5),
// never by judgement and never by an LLM.
type Severity string

const (
	SeverityBreaksRequestPath Severity = "breaks_request_path"
	SeverityDegrades          Severity = "degrades"
	SeverityCosmetic          Severity = "cosmetic"
	SeverityUnknown           Severity = "unknown"
)

// Rank orders severities for `--fail-on` comparisons. Higher is worse.
//
// `unknown` sits *above* cosmetic deliberately. "We could not work out
// how bad this is" must not be quieter than "we worked it out and it is
// trivial" — the honest ordering puts the thing nobody understands ahead
// of the thing everybody does.
func (s Severity) Rank() int {
	switch s {
	case SeverityBreaksRequestPath:
		return 3
	case SeverityDegrades:
		return 2
	case SeverityUnknown:
		return 1
	default:
		return 0
	}
}

// AtLeast reports whether this severity meets a threshold.
func (s Severity) AtLeast(threshold Severity) bool { return s.Rank() >= threshold.Rank() }

// DivergenceStatus mirrors §2.5.
type DivergenceStatus string

const (
	StatusOpen         DivergenceStatus = "open"
	StatusAcknowledged DivergenceStatus = "acknowledged"
	StatusResolved     DivergenceStatus = "resolved"
	StatusSuppressed   DivergenceStatus = "suppressed"
)

// Divergence is one finding.
//
// `Left` and `Right` are the two facts, whole. Keeping them rather than
// a rendered summary is what makes a finding *checkable*: the report can
// tell the reader which file and line each side came from, and a person
// who disagrees with the finding can go and look. A finding you cannot
// audit is an opinion.
type Divergence struct {
	Kind      DivergenceKind `json:"kind"`
	Subject   string         `json:"subject"`
	Predicate string         `json:"predicate"`
	Left      Fact           `json:"left"`
	Right     Fact           `json:"right"`
	Severity  Severity       `json:"severity"`
	// Explanation is one sentence a human reads first. Built from the
	// two facts by the comparator, never freeform prose and never
	// generated: D8 forbids an LLM anywhere on this path.
	Explanation string `json:"explanation"`
	// SeverityReason says *why* that severity, in the model's own terms
	// ("orders-api is on the request path from web"). A severity nobody
	// can trace is a severity nobody trusts.
	SeverityReason string           `json:"severity_reason,omitempty"`
	Status         DivergenceStatus `json:"status"`
	// SuppressedBy carries the suppression's reason when Status is
	// suppressed, so a suppressed finding still explains itself in the
	// report rather than vanishing.
	SuppressedBy string    `json:"suppressed_by,omitempty"`
	FirstSeenAt  time.Time `json:"first_seen_at"`
}

// ID is a stable identifier for one finding.
//
// Derived from what the finding *is* — its subject, its predicate, and
// the two *sources* that disagreed — so the same fault reported on two
// consecutive CI runs carries the same id, and a consumer can tell
// "still broken" from "broken again". Deliberately not a hash of the
// whole Divergence: the values and the timestamps move, the identity
// does not.
//
// # A source is an extractor *and* an artefact
//
// Both halves, and the second one is not decoration. `sameSource` in the
// comparator already defines a source that way, for a reason worth
// repeating here: one extractor legitimately reads several independent
// descriptions of the same thing. `culprit-extract-python` reports the
// columns the ORM declares *and* the columns the migration chain
// creates, and an unmigrated column is precisely those two disagreeing —
// same extractor on both sides of the finding.
//
// Keying the identity on the extractors alone made those ids collide.
// Two genuinely different findings about one `(subject, predicate)` —
// models against migrations, and models against a committed schema.sql —
// produced the same key, so the second `ON CONFLICT DO UPDATE` on upload
// overwrote the first. One row survived, holding only the later finding,
// and the endpoint reported both as handled. A real fault deleted, with
// the response saying nothing was lost.
//
// That is the exact failure `divergence_key` was introduced to prevent,
// and it is worth noticing that it is the same mistake as conflating an
// extractor with a source in `sameSource` — made twice, in two places,
// from the same wrong idea.
//
// **Kept byte-identical to `Divergence.identity()` in
// `shared/culprit_model/facts.py`**, held there by
// `shared/tests/divergence_identity_conformance.json`, which both
// languages read.
func (d Divergence) ID() string {
	return strings.Join([]string{
		d.Subject,
		d.Predicate,
		d.Left.Provenance.Extractor,
		d.Left.Provenance.Artefact,
		d.Right.Provenance.Extractor,
		d.Right.Provenance.Artefact,
	}, "|")
}
