package model

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
	"time"
)

// Verification — Phase 34: whether a change fixed what an investigation
// found.
//
// The Go half of shared/culprit_model/verifications.py, held to it by
// shared/tests/verification_conformance.json. `culprit verify` builds one.
// A verification is its own append-only record pointing at an
// investigation; the investigation is never edited ("How Phase 34 is
// run", 2026-11-10).
//
// # The verdict is a pure function of the record
//
// A verification holds every reading re-run (twice), the changes named,
// whether there is a capture of the environment before and after, and the
// differences between them. Judge computes the verdict and the three
// clause flags from that, and Validate refuses a record whose verdict or
// flags say anything else. So a `verified` verification cannot be built —
// in code, from a file, or by encoding one — unless all three clauses
// hold:
//
//  1. every reading that failed passes, on both runs;
//  2. every reading that passed still passes;
//  3. every difference between before and after is explained by a change
//     named — which needs a change named and a capture before.
//
// Re-running only the failing probe once is confidence theatre: caching,
// intermittency and an unrelated change all produce a pass.

// VerificationVerdict is one of five, a closed set.
type VerificationVerdict string

const (
	// VerificationVerified: all three clauses hold.
	VerificationVerified VerificationVerdict = "verified"
	// VerificationNotResolved: a reading that failed still fails.
	VerificationNotResolved VerificationVerdict = "not_resolved"
	// VerificationRegressed: the failing readings pass, but one that
	// passed now fails.
	VerificationRegressed VerificationVerdict = "regressed"
	// VerificationChangedUnderneath: the failing readings pass, but the
	// environment changed in a way the named change does not explain.
	VerificationChangedUnderneath VerificationVerdict = "changed_underneath"
	// VerificationInconclusive: anything else — a probe refused or
	// inconclusive now, a result that flips between the two runs, no
	// change named, or no record of the environment before.
	VerificationInconclusive VerificationVerdict = "inconclusive"
)

// VerificationVerdicts is the closed set, in the fixture's order.
var VerificationVerdicts = []VerificationVerdict{
	VerificationVerified, VerificationNotResolved, VerificationRegressed,
	VerificationChangedUnderneath, VerificationInconclusive,
}

// ChangeKind is what kind of thing was applied.
type ChangeKind string

const (
	ChangeImage  ChangeKind = "image"
	ChangeConfig ChangeKind = "config"
	ChangeCommit ChangeKind = "commit"
)

// ChangeKinds is every kind, in the fixture's order.
var ChangeKinds = []ChangeKind{ChangeImage, ChangeConfig, ChangeCommit}

var commitRef = regexp.MustCompile(`^[0-9a-f]{7,40}$`)

// Change is what was applied: an image for a component, a config key for
// a component, or a commit.
type Change struct {
	Kind ChangeKind `json:"kind"`
	// Subject is image:<component> or config:<component>/<key>.
	Subject string `json:"subject,omitempty"`
	// Ref is a commit id, 7 to 40 lowercase hex characters.
	Ref string `json:"ref,omitempty"`
}

// Validate refuses a change that does not name one thing of its kind.
func (c Change) Validate() error {
	switch c.Kind {
	case ChangeCommit:
		if c.Subject != "" {
			return fmt.Errorf("a commit change names a ref, not a subject")
		}
		if !commitRef.MatchString(c.Ref) {
			return fmt.Errorf("commit ref %q is not a commit id (7-40 hex characters)", c.Ref)
		}
		return nil
	case ChangeImage, ChangeConfig:
		if c.Ref != "" {
			return fmt.Errorf("%s change names a subject, not a ref", article(c.Kind))
		}
		want := KindImage
		if c.Kind == ChangeConfig {
			want = KindConfig
		}
		kind, _, err := ParseSubject(c.Subject)
		if err != nil || kind != want {
			return fmt.Errorf("%s change names a %s: subject, got %q", article(c.Kind), want, c.Subject)
		}
		return nil
	}
	return fmt.Errorf("unknown change kind %q (want image, config or commit)", c.Kind)
}

func article(kind ChangeKind) string {
	if kind == ChangeImage {
		return "an image"
	}
	return "a " + string(kind)
}

// Label is how a difference cites the change that explains it.
func (c Change) Label() string {
	if c.Kind == ChangeCommit {
		return "commit:" + c.Ref
	}
	return c.Subject
}

// Touches reports whether a difference on subject is one this change
// explains. A config key explains that key. An image explains that
// component's image and its packages, which ship in it. A commit explains
// nothing a capture records: captures hold no commits.
func (c Change) Touches(subject string) bool {
	switch c.Kind {
	case ChangeConfig:
		return subject == c.Subject
	case ChangeImage:
		_, changed, err := ParseSubject(c.Subject)
		if err != nil {
			return false
		}
		kind, target, err := ParseSubject(subject)
		if err != nil {
			return false
		}
		return (kind == KindImage || kind == KindDep) && target["component"] == changed["component"]
	}
	return false
}

// Rerun is one of the investigation's readings, measured again twice.
type Rerun struct {
	ReadingID string `json:"reading_id"`
	// Was is the verdict the investigation recorded.
	Was         Verdict    `json:"was"`
	ProbeID     string     `json:"probe_id"`
	Target      string     `json:"target"`
	Environment string     `json:"environment"`
	Runs        [2]Reading `json:"runs"`
}

// Now is the verdict both runs agree on, if it is pass or fail; "" for a
// flip, a refusal or an inconclusive run.
func (r Rerun) Now() Verdict {
	first, second := r.Runs[0].Verdict, r.Runs[1].Verdict
	if first == second && (first == VerdictPass || first == VerdictFail) {
		return first
	}
	return ""
}

// UnmarshalJSON insists on exactly two runs: a fixed-size array would
// otherwise take one run and leave the second empty.
func (r *Rerun) UnmarshalJSON(data []byte) error {
	type plain struct {
		ReadingID   string    `json:"reading_id"`
		Was         Verdict   `json:"was"`
		ProbeID     string    `json:"probe_id"`
		Target      string    `json:"target"`
		Environment string    `json:"environment"`
		Runs        []Reading `json:"runs"`
	}
	var decoded plain
	if err := json.Unmarshal(data, &decoded); err != nil {
		return err
	}
	if len(decoded.Runs) != 2 {
		return fmt.Errorf("reading %s is re-run %d time(s); a verification runs each twice",
			decoded.ReadingID, len(decoded.Runs))
	}
	*r = Rerun{ReadingID: decoded.ReadingID, Was: decoded.Was, ProbeID: decoded.ProbeID,
		Target: decoded.Target, Environment: decoded.Environment,
		Runs: [2]Reading{decoded.Runs[0], decoded.Runs[1]}}
	return nil
}

func (r Rerun) validate() error {
	if strings.TrimSpace(r.ReadingID) == "" || strings.TrimSpace(r.ProbeID) == "" ||
		strings.TrimSpace(r.Environment) == "" {
		return fmt.Errorf("a re-run needs a reading id, a probe and an environment")
	}
	if !r.Was.Valid() {
		return fmt.Errorf("reading %s was %q, which is not a verdict", r.ReadingID, r.Was)
	}
	for _, run := range r.Runs {
		if err := run.Validate(); err != nil {
			return fmt.Errorf("a re-run of %s: %w", r.ReadingID, err)
		}
		if run.ProbeID != r.ProbeID || run.Target != r.Target || run.Environment != r.Environment {
			return fmt.Errorf("a re-run of %s measured %s on %s in %s, not %s on %s in %s",
				r.ReadingID, run.ProbeID, run.Target, run.Environment, r.ProbeID, r.Target, r.Environment)
		}
	}
	return nil
}

// Difference is one question the capture before and the capture after
// answer differently. Subject and predicate only: never a value.
type Difference struct {
	Subject   string `json:"subject"`
	Predicate string `json:"predicate"`
	// ExplainedBy is the label of the first named change that touches the
	// subject, or nil when none does.
	ExplainedBy *string `json:"explained_by"`
}

// Explain fills ExplainedBy from the changes named: the first that
// touches the difference's subject.
func Explain(difference Difference, changes []Change) Difference {
	difference.ExplainedBy = nil
	for _, change := range changes {
		if change.Touches(difference.Subject) {
			label := change.Label()
			difference.ExplainedBy = &label
			break
		}
	}
	return difference
}

// Judgement is what the record supports.
type Judgement struct {
	FailingNowPasses bool
	NoRegressions    bool
	ChangesExplained bool
	Verdict          VerificationVerdict
}

// Judge is the verdict rules, in order. verifications.py's judge() is the
// same function.
func Judge(reran []Rerun, changes []Change, beforeCapture, afterCapture *string, differences []Difference) Judgement {
	var failed, passed []Rerun
	for _, rerun := range reran {
		switch rerun.Was {
		case VerdictFail:
			failed = append(failed, rerun)
		case VerdictPass:
			passed = append(passed, rerun)
		}
	}
	all := func(set []Rerun, verdict Verdict) bool {
		for _, rerun := range set {
			if rerun.Now() != verdict {
				return false
			}
		}
		return true
	}
	any := func(set []Rerun, verdict Verdict) bool {
		for _, rerun := range set {
			if rerun.Now() == verdict {
				return true
			}
		}
		return false
	}
	judged := Judgement{
		FailingNowPasses: len(failed) > 0 && all(failed, VerdictPass),
		NoRegressions:    all(passed, VerdictPass),
	}
	explained := true
	for _, difference := range differences {
		if difference.ExplainedBy == nil {
			explained = false
		}
	}
	recorded := beforeCapture != nil && afterCapture != nil
	judged.ChangesExplained = len(changes) > 0 && recorded && explained

	switch {
	case any(failed, VerdictFail):
		judged.Verdict = VerificationNotResolved
	case judged.FailingNowPasses && any(passed, VerdictFail):
		judged.Verdict = VerificationRegressed
	case !judged.FailingNowPasses || !judged.NoRegressions:
		judged.Verdict = VerificationInconclusive
	case !all(reran, VerdictPass):
		// A reading the investigation could not answer is unanswered now,
		// or now fails: either way the path is not shown clear.
		judged.Verdict = VerificationInconclusive
	case len(changes) == 0 || !recorded:
		judged.Verdict = VerificationInconclusive
	case !judged.ChangesExplained:
		judged.Verdict = VerificationChangedUnderneath
	default:
		judged.Verdict = VerificationVerified
	}
	return judged
}

// Verification is Phase 34 field 7, as decided 2026-11-10.
type Verification struct {
	ID              string   `json:"id"`
	InvestigationID string   `json:"investigation_id"`
	Environment     string   `json:"environment"`
	AppliedChange   []Change `json:"applied_change"`
	Reran           []Rerun  `json:"reran"`
	// BeforeCapture is the capture id of the environment as `culprit
	// diagnose` found it, or nil when the investigation has no record of
	// before.
	BeforeCapture    *string             `json:"before_capture"`
	AfterCapture     *string             `json:"after_capture"`
	Differences      []Difference        `json:"differences"`
	FailingNowPasses bool                `json:"failing_now_passes"`
	NoRegressions    bool                `json:"no_regressions"`
	ChangesExplained bool                `json:"changes_explained"`
	Verdict          VerificationVerdict `json:"verdict"`
	Reason           string              `json:"reason"`
	VerifiedAt       time.Time           `json:"verified_at"`
}

// NewVerification builds a verification from its record, judging it: the
// caller supplies what was measured and compared, never the verdict.
// Reason is filled by describe, which is handed the judgement.
func NewVerification(id, investigationID, environment string, changes []Change, reran []Rerun,
	beforeCapture, afterCapture *string, differences []Difference, verifiedAt time.Time,
	describe func(Judgement) string,
) (Verification, error) {
	explained := make([]Difference, len(differences))
	for index, difference := range differences {
		explained[index] = Explain(difference, changes)
	}
	judged := Judge(reran, changes, beforeCapture, afterCapture, explained)
	verification := Verification{
		ID: id, InvestigationID: investigationID, Environment: environment,
		AppliedChange: append([]Change{}, changes...), Reran: append([]Rerun{}, reran...),
		BeforeCapture: beforeCapture, AfterCapture: afterCapture, Differences: explained,
		FailingNowPasses: judged.FailingNowPasses, NoRegressions: judged.NoRegressions,
		ChangesExplained: judged.ChangesExplained, Verdict: judged.Verdict,
		Reason: describe(judged), VerifiedAt: verifiedAt,
	}
	return verification, verification.Validate()
}

// Validate enforces verifications.py's rules, the verdict among them.
func (v Verification) Validate() error {
	if strings.TrimSpace(v.ID) == "" || strings.TrimSpace(v.InvestigationID) == "" {
		return fmt.Errorf("a verification needs an id and the investigation it verifies")
	}
	if strings.TrimSpace(v.Environment) == "" {
		return fmt.Errorf("verification %s names no environment", v.ID)
	}
	if strings.TrimSpace(v.Reason) == "" {
		return fmt.Errorf("a verification gives no reason for its verdict")
	}
	known := false
	for _, verdict := range VerificationVerdicts {
		known = known || verdict == v.Verdict
	}
	if !known {
		return fmt.Errorf("verification %s has unknown verdict %q", v.ID, v.Verdict)
	}
	for _, change := range v.AppliedChange {
		if err := change.Validate(); err != nil {
			return err
		}
	}
	if len(v.Reran) == 0 {
		return fmt.Errorf("verification %s re-runs nothing", v.ID)
	}
	seen := map[string]bool{}
	for _, rerun := range v.Reran {
		if err := rerun.validate(); err != nil {
			return err
		}
		if seen[rerun.ReadingID] {
			return fmt.Errorf("verification %s re-runs reading %s twice over", v.ID, rerun.ReadingID)
		}
		seen[rerun.ReadingID] = true
		if rerun.Environment != v.Environment {
			return fmt.Errorf("reading %s was re-run in %s, not %s", rerun.ReadingID, rerun.Environment, v.Environment)
		}
	}
	if len(v.Differences) > 0 && (v.BeforeCapture == nil || v.AfterCapture == nil) {
		return fmt.Errorf("a difference is recorded with no capture before and after it")
	}
	for _, difference := range v.Differences {
		if _, _, err := ParseSubject(difference.Subject); err != nil {
			return fmt.Errorf("difference subject %q is not a subject URI: %w", difference.Subject, err)
		}
		if strings.TrimSpace(difference.Predicate) == "" {
			return fmt.Errorf("the difference on %s names no predicate", difference.Subject)
		}
		want := Explain(difference, v.AppliedChange).ExplainedBy
		if !sameLabel(difference.ExplainedBy, want) {
			return fmt.Errorf("the difference on %s says it is explained by %s; the changes named say %s",
				difference.Subject, labelOrNone(difference.ExplainedBy), labelOrNone(want))
		}
	}

	judged := Judge(v.Reran, v.AppliedChange, v.BeforeCapture, v.AfterCapture, v.Differences)
	for name, pair := range map[string][2]bool{
		"failing_now_passes": {v.FailingNowPasses, judged.FailingNowPasses},
		"no_regressions":     {v.NoRegressions, judged.NoRegressions},
		"changes_explained":  {v.ChangesExplained, judged.ChangesExplained},
	} {
		if pair[0] != pair[1] {
			return fmt.Errorf("verification %s says %s=%v; its readings say %v", v.ID, name, pair[0], pair[1])
		}
	}
	if v.Verdict != judged.Verdict {
		return fmt.Errorf("verification %s says %s; its record supports %s", v.ID, v.Verdict, judged.Verdict)
	}
	return nil
}

func sameLabel(left, right *string) bool {
	if left == nil || right == nil {
		return left == right
	}
	return *left == *right
}

func labelOrNone(label *string) string {
	if label == nil {
		return "nothing"
	}
	return *label
}

// UnmarshalJSON validates, so a verification read from a file is held to
// the same rules as one built in code.
func (v *Verification) UnmarshalJSON(data []byte) error {
	type plain Verification
	var decoded plain
	if err := json.Unmarshal(data, &decoded); err != nil {
		return err
	}
	verification := Verification(decoded)
	if err := verification.Validate(); err != nil {
		return err
	}
	*v = verification
	return nil
}

// MarshalJSON refuses to write a verification its record does not
// support, and writes lists as lists, never null — the Python model
// rejects null where it expects a list.
func (v Verification) MarshalJSON() ([]byte, error) {
	if err := v.Validate(); err != nil {
		return nil, err
	}
	type plain Verification
	normalised := plain(v)
	if normalised.AppliedChange == nil {
		normalised.AppliedChange = []Change{}
	}
	if normalised.Differences == nil {
		normalised.Differences = []Difference{}
	}
	return json.Marshal(normalised)
}
