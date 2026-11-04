package model

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

// Investigation, Hypothesis and FaultEdge — docs/DIAGNOSTIC_PLAN.md §2.8.
//
// An incident is something that happened to you; an investigation is
// something you are doing. It holds the symptom it started from, the
// hypotheses the model gave it, every reading it took, and the fault tree
// those readings established.
//
// The Go half of shared/culprit_model/investigations.py, held to
// shared/tests/investigation_conformance.json the way Reading is held to
// reading_conformance.json. `culprit diagnose` writes this as JSON on a
// machine that may never reach the API, so the rules below are enforced
// here, in the type, and not only where the API stores it (Phase 32,
// part 2).
//
// # The rule this file exists for
//
// A fault edge cannot exist without at least one reading that established
// it, and every reading it cites must be one this investigation took.
// That is the structural guarantee against narrative masquerading as
// diagnosis: an edge in the tree is a claim, and a claim with no
// measurement behind it is not allowed to be built.

// Relation is what a fault edge says about its two subjects.
type Relation string

const (
	// RelationSymptomOf: From (what the user saw) is a symptom of To
	// (the component that failed to serve it).
	RelationSymptomOf Relation = "symptom_of"
	// RelationPropagatesTo: the failure at From (downstream) reached To
	// (the component that called it).
	RelationPropagatesTo Relation = "propagates_to"
	// RelationCausedBy: From (a failing component) is failing because of
	// To — a connection, an auth relationship, a contract or a config key.
	RelationCausedBy Relation = "caused_by"
)

// Valid reports whether r is one of the three.
func (r Relation) Valid() bool {
	switch r {
	case RelationSymptomOf, RelationPropagatesTo, RelationCausedBy:
		return true
	}
	return false
}

// HypothesisStatus is where the walk left a hypothesis.
type HypothesisStatus string

const (
	// HypothesisOpen: nothing has spoken to it yet.
	HypothesisOpen HypothesisStatus = "open"
	// HypothesisRuledOut: a reading excluded it.
	HypothesisRuledOut HypothesisStatus = "ruled_out"
	// HypothesisSupported: a reading is consistent with it being the cause.
	HypothesisSupported HypothesisStatus = "supported"
	// HypothesisUnexplored: the walk could not test it — the probe was
	// refused, inconclusive, could not be placed where it needed to run,
	// or the budget ran out. A partial diagnosis is visibly partial
	// (Phase 32 field 12).
	HypothesisUnexplored HypothesisStatus = "unexplored"
)

// Valid reports whether s is one of the four.
func (s HypothesisStatus) Valid() bool {
	switch s {
	case HypothesisOpen, HypothesisRuledOut, HypothesisSupported, HypothesisUnexplored:
		return true
	}
	return false
}

// Hypothesis kinds — what ProbeManifest.Discriminates names. A probe that
// passes on a subject rules out hypotheses of the kinds it lists on that
// subject; the isolation walk chooses probes by this and nothing else.
const (
	// "A request entering at this component fails."
	HypothesisComponentFails = "component_fails"
	// "This component cannot reach that one" — DNS or TCP.
	HypothesisConnectionUnreachable = "connection_unreachable"
	// "This component cannot open a connection to its database."
	HypothesisDatabaseUnreachable = "database_unreachable"
	// "The certificate on this connection is not one a client accepts."
	HypothesisTLSInvalid = "tls_invalid"
	// "The token this component presents carries the wrong audience."
	HypothesisAuthAudience = "auth_audience_mismatch"
	// "The downstream refuses the credentials this component sends."
	HypothesisAuthRejected = "auth_rejected"
	// "A route the caller declares is not what the callee serves."
	HypothesisContractMismatch = "contract_mismatch"
	// "A config key the code requires is not set."
	HypothesisConfigMissing = "config_missing"
)

// HypothesisKinds is every kind, for validating a manifest's discriminates.
var HypothesisKinds = []string{
	HypothesisComponentFails, HypothesisConnectionUnreachable, HypothesisDatabaseUnreachable,
	HypothesisTLSInvalid, HypothesisAuthAudience, HypothesisAuthRejected,
	HypothesisContractMismatch, HypothesisConfigMissing,
}

// SymptomKind is how the symptom was named on the command line.
type SymptomKind string

const (
	SymptomSubject   SymptomKind = "subject"
	SymptomEndpoint  SymptomKind = "endpoint"
	SymptomComponent SymptomKind = "component"
)

// AttestationKind is how the symptom's occurrence is known (§2.8,
// amended 2026-11-04).
type AttestationKind string

const (
	// AttestedReproduced: the walk reproduced the symptom read-only — a
	// reading on the symptom's own subject failed.
	AttestedReproduced AttestationKind = "reproduced"
	// AttestedReported: the symptom is known only from the report it came
	// from. A write cannot be replayed read-only, so this is common.
	AttestedReported AttestationKind = "reported"
)

// Attestation says what establishes that the symptom happened at all —
// separately from the symptom_of edge, which says what ties it to its
// cause. A symptom that was only reported is never presented as
// reproduced: "reproduced" must cite a failing reading on the symptom's
// own subject, and the model refuses one that does not.
type Attestation struct {
	Kind AttestationKind `json:"kind"`
	// Reading is the id of the failing reading that reproduced it.
	Reading string `json:"reading,omitempty"`
	// ReportedBy names where a reported symptom came from.
	ReportedBy string `json:"reported_by,omitempty"`
}

// Symptom is what the investigation started from.
type Symptom struct {
	Kind        SymptomKind `json:"kind"`
	Subject     string      `json:"subject"`
	Description string      `json:"description,omitempty"`
	Source      string      `json:"source"`
	Attestation Attestation `json:"attestation"`
}

// Hypothesis is one candidate cause the model offered the walk.
type Hypothesis struct {
	ID      string           `json:"id"`
	Kind    string           `json:"kind"`
	Subject string           `json:"subject"`
	Status  HypothesisStatus `json:"status"`
	Reason  string           `json:"reason,omitempty"`
	// Readings are the ids of the readings that moved it off `open`.
	Readings []string `json:"readings,omitempty"`
}

// InvestigationReading is a reading as an investigation holds it: with an
// id the fault tree can cite. The Reading itself is unchanged — the id is
// the investigation's, not the probe's.
type InvestigationReading struct {
	ID      string  `json:"id"`
	Reading Reading `json:"reading"`
}

// FaultEdge is one link in the fault tree (§2.8).
//
// Build one with NewFaultEdge. A literal can be written in Go, but it is
// rejected by Validate, by Investigation.Validate and when decoded from
// JSON — every path by which an edge reaches a report.
type FaultEdge struct {
	FromSubject   string   `json:"from_subject"`
	ToSubject     string   `json:"to_subject"`
	Relation      Relation `json:"relation"`
	EstablishedBy []string `json:"established_by"`
}

// NewFaultEdge builds an edge, refusing one no reading established.
func NewFaultEdge(from, to string, relation Relation, establishedBy ...string) (FaultEdge, error) {
	edge := FaultEdge{
		FromSubject: from, ToSubject: to, Relation: relation,
		EstablishedBy: append([]string(nil), establishedBy...),
	}
	return edge, edge.Validate()
}

// Validate enforces the edge's own rules. Investigation.Validate adds the
// one an edge cannot check alone: that the readings it cites exist.
func (e FaultEdge) Validate() error {
	if len(e.EstablishedBy) == 0 {
		return fmt.Errorf(
			"a fault edge %s -[%s]-> %s cites no reading. An edge with no reading "+
				"behind it is a narrative, not a diagnosis (§2.8)",
			e.FromSubject, e.Relation, e.ToSubject)
	}
	for _, id := range e.EstablishedBy {
		if strings.TrimSpace(id) == "" {
			return fmt.Errorf("a fault edge %s -> %s cites an empty reading id",
				e.FromSubject, e.ToSubject)
		}
	}
	if !e.Relation.Valid() {
		return fmt.Errorf("a fault edge has unknown relation %q", e.Relation)
	}
	for _, subject := range []string{e.FromSubject, e.ToSubject} {
		if _, _, err := ParseSubject(subject); err != nil {
			return fmt.Errorf("fault edge subject %q is not a subject URI: %w", subject, err)
		}
	}
	if e.FromSubject == e.ToSubject {
		return fmt.Errorf("a fault edge cannot join %s to itself", e.FromSubject)
	}
	return nil
}

// UnmarshalJSON validates, so an edge read from a file is held to the same
// rule as one built in code.
func (e *FaultEdge) UnmarshalJSON(data []byte) error {
	type plain FaultEdge
	var decoded plain
	if err := json.Unmarshal(data, &decoded); err != nil {
		return err
	}
	edge := FaultEdge(decoded)
	if err := edge.Validate(); err != nil {
		return err
	}
	*e = edge
	return nil
}

// Criterion is one of the rubric's four booleans, with the reason it holds
// or does not.
type Criterion struct {
	Holds  bool   `json:"holds"`
	Reason string `json:"reason"`
}

// ConfidenceRubric is §2.9: four independent booleans, reported as a set,
// never collapsed into a number.
type ConfidenceRubric struct {
	// Reproduced: the failing probe was run again and failed again.
	Reproduced Criterion `json:"reproduced"`
	// Discriminated: at least one reading ruled out a competing hypothesis.
	Discriminated Criterion `json:"discriminated"`
	// Counterfactual: the same probe passes in a reference environment.
	Counterfactual Criterion `json:"counterfactual"`
	// Verified: after a change, the failing probe passes and nothing else
	// regressed. Always false until Phase 34 builds the verification loop.
	Verified Criterion `json:"verified"`
}

// Diagnosis is where the walk ended.
type Diagnosis struct {
	// RootSubject is the deepest subject the readings established. When
	// Complete is false it is the best the walk could localise to, and the
	// unexplored hypotheses say why it stopped there.
	RootSubject string           `json:"root_subject"`
	Statement   string           `json:"statement"`
	Confidence  ConfidenceRubric `json:"confidence"`
	Remediation string           `json:"remediation,omitempty"`
	Complete    bool             `json:"complete"`
}

// Investigation is §2.8's central object.
type Investigation struct {
	ID          string                 `json:"id"`
	OpenedAt    time.Time              `json:"opened_at"`
	ClosedAt    *time.Time             `json:"closed_at,omitempty"`
	Environment string                 `json:"environment"`
	Symptom     Symptom                `json:"symptom"`
	Hypotheses  []Hypothesis           `json:"hypotheses"`
	Readings    []InvestigationReading `json:"readings"`
	FaultTree   []FaultEdge            `json:"fault_tree"`
	Diagnosis   *Diagnosis             `json:"diagnosis,omitempty"`
}

// Validate enforces investigations.py's invariants.
func (inv Investigation) Validate() error {
	if strings.TrimSpace(inv.ID) == "" {
		return fmt.Errorf("an investigation needs an id")
	}
	if strings.TrimSpace(inv.Environment) == "" {
		return fmt.Errorf("investigation %s names no environment; readings are always about one", inv.ID)
	}
	if inv.ClosedAt != nil && inv.ClosedAt.Before(inv.OpenedAt) {
		return fmt.Errorf("investigation %s closes before it opened", inv.ID)
	}
	switch inv.Symptom.Kind {
	case SymptomSubject, SymptomEndpoint, SymptomComponent:
	default:
		return fmt.Errorf("investigation %s has unknown symptom kind %q", inv.ID, inv.Symptom.Kind)
	}
	if _, _, err := ParseSubject(inv.Symptom.Subject); err != nil {
		return fmt.Errorf("symptom subject %q is not a subject URI: %w", inv.Symptom.Subject, err)
	}

	if err := validateAttestation(inv); err != nil {
		return err
	}

	readings := make(map[string]bool, len(inv.Readings))
	for _, item := range inv.Readings {
		if strings.TrimSpace(item.ID) == "" {
			return fmt.Errorf("investigation %s holds a reading with no id", inv.ID)
		}
		if readings[item.ID] {
			return fmt.Errorf("investigation %s holds two readings with id %q", inv.ID, item.ID)
		}
		if err := item.Reading.Validate(); err != nil {
			return fmt.Errorf("reading %s: %w", item.ID, err)
		}
		readings[item.ID] = true
	}

	hypotheses := make(map[string]bool, len(inv.Hypotheses))
	for _, hypothesis := range inv.Hypotheses {
		if err := validateHypothesis(hypothesis, readings); err != nil {
			return err
		}
		if hypotheses[hypothesis.ID] {
			return fmt.Errorf("investigation %s has two hypotheses with id %q", inv.ID, hypothesis.ID)
		}
		hypotheses[hypothesis.ID] = true
	}

	for _, edge := range inv.FaultTree {
		if err := edge.Validate(); err != nil {
			return err
		}
		for _, id := range edge.EstablishedBy {
			if !readings[id] {
				return fmt.Errorf(
					"fault edge %s -[%s]-> %s cites reading %q, which this investigation "+
						"did not take", edge.FromSubject, edge.Relation, edge.ToSubject, id)
			}
		}
	}

	if inv.Diagnosis != nil {
		if err := validateDiagnosis(*inv.Diagnosis, inv.FaultTree); err != nil {
			return err
		}
	}
	return nil
}

func validateHypothesis(h Hypothesis, readings map[string]bool) error {
	if strings.TrimSpace(h.ID) == "" || strings.TrimSpace(h.Kind) == "" {
		return fmt.Errorf("a hypothesis needs an id and a kind (got %q, %q)", h.ID, h.Kind)
	}
	if !h.Status.Valid() {
		return fmt.Errorf("hypothesis %s has unknown status %q", h.ID, h.Status)
	}
	if _, _, err := ParseSubject(h.Subject); err != nil {
		return fmt.Errorf("hypothesis %s subject %q is not a subject URI: %w", h.ID, h.Subject, err)
	}
	switch h.Status {
	case HypothesisRuledOut, HypothesisSupported:
		// Moving a hypothesis is a claim; it cites what moved it.
		if len(h.Readings) == 0 {
			return fmt.Errorf(
				"hypothesis %s is %s with no reading behind it", h.ID, h.Status)
		}
	case HypothesisUnexplored:
		if strings.TrimSpace(h.Reason) == "" {
			return fmt.Errorf(
				"hypothesis %s is unexplored with no reason. A partial diagnosis "+
					"says why it is partial", h.ID)
		}
	}
	for _, id := range h.Readings {
		if !readings[id] {
			return fmt.Errorf("hypothesis %s cites reading %q, which this investigation did not take", h.ID, id)
		}
	}
	return nil
}

func validateDiagnosis(d Diagnosis, tree []FaultEdge) error {
	if _, _, err := ParseSubject(d.RootSubject); err != nil {
		return fmt.Errorf("diagnosis root %q is not a subject URI: %w", d.RootSubject, err)
	}
	if strings.TrimSpace(d.Statement) == "" {
		return fmt.Errorf("a diagnosis needs a statement")
	}
	for name, criterion := range map[string]Criterion{
		"reproduced": d.Confidence.Reproduced, "discriminated": d.Confidence.Discriminated,
		"counterfactual": d.Confidence.Counterfactual, "verified": d.Confidence.Verified,
	} {
		if strings.TrimSpace(criterion.Reason) == "" {
			return fmt.Errorf("confidence criterion %q gives no reason", name)
		}
	}
	if d.Confidence.Verified.Holds {
		return fmt.Errorf(
			"a diagnosis claims verified, and nothing can verify one before the " +
				"verification loop exists (Phase 34)")
	}
	if d.Complete {
		found := false
		for _, edge := range tree {
			if edge.ToSubject == d.RootSubject || edge.FromSubject == d.RootSubject {
				found = true
				break
			}
		}
		if !found {
			return fmt.Errorf(
				"a complete diagnosis names root %s, which no fault edge reaches. "+
					"A root the readings did not establish is a guess", d.RootSubject)
		}
	}
	return nil
}

func validateAttestation(inv Investigation) error {
	attestation := inv.Symptom.Attestation
	switch attestation.Kind {
	case AttestedReproduced:
		for _, item := range inv.Readings {
			if item.ID != attestation.Reading {
				continue
			}
			if item.Reading.Verdict != VerdictFail || item.Reading.Target != inv.Symptom.Subject {
				return fmt.Errorf(
					"the symptom is attested as reproduced by %s, which is not a failing reading "+
						"of %s. A symptom only reported is never presented as reproduced",
					attestation.Reading, inv.Symptom.Subject)
			}
			return nil
		}
		return fmt.Errorf("the symptom is attested as reproduced by %q, which this investigation did not take",
			attestation.Reading)
	case AttestedReported:
		if attestation.Reading != "" {
			return fmt.Errorf("a reported symptom cites reading %s; if a reading reproduced it, say reproduced",
				attestation.Reading)
		}
		if strings.TrimSpace(attestation.ReportedBy) == "" {
			return fmt.Errorf("a reported symptom must say where the report came from")
		}
		return nil
	}
	return fmt.Errorf("the symptom has unknown attestation %q", attestation.Kind)
}

// MarshalJSON writes an investigation's lists as lists, never null. A walk
// that establishes no edge leaves FaultTree nil, which encoding/json writes
// as `null` — and the Python model, the one POST /investigations validates
// with, rejects null where it expects a list. Found by the API's round trip
// on a real partial investigation (Phase 32 part 2), the same class of
// defect as part 1's `capabilities: null`.
func (inv Investigation) MarshalJSON() ([]byte, error) {
	type plain Investigation
	normalised := plain(inv)
	if normalised.Hypotheses == nil {
		normalised.Hypotheses = []Hypothesis{}
	}
	if normalised.Readings == nil {
		normalised.Readings = []InvestigationReading{}
	}
	if normalised.FaultTree == nil {
		normalised.FaultTree = []FaultEdge{}
	}
	return json.Marshal(normalised)
}
