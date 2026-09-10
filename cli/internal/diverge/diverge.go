// Package diverge is the comparator (Phase 29, D7).
//
// **It knows nothing about HTTP, SQL or auth.** It groups facts by
// subject and predicate, compares their canonicalised values, and emits
// a Divergence when two sources disagree. Adding a new class of
// detectable fault means adding an extractor, never touching this file.
// That is D7, and it is the difference between a product that grows and
// a pile of special cases.
//
// # The two rules
//
// **Conflict.** Two facts share a subject and a predicate and their
// canonical values differ. This is the easy half and it covers, for
// instance, a committed `openapi.json` whose response codes disagree
// with the running app's route table.
//
// **Absence.** One source asserts a subject that another source, which
// demonstrably had *complete* coverage of that kind of subject for that
// component, does not assert at all. This is the half that finds "the
// frontend calls a route the backend does not expose" — and it is the
// half that can produce false positives if it is careless, so it is not
// careless:
//
//   - Absence is only ever judged against a **reference source**: the
//     highest-confidence source that covered (component, subject kind).
//     A rank-90 route table read out of the running application really
//     is the complete list of that app's routes. A rank-40 scrape of
//     call sites is not a complete list of anything, and is never used
//     as a reference.
//   - If nothing of reference quality covered that (component, subject
//     kind), **no absence is reported at all**. That is what protects
//     against concluding "it is not there" from "we did not look", which
//     is the single most damaging thing this tool could do — a component
//     whose route table could not be read produces skips in the report,
//     not findings.
//
// An earlier version had a second guard: if *any* skip existed for the
// want, absence was suppressed for that component. It was removed
// because it was both redundant and wrong. Redundant, because a source
// at rank 80 or above is by definition a complete description of what it
// covers, so the reference requirement already carries the completeness
// argument. Wrong, because skips are recorded per `(component, want)`
// and several readers share one want: on the demo repository, the
// compose reader's honest "no docker-compose file found" suppressed
// every config-key absence finding for that component, including a key
// the code reads and `.env.example` does not declare. A guard that
// silently disables a whole class of check because an unrelated reader
// had nothing to say is worse than no guard, because it fails quietly.
//
// Acceptance criterion 6 — zero findings on a fixture known to be
// correct — is the criterion these two guards exist to satisfy, and it
// is the one the plan calls the single most important in the phase.
package diverge

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Options configure one comparison run.
type Options struct {
	// Now stamps `first_seen_at`. Injected so output is reproducible.
	Now time.Time
}

// Result is everything one comparison produced.
type Result struct {
	Divergences []model.Divergence
	// Unverifiable is the §0.1 corollary: subjects nothing could ever
	// cross-check, because only one source knows about them. Reported by
	// `culprit check --unverifiable`, and deliberately *not* mixed in
	// with divergences — "nothing could catch a mistake here" is not a
	// finding that something is wrong.
	Unverifiable []Unverifiable
}

// Unverifiable is one subject with a single source of truth.
type Unverifiable struct {
	Subject string `json:"subject"`
	// Source is the lone extractor that knows about it.
	Source string `json:"source"`
	// Artefact and Locator point at where it came from, so the report
	// can tell the reader which file to add a test or a spec to.
	Artefact string `json:"artefact,omitempty"`
	Locator  string `json:"locator,omitempty"`
	Reason   string `json:"reason"`
}

// referenceRanks are the confidence ranks a source must reach before its
// silence is treated as evidence of absence.
//
// 80 is the line: §2.4's rank 80 is "a committed machine-readable spec"
// — an `openapi.json`, a migration file — and rank 90 is the running
// application's own table. Both are *complete descriptions* of something.
// Rank 60 and below are extractions of fragments (a decorator here, a
// call site there); their silence means nothing at all, and treating it
// as evidence would invent a finding for every route a scraper happened
// to miss.
const referenceRank = 80

// enumerates reports whether a fact's source is the kind that *lists*
// things, and so whose silence about a subject means something.
//
// Rank is not enough on its own, and the fault corpus proved it in the
// most direct way available. A `culprit.yaml` invariant is rank 100 —
// the top of §2.4, above every extractor — so it became the reference
// set for its component, and the application's real route table was
// reported as two routes "absent" from a set of one hand-written line.
//
// The confusion is between two different properties. Rank says how much
// to *believe* a source. Absence needs a different property entirely:
// whether the source was surveying a surface or pointing at one thing. A
// developer assertion is always the second. It says "this route must
// exist"; it never says "and these are all of them", and no amount of
// trustworthiness turns the first sentence into the second.
func enumerates(fact model.Fact) bool {
	return fact.Provenance.SourceKind != model.SourceAssertion
}

// Compare produces findings from one capture.
func Compare(bundle model.CaptureBundle, options Options) Result {
	now := options.Now
	if now.IsZero() {
		now = time.Now().UTC()
	}

	groups := groupBySubjectPredicate(bundle.Facts)
	coverage := buildCoverage(bundle)

	result := Result{Divergences: []model.Divergence{}, Unverifiable: []Unverifiable{}}
	result.Divergences = append(result.Divergences, conflicts(groups, now)...)
	result.Divergences = append(result.Divergences, absences(bundle, coverage, now)...)
	result.Unverifiable = unverifiable(bundle, groups)

	sortDivergences(result.Divergences)
	sort.Slice(result.Unverifiable, func(i, j int) bool {
		return result.Unverifiable[i].Subject < result.Unverifiable[j].Subject
	})
	return result
}

// --- rule one: two sources, same claim, different answers -------------

type key struct {
	subject   string
	predicate string
}

func groupBySubjectPredicate(facts []model.Fact) map[key][]model.Fact {
	groups := map[key][]model.Fact{}
	for _, fact := range facts {
		groupKey := key{subject: fact.Subject, predicate: fact.Predicate}
		groups[groupKey] = append(groups[groupKey], fact)
	}
	return groups
}

// conflicts finds groups whose members do not agree.
//
// Compared *pairwise against the highest-ranked member*, not
// all-against-all. Three sources disagreeing produce two findings
// ("A disagrees with the reference", "B disagrees with the reference"),
// not three; the reader wants to know what to fix, and the
// highest-confidence source is the best available answer to that.
// §2.4's rule holds either way: rank orders the report, it never
// silently discards the losing source.
func conflicts(groups map[key][]model.Fact, now time.Time) []model.Divergence {
	var found []model.Divergence
	for groupKey, facts := range sortedGroups(groups) {
		_ = groupKey
		if len(facts) < 2 {
			continue
		}
		ordered := byRankThenExtractor(facts)
		reference := ordered[0]
		for _, other := range ordered[1:] {
			if sameSource(reference, other) {
				// The same extractor reading the same file twice is a
				// duplicate, not a disagreement.
				continue
			}
			if model.ValuesEqual(reference.Value, other.Value) &&
				shapesEqual(reference.ValueShape, other.ValueShape) {
				continue
			}
			found = append(found, model.Divergence{
				Kind:      model.KindIntentConflict,
				Subject:   reference.Subject,
				Predicate: reference.Predicate,
				Left:      reference,
				Right:     other,
				Severity:  model.SeverityUnknown,
				Explanation: fmt.Sprintf(
					"%s and %s disagree about %s",
					sourceLabel(reference), sourceLabel(other), reference.Predicate),
				Status:      model.StatusOpen,
				FirstSeenAt: now,
			})
		}
	}
	return found
}

// --- rule two: one source says it exists, the reference does not ------

// coverage records which sources produced a complete picture of which
// (component, subject kind), and which were skipped.
type coverage struct {
	// reference[componentKind] is the highest-ranked complete source for
	// that pair, and the set of subjects it asserted.
	reference map[componentKind]*referenceSet
	// skipped[componentWant] means extraction of that want did not
	// happen for that component, so absence must not be inferred.
	skipped map[componentWant]string
}

type componentKind struct {
	component string
	kind      model.SubjectKind
}

type componentWant struct {
	component string
	want      string
}

type referenceSet struct {
	extractor string
	rank      int
	subjects  map[string]bool
	sample    model.Fact
}

// wantForKind maps a subject kind to the `want` whose skip would mean
// "we did not look". Kinds with no entry never produce absence findings.
var wantForKind = map[model.SubjectKind]string{
	model.KindHTTP:   string(model.WantHTTPRoutes),
	model.KindConfig: string(model.WantConfigKeys),
	model.KindSchema: string(model.WantDBSchema),
	model.KindDep:    string(model.WantDependencies),
}

// existencePredicates are the predicates that assert "this thing is
// there". Only these define a reference set, and only these are checked
// for absence — a `nullable` fact about a column says nothing about
// whether the column exists elsewhere.
var existencePredicates = map[string]bool{
	model.PredicateExists: true,
	model.PredicateCalls:  true,
	// A config key read in code is a claim that the key is expected to
	// exist — that is precisely acceptance criterion 3.
	model.PredicateReadBy:  true,
	model.PredicateColumns: true,
	// A test exercising a route is a claim the route is there — which is
	// how "a test calls an endpoint the application does not serve"
	// becomes a finding. At rank 50 it can never be a reference set, so
	// it is only ever the side being checked.
	model.PredicateExercisedByTest: true,
}

func buildCoverage(bundle model.CaptureBundle) coverage {
	result := coverage{
		reference: map[componentKind]*referenceSet{},
		skipped:   map[componentWant]string{},
	}
	for _, skip := range bundle.Skipped {
		if skip.Component == "" {
			continue
		}
		result.skipped[componentWant{component: skip.Component, want: skip.Want}] = skip.Reason
		// A `*` skip means the whole component was not extracted.
		if skip.Want == "*" {
			for _, want := range model.AllWants {
				result.skipped[componentWant{skip.Component, string(want)}] = skip.Reason
			}
		}
	}

	for _, fact := range bundle.Facts {
		if !existencePredicates[fact.Predicate] {
			continue
		}
		if fact.Provenance.ConfidenceRank < referenceRank {
			continue
		}
		if !enumerates(fact) {
			continue
		}
		kind, parts, err := model.ParseSubject(fact.Subject)
		if err != nil {
			continue
		}
		component := parts["component"]
		if component == "" {
			continue
		}
		pair := componentKind{component: component, kind: kind}
		existing := result.reference[pair]
		if existing == nil || fact.Provenance.ConfidenceRank > existing.rank {
			result.reference[pair] = &referenceSet{
				extractor: fact.Provenance.Extractor,
				rank:      fact.Provenance.ConfidenceRank,
				subjects:  map[string]bool{fact.Subject: true},
				sample:    fact,
			}
			continue
		}
		if fact.Provenance.ConfidenceRank == existing.rank &&
			fact.Provenance.Extractor == existing.extractor {
			existing.subjects[fact.Subject] = true
		}
	}
	return result
}

// absences finds subjects one source claims and the reference does not.
func absences(bundle model.CaptureBundle, cover coverage, now time.Time) []model.Divergence {
	var found []model.Divergence
	seen := map[string]bool{}

	facts := append([]model.Fact(nil), bundle.Facts...)
	sort.SliceStable(facts, func(i, j int) bool { return facts[i].Subject < facts[j].Subject })

	for _, fact := range facts {
		if !existencePredicates[fact.Predicate] {
			continue
		}
		kind, parts, err := model.ParseSubject(fact.Subject)
		if err != nil {
			continue
		}
		if _, comparable := wantForKind[kind]; !comparable {
			continue
		}
		component := parts["component"]
		if component == "" {
			continue
		}

		reference := cover.reference[componentKind{component: component, kind: kind}]
		if reference == nil {
			// Nothing authoritative described this component's subjects
			// of this kind, so there is no set to be absent from.
			continue
		}
		if fact.Provenance.Extractor == reference.extractor {
			continue
		}
		if reference.subjects[fact.Subject] {
			continue
		}
		// Keyed by predicate too. Without it, one extractor claiming a
		// subject under two existence predicates — `exists` from a route
		// table and `exercised_by_test` from the suite, say — reported
		// only the first, and the second silently disappeared.
		key := fact.Subject + "|" + fact.Predicate + "|" + fact.Provenance.Extractor
		if seen[key] {
			continue
		}
		seen[key] = true

		found = append(found, model.Divergence{
			Kind:      model.KindIntentConflict,
			Subject:   fact.Subject,
			Predicate: fact.Predicate,
			Left:      fact,
			Right:     absentFrom(reference, fact),
			Severity:  model.SeverityUnknown,
			Explanation: fmt.Sprintf(
				"%s refers to %s, which %s does not describe",
				sourceLabel(fact), describeSubject(kind, parts), sourceLabel(reference.sample)),
			Status:      model.StatusOpen,
			FirstSeenAt: now,
		})
	}
	return found
}

// absentFrom builds the other side of an absence finding: the reference
// source, saying this subject is not in its set.
//
// Synthesised rather than reusing a sample fact from the reference, and
// the reason is a contract, not a nicety. `Divergence` in
// `shared/culprit_model/facts.py` validates that both sides name the
// same subject and predicate — reasonably, since a divergence is
// two answers to one question. A sample fact from the reference source
// is about some *other* route or column, so posting one would be
// rejected at the API boundary, and the Go and Python models would have
// silently diverged about what a Divergence is.
//
// It is also the more truthful object. A complete source that does not
// list a subject *is* asserting something about it: that it is not
// there. The synthesised fact says exactly that, with the reference's
// own provenance, so the report can tell the reader which file to open
// to see the absence for themselves.
func absentFrom(reference *referenceSet, claim model.Fact) model.Fact {
	provenance := reference.sample.Provenance
	// The locator is dropped deliberately. The sample fact points at some
	// *other* route or column in the reference — the first one that
	// happened to sort into place — and carrying its line number over
	// would have the report tell the reader to go and look at a line
	// that has nothing to do with the finding. The artefact is right and
	// is what matters: "this file does not mention it".
	provenance.Locator = ""
	return model.Fact{
		Plane:      claim.Plane,
		Subject:    claim.Subject,
		Predicate:  claim.Predicate,
		Value:      false,
		Provenance: provenance,
		CapturedAt: reference.sample.CapturedAt,
		CaptureID:  reference.sample.CaptureID,
	}
}

// --- the §0.1 corollary: what nothing could ever check ----------------

// unverifiable reports subjects with exactly one source.
//
// Not a defect — a *coverage* statement. "Here are the 34 places in your
// system where nothing could ever catch a mistake" is the honest,
// shippable answer to Tier 3, which §0.1 is explicit that no tool can
// solve. It is kept out of the divergence list because a place nobody
// checks is not a place something is wrong.
func unverifiable(bundle model.CaptureBundle, groups map[key][]model.Fact) []Unverifiable {
	sources := map[string]map[string]bool{}
	sample := map[string]model.Fact{}
	for _, fact := range bundle.Facts {
		if sources[fact.Subject] == nil {
			sources[fact.Subject] = map[string]bool{}
			sample[fact.Subject] = fact
		}
		sources[fact.Subject][fact.Provenance.Extractor] = true
	}

	var found []Unverifiable
	for subject, extractors := range sources {
		if len(extractors) > 1 {
			continue
		}
		fact := sample[subject]
		found = append(found, Unverifiable{
			Subject:  subject,
			Source:   fact.Provenance.Extractor,
			Artefact: fact.Provenance.Artefact,
			Locator:  fact.Provenance.Locator,
			Reason: fmt.Sprintf(
				"only %s describes this, so no second source could contradict it",
				fact.Provenance.Extractor),
		})
	}
	return found
}

// --- helpers ----------------------------------------------------------

func sortedGroups(groups map[key][]model.Fact) map[key][]model.Fact {
	// Go randomises map iteration; every consumer of this sorts its
	// output, so returning the map is safe. Kept as a named function so
	// the reason is written down rather than rediscovered.
	return groups
}

func byRankThenExtractor(facts []model.Fact) []model.Fact {
	ordered := append([]model.Fact(nil), facts...)
	sort.SliceStable(ordered, func(i, j int) bool {
		if ordered[i].Provenance.ConfidenceRank != ordered[j].Provenance.ConfidenceRank {
			return ordered[i].Provenance.ConfidenceRank > ordered[j].Provenance.ConfidenceRank
		}
		if ordered[i].Provenance.Extractor != ordered[j].Provenance.Extractor {
			return ordered[i].Provenance.Extractor < ordered[j].Provenance.Extractor
		}
		return ordered[i].Provenance.Artefact < ordered[j].Provenance.Artefact
	})
	return ordered
}

// sameSource is extractor *and* artefact, not extractor alone.
//
// Extractor alone was the first attempt and it silently swallowed
// acceptance criterion 2. One extractor legitimately reads several
// independent descriptions of the same thing: `culprit-extract-python`
// reports the columns the ORM declares *and* the columns the migration
// chain creates, and an unmigrated column is precisely those two
// disagreeing. Keying on the extractor made that finding impossible, and
// the fault corpus is what caught it — the comparator's own unit tests
// would not have, because they were written against the same wrong idea.
//
// The duplicate case the guard exists for is narrower than it looked: an
// extractor emitting the same predicate twice from one file. Different
// artefacts are different sources, whatever read them, and two sources
// that disagree is the entire product.
func sameSource(left, right model.Fact) bool {
	return left.Provenance.Extractor == right.Provenance.Extractor &&
		left.Provenance.Artefact == right.Provenance.Artefact
}

func shapesEqual(left, right *model.ValueShape) bool {
	if left == nil || right == nil {
		return left == right
	}
	return *left == *right
}

func sourceLabel(fact model.Fact) string {
	if fact.Provenance.Artefact != "" {
		return fact.Provenance.Artefact
	}
	return fact.Provenance.Extractor
}

func describeSubject(kind model.SubjectKind, parts model.Parts) string {
	switch kind {
	case model.KindHTTP:
		return strings.TrimSpace(parts["method"] + " " + parts["path"])
	case model.KindConfig:
		return parts["key"]
	case model.KindSchema:
		return strings.Trim(parts["namespace"]+"."+parts["table"]+"."+parts["column"], ".")
	case model.KindDep:
		return parts["dependency"]
	default:
		return parts["name"]
	}
}

func sortDivergences(divergences []model.Divergence) {
	sort.SliceStable(divergences, func(i, j int) bool {
		left, right := divergences[i], divergences[j]
		if left.Severity.Rank() != right.Severity.Rank() {
			return left.Severity.Rank() > right.Severity.Rank()
		}
		if left.Subject != right.Subject {
			return left.Subject < right.Subject
		}
		if left.Predicate != right.Predicate {
			return left.Predicate < right.Predicate
		}
		return left.Right.Provenance.Extractor < right.Right.Provenance.Extractor
	})
}
