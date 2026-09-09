package model

import (
	"fmt"
	"strings"
	"time"
)

// Fact — the atomic unit (§2.2). The Go mirror of
// shared/culprit_model/facts.py.
//
// The field names and JSON tags are the contract: this struct is
// marshalled by `culprit intent`, unmarshalled by FastAPI into the
// Python Fact, and stored. A rename on either side is a wire break, so
// cli/internal/model/protocol_conformance_test.go asserts the shape
// against a fixture both languages read.

// Plane is what kind of claim a Fact is (§2.1).
type Plane string

const (
	PlaneIntent     Plane = "INTENT"
	PlaneConfigured Plane = "CONFIGURED"
	PlaneObserved   Plane = "OBSERVED"
)

// RequiresEnvironment reports whether a fact on this plane must carry
// one. INTENT is environment-independent by definition (§0.2), which is
// why intent_facts has no environment column at all.
func (p Plane) RequiresEnvironment() bool { return p != PlaneIntent }

// SourceKind is how a Fact was come by.
type SourceKind string

const (
	SourceSpec          SourceKind = "spec"
	SourceIntrospection SourceKind = "introspection"
	SourceStatic        SourceKind = "static"
	SourceTest          SourceKind = "test"
	SourceAssertion     SourceKind = "assertion"
	SourceObservation   SourceKind = "observation"
)

// Confidence ranks (§2.4). Named landmarks, not a closed set — an
// extractor may report any 0..100. Rank orders reports and picks
// comparison defaults; it never silently discards a source.
const (
	RankDeveloperAssertion    = 100
	RankRuntimeIntrospection  = 90
	RankCommittedSpec         = 80
	RankStaticFrameworkCode   = 60
	RankStaticTests           = 50
	RankStaticClientCallSites = 40
	RankObservedTraffic       = 20
)

// Provenance is where a Fact came from, precisely enough to go and look.
type Provenance struct {
	SourceKind SourceKind `json:"source_kind"`
	Extractor  string     `json:"extractor"`
	// Artefact and Locator are what turn a report line into something a
	// developer can open: "openapi.json" plus "$.paths./orders.post", or
	// "api/app/main.py" plus "L142".
	Artefact       string `json:"artefact,omitempty"`
	Locator        string `json:"locator,omitempty"`
	ConfidenceRank int    `json:"confidence_rank"`
}

// Fact is a single claim, on one plane, about one subject.
type Fact struct {
	Plane     Plane  `json:"plane"`
	Subject   string `json:"subject"`
	Predicate string `json:"predicate"`
	Value     any    `json:"value,omitempty"`
	// ValueShape is set instead of Value for a config key (§2.2). A
	// pointer so "no shape" and "the zero shape" stay distinguishable.
	ValueShape  *ValueShape `json:"value_shape,omitempty"`
	GrantRef    string      `json:"grant_ref,omitempty"`
	Environment string      `json:"environment,omitempty"`
	Provenance  Provenance  `json:"provenance"`
	CapturedAt  time.Time   `json:"captured_at"`
	CaptureID   string      `json:"capture_id"`
}

// Validate enforces the same three invariants facts.py does, and for the
// same reason: each has a silent-wrong-answer failure mode, and an
// extractor is the last place any of them can be caught cheaply.
//
// The config rule is the one that matters most (Phase 28 acceptance
// criterion 3). Enforcing it here as well as in Python is not
// belt-and-braces duplication: `culprit intent` prints a bundle to
// stdout that may never reach the API at all, so if the Go side did not
// check, nothing would.
func (f Fact) Validate() error {
	if f.Plane.RequiresEnvironment() && f.Environment == "" {
		return fmt.Errorf("a %s fact requires an environment", f.Plane)
	}
	if !f.Plane.RequiresEnvironment() && f.Environment != "" {
		return fmt.Errorf(
			"a %s fact must not carry an environment (got %q) — INTENT is environment-independent",
			f.Plane, f.Environment)
	}

	kind, _, err := ParseSubject(f.Subject)
	if err != nil {
		// Left alone deliberately: that is BuildSubject's error to
		// report, and duplicating it here turns one clear failure into
		// two confusing ones.
		return nil //nolint:nilerr
	}
	if kind != KindConfig {
		if f.ValueShape != nil {
			return fmt.Errorf(
				"value_shape is only meaningful for a config: subject (got %q)", f.Subject)
		}
		return nil
	}
	// The one exception, mirroring facts.py: a bool is allowed without a
	// grant. Extractors need to assert things *about* a key that are not
	// its value — read_by, required, exists — and a bool has two
	// inhabitants, so it cannot carry a credential. Every other type can,
	// including a number (a numeric API key is a real thing), so every
	// other type needs a grant.
	if f.Value != nil && !isBool(f.Value) && strings.TrimSpace(f.GrantRef) == "" {
		return fmt.Errorf(
			"a fact about config key %q may not carry a literal %T value without a "+
				"grant_ref naming the per-key grant that permitted it — put the "+
				"classification in value_shape instead (docs/DIAGNOSTIC_PLAN.md §2.2). "+
				"Only a bool is allowed ungranted, for assertions about a key rather "+
				"than its value.", f.Subject, f.Value)
	}
	return nil
}

// isBool reports whether a decoded JSON value is a boolean.
//
// Checked against the decoded `any` rather than a Go bool specifically:
// a fact arriving from an extractor's stdout has been through
// encoding/json, where a JSON `true` becomes a bool and a JSON `"true"`
// stays a string. That distinction is exactly the one being enforced.
func isBool(value any) bool {
	_, ok := value.(bool)
	return ok
}

// NewConfigFact is the only sanctioned way to make a fact about a config
// key from this binary. It takes a ValueShape and has no parameter a
// literal value could be passed through, so the guarantee holds at the
// call site rather than depending on every caller remembering Validate.
func NewConfigFact(
	plane Plane,
	component, key, predicate string,
	shape ValueShape,
	provenance Provenance,
	capturedAt time.Time,
	captureID string,
) (Fact, error) {
	subject, err := BuildSubject(KindConfig, Parts{"component": component, "key": key})
	if err != nil {
		return Fact{}, err
	}
	fact := Fact{
		Plane:      plane,
		Subject:    subject,
		Predicate:  predicate,
		ValueShape: &shape,
		Provenance: provenance,
		CapturedAt: capturedAt,
		CaptureID:  captureID,
	}
	return fact, fact.Validate()
}
