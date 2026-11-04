package model

import (
	"fmt"
	"strings"
	"time"
)

// ProbeManifest and Reading — the OBSERVED plane's atomic units.
//
// docs/DIAGNOSTIC_PLAN.md §2.6, and the Go half of
// shared/culprit_model/readings.py. A Fact is a claim about how something
// is meant to be or is set up to be; a Reading is what happened when
// someone actually went and measured, at a chosen point, at a known
// moment.
//
// Both halves are held to shared/tests/reading_conformance.json. The
// invariants below are enforced in both languages for the same reason the
// Fact ones are: `culprit probe` prints readings to stdout on a machine
// that may never reach the API, so a rule that lives only in Postgres —
// or only in Python — is a rule that does not hold for the artefact a
// developer actually pastes into a bug report.

// Verdict is the four-valued result of running a probe (§2.6).
//
// Inconclusive means the probe ran and could not establish the answer.
// Refused means the capability was not granted. Both are honest outputs
// and both appear in reports — "I could not check X because you have not
// granted Y" is a feature, not an error.
type Verdict string

const (
	VerdictPass         Verdict = "pass"
	VerdictFail         Verdict = "fail"
	VerdictInconclusive Verdict = "inconclusive"
	VerdictRefused      Verdict = "refused"
)

// NeedsReason reports whether a verdict is meaningless without one.
func (v Verdict) NeedsReason() bool {
	return v == VerdictInconclusive || v == VerdictRefused
}

// Valid reports whether v is one of the four.
func (v Verdict) Valid() bool {
	switch v {
	case VerdictPass, VerdictFail, VerdictInconclusive, VerdictRefused:
		return true
	}
	return false
}

// Effect is what running a probe does to the system under test.
//
// EffectMutate is named so it can be refused *by name* rather than
// falling through as an unrecognised string.
type Effect string

const (
	EffectInspect     Effect = "inspect"
	EffectObserve     Effect = "observe"
	EffectInterrogate Effect = "interrogate"
	EffectMutate      Effect = "mutate"
)

// Cost is how expensive a probe is to run, for a scheduler that does not
// exist yet (Phase 32 chooses which probes to run).
type Cost string

const (
	CostCheap     Cost = "cheap"
	CostMetered   Cost = "metered"
	CostIntrusive Cost = "intrusive"
)

// Evidence is one piece of what the probe saw, kept so a human can check
// it.
type Evidence struct {
	Kind     string `json:"kind"`
	Value    string `json:"value"`
	Redacted bool   `json:"redacted"`
}

// Produces is a (subject_template, predicate) pair a probe reports on.
type Produces struct {
	SubjectTemplate string `json:"subject_template"`
	Predicate       string `json:"predicate"`
}

// ProbeManifest describes a probe. Manifests are data, not code, so the
// catalogue is extensible without recompiling the engine (Phase 31
// field 3).
type ProbeManifest struct {
	ID           string   `json:"id"`
	Version      int      `json:"version"`
	Effect       Effect   `json:"effect"`
	Capabilities []string `json:"capabilities"`
	// Inputs is a JSON Schema object describing this probe's inputs.
	// Free-form by necessity — it is a schema, not a value.
	Inputs    map[string]any `json:"inputs,omitempty"`
	TimeoutMS int            `json:"timeout_ms"`
	// ExpectedFrom names the plane supplying the expectation this probe
	// measures against, or "" for a probe that reports a measurement with
	// no expectation.
	ExpectedFrom Plane      `json:"expected_from,omitempty"`
	Produces     []Produces `json:"produces,omitempty"`
	// Discriminates lists hypothesis ids a result rules out. Populated by
	// Phase 32; empty here means "discriminates nothing yet".
	Discriminates []string `json:"discriminates,omitempty"`
	Cost          Cost     `json:"cost,omitempty"`
}

// Validate enforces the same rules readings.py does.
//
// The mutate rule is the one that matters most. §2.6 states it without
// qualification — "effect: mutate fails manifest validation. No
// exceptions in this plan" — and it is enforced on the type rather than
// in the loader so that a manifest arriving by some path the loader does
// not guard still cannot produce a probe that writes.
func (m ProbeManifest) Validate() error {
	if m.Effect == EffectMutate {
		return fmt.Errorf(
			"probe %q declares effect: mutate. No probe in this plan may "+
				"mutate the system under test, and no *.write capability exists "+
				"to permit it (§2.6, §2.7)", m.ID)
	}
	switch m.Effect {
	case EffectInspect, EffectObserve, EffectInterrogate:
	default:
		return fmt.Errorf("probe %q has unknown effect %q", m.ID, m.Effect)
	}

	parts := strings.Split(m.ID, ".")
	if len(parts) != 3 || parts[0] != "probe" || parts[1] == "" || parts[2] == "" {
		return fmt.Errorf(
			"probe id %q must be 'probe.<group>.<name>', e.g. 'probe.net.tcp_connect'",
			m.ID)
	}
	if m.Version < 1 {
		return fmt.Errorf("probe %q must have version >= 1", m.ID)
	}
	if m.TimeoutMS <= 0 {
		return fmt.Errorf(
			"probe %q has timeout_ms %d; a probe that cannot run is not a probe",
			m.ID, m.TimeoutMS)
	}
	if m.TimeoutMS > 300_000 {
		return fmt.Errorf("probe %q has timeout_ms %d, above the 300000 ceiling",
			m.ID, m.TimeoutMS)
	}
	if m.ExpectedFrom == PlaneObserved {
		return fmt.Errorf(
			"probe %q declares expected_from: OBSERVED. A reading cannot be its "+
				"own expectation — that is the baseline-as-truth mistake the "+
				"three-plane model exists to prevent", m.ID)
	}
	if m.ExpectedFrom != "" && m.ExpectedFrom != PlaneIntent && m.ExpectedFrom != PlaneConfigured {
		return fmt.Errorf("probe %q has unknown expected_from %q", m.ID, m.ExpectedFrom)
	}
	switch m.Cost {
	case "", CostCheap, CostMetered, CostIntrusive:
	default:
		return fmt.Errorf("probe %q has unknown cost %q", m.ID, m.Cost)
	}
	for _, kind := range m.Discriminates {
		if !knownHypothesisKind(kind) {
			return fmt.Errorf(
				"probe %q discriminates %q, which is not a hypothesis kind the "+
					"isolation walk knows; a probe that names one it does not would "+
					"never be chosen, silently", m.ID, kind)
		}
	}
	for _, name := range m.Capabilities {
		if strings.HasSuffix(name, ".write") {
			return fmt.Errorf(
				"probe %q names capability %q. No *.write capability exists; "+
					"adding one is a design decision requiring its own plan "+
					"document, not a probe", m.ID, name)
		}
	}
	return nil
}

// Reading is one measurement, taken at one point, at one moment (§2.6).
type Reading struct {
	ProbeID      string `json:"probe_id"`
	ProbeVersion int    `json:"probe_version"`
	// Target is a subject URI (§2.3), built by BuildSubject — never
	// formatted by hand.
	Target      string         `json:"target"`
	Environment string         `json:"environment"`
	Verdict     Verdict        `json:"verdict"`
	Measured    map[string]any `json:"measured,omitempty"`
	Expected    map[string]any `json:"expected,omitempty"`
	// ExpectedSource is where the expectation came from, so a failing
	// reading can be traced back to the claim it contradicts.
	ExpectedSource *Provenance `json:"expected_source,omitempty"`
	Evidence       []Evidence  `json:"evidence,omitempty"`
	Reason         string      `json:"reason,omitempty"`
	TakenAt        time.Time   `json:"taken_at"`
	ExpiresAt      *time.Time  `json:"expires_at,omitempty"`
	AgentID        string      `json:"agent_id"`
	GrantsUsed     []string    `json:"grants_used,omitempty"`
}

// Validate enforces readings.py's invariants.
func (r Reading) Validate() error {
	if !r.Verdict.Valid() {
		return fmt.Errorf("reading from %q has unknown verdict %q", r.ProbeID, r.Verdict)
	}
	if r.Verdict.NeedsReason() && strings.TrimSpace(r.Reason) == "" {
		return fmt.Errorf(
			"a %s reading from %q must give a reason. A probe that cannot say "+
				"why it could not answer is a probe that guesses",
			r.Verdict, r.ProbeID)
	}
	if r.Verdict == VerdictRefused && len(r.GrantsUsed) > 0 {
		return fmt.Errorf(
			"a refused reading from %q lists grants_used %v. Refused means the "+
				"capability was not granted, so nothing was used",
			r.ProbeID, r.GrantsUsed)
	}
	if _, _, err := ParseSubject(r.Target); err != nil {
		return fmt.Errorf(
			"reading target %q is not a subject URI: %w. Build it with "+
				"BuildSubject, never by string formatting", r.Target, err)
	}
	if r.ProbeVersion < 1 {
		return fmt.Errorf("reading from %q must have probe_version >= 1", r.ProbeID)
	}
	if strings.TrimSpace(r.AgentID) == "" {
		return fmt.Errorf("reading from %q must name the agent that took it", r.ProbeID)
	}
	if r.ExpiresAt != nil && r.ExpiresAt.Before(r.TakenAt) {
		return fmt.Errorf("reading from %q expires before it was taken", r.ProbeID)
	}
	for _, item := range r.Evidence {
		if !item.Redacted && LooksLikeCredential(item.Value) {
			return fmt.Errorf(
				"evidence of kind %q on a reading from %q is credential-shaped "+
					"but is not marked redacted", item.Kind, r.ProbeID)
		}
	}
	return nil
}

// RedactReading returns a copy of a reading with every free-text field
// passed through RedactCredentials.
//
// # Why this is on the value, not in a renderer
//
// Phase 31 first applied redaction in the text renderer, and
// `culprit probe --format json` printed a password — the same defect
// Phase 30's audit found in `culprit diff`, on a new path. Redacting per
// output format always has one more format; redacting per call site
// always has one more site (standing invariant 11, and Phase 28's chain
// of four leaks where three were introduced by the fix for the previous
// one).
//
// So this is applied once, by the runner, before a Reading exists as a
// value at all. Everything downstream — the text report, the JSON
// bundle, `POST /readings`, a third-party tool reading that JSON — gets
// a reading that never carried the credential, rather than a promise
// that each of them remembers to strip it.
//
// A probe's inputs are the likely carrier: eight of the built-in probes
// copy a caller-supplied `url`, `host`, `key`, `package` or `table` into
// `measured` so a human can see what was measured, and a URL is the one
// of those that routinely has credentials in it.
func RedactReading(reading Reading) Reading {
	redacted := reading
	redacted.Reason = RedactCredentials(reading.Reason)
	redacted.Measured = redactMap(reading.Measured)
	redacted.Expected = redactMap(reading.Expected)

	if len(reading.Evidence) > 0 {
		evidence := make([]Evidence, len(reading.Evidence))
		for index, item := range reading.Evidence {
			// An item already marked redacted is left exactly as it is:
			// its value is a description the probe chose, not a leak.
			if !item.Redacted {
				item.Value = RedactCredentials(item.Value)
			}
			evidence[index] = item
		}
		redacted.Evidence = evidence
	}
	return redacted
}

// redactMap copies a measurement map, redacting string values.
//
// Only strings are rewritten. A number or a bool cannot carry a
// credential, and rendering them through a regex would turn `443` into a
// string in the JSON output, changing the wire shape to no purpose.
// Nested maps are walked, because a third-party probe may return one.
func redactMap(values map[string]any) map[string]any {
	if values == nil {
		return nil
	}
	redacted := make(map[string]any, len(values))
	for key, value := range values {
		switch typed := value.(type) {
		case string:
			redacted[key] = RedactCredentials(typed)
		case map[string]any:
			redacted[key] = redactMap(typed)
		case []any:
			items := make([]any, len(typed))
			for index, item := range typed {
				if text, ok := item.(string); ok {
					items[index] = RedactCredentials(text)
					continue
				}
				items[index] = item
			}
			redacted[key] = items
		default:
			redacted[key] = value
		}
	}
	return redacted
}

func knownHypothesisKind(kind string) bool {
	for _, known := range HypothesisKinds {
		if known == kind {
			return true
		}
	}
	return false
}
