package diverge

import (
	"fmt"
	"sort"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Comparison across scopes (Phase 30): INTENT against each environment,
// and each environment against every other. See CompareAll's comment for
// the rules; this file is only their mechanics.

func environmentOf(bundle model.CaptureBundle) string {
	if bundle.Environment != nil {
		return *bundle.Environment
	}
	for _, fact := range bundle.Facts {
		if fact.Environment != "" {
			return fact.Environment
		}
	}
	return ""
}

// representatives picks each scope's best answer to each question: the
// highest-ranked fact per (subject, predicate) — exactly the fact
// `conflicts` treats as a group's reference within INTENT.
func representatives(facts []model.Fact) map[key]model.Fact {
	best := map[key]model.Fact{}
	for groupKey, group := range groupBySubjectPredicate(facts) {
		best[groupKey] = byRankThenExtractor(group)[0]
	}
	return best
}

// crossScopeConflicts compares answers to the same question between
// INTENT and each environment, and between every pair of environments.
//
// Only questions *both* sides answered are compared here. A question one
// side never asked — INTENT has no `digest` for an image; a capture has
// no `example_shape` — is not a disagreement, and a comparator that
// treated silence as an answer would report every predicate one plane
// happens to have and the other does not.
func crossScopeConflicts(
	intent model.CaptureBundle, configured []model.CaptureBundle, now time.Time,
) []model.Divergence {
	var found []model.Divergence
	intentBest := representatives(intent.Facts)
	environmentBest := make([]map[key]model.Fact, len(configured))
	for index, bundle := range configured {
		environmentBest[index] = representatives(bundle.Facts)
	}

	compare := func(left, right model.Fact) {
		if model.ValuesEqual(left.Value, right.Value) && shapesEqual(left.ValueShape, right.ValueShape) {
			return
		}
		kind, ok := model.KindFor(left, right)
		if !ok {
			return
		}
		found = append(found, model.Divergence{
			Kind:      kind,
			Subject:   left.Subject,
			Predicate: left.Predicate,
			Left:      left,
			Right:     right,
			Severity:  model.SeverityUnknown,
			Explanation: fmt.Sprintf("%s and %s disagree about %s",
				sourceLabel(left), sourceLabel(right), left.Predicate),
			Status:      model.StatusOpen,
			FirstSeenAt: now,
		})
	}

	for index := range configured {
		for groupKey, right := range environmentBest[index] {
			if left, ok := intentBest[groupKey]; ok {
				compare(left, right)
			}
		}
		for later := index + 1; later < len(configured); later++ {
			for groupKey, left := range environmentBest[index] {
				// INTENT is the reference wherever it has an answer — the
				// same rule `conflicts` applies within INTENT, comparing
				// against the highest-ranked member rather than
				// all-against-all. If the code says the migration head is
				// 0003 and production says 0002, that is one finding; also
				// reporting "staging and production disagree" repeats it
				// in a form that no longer says which side is wrong.
				if _, intentAnswers := intentBest[groupKey]; intentAnswers {
					continue
				}
				if right, ok := environmentBest[later][groupKey]; ok {
					compare(left, right)
				}
			}
		}
	}
	return found
}

// crossScopeAbsences finds a thing one scope says exists that an
// environment which enumerated that kind of thing does not have.
//
// # The environment's own skips are honoured here
//
// Unlike within INTENT, where that guard was removed (see the package
// comment). The reason it was wrong there and is right here: several
// INTENT readers share one want, so one reader's "no compose file found"
// blinded all the others; in a capture, exactly one adapter enumerates a
// component's environment, and when it records "I could not see all of
// it" — a Kubernetes `envFrom` whose Secret could not be listed — it is
// talking about the very set this rule would otherwise treat as
// complete. Concluding "production does not set X" from a list known to
// be partial is the single most damaging thing this could say.
func crossScopeAbsences(
	intent model.CaptureBundle, configured []model.CaptureBundle, now time.Time,
) []model.Divergence {
	var found []model.Divergence
	covers := make([]coverage, len(configured))
	for index, bundle := range configured {
		covers[index] = buildScopedCoverage(bundle)
	}

	check := func(claims []model.Fact, target int) {
		cover := covers[target]
		for _, claim := range bestClaims(claims) {
			kind, parts, err := model.ParseSubject(claim.Subject)
			if err != nil {
				continue
			}
			want, comparable := wantForKind[kind]
			if !comparable {
				continue
			}
			owner := ownerOf(kind, parts)
			if owner == "" {
				continue
			}
			reference := cover.reference[componentKind{component: owner, kind: kind}]
			if reference == nil || reference.subjects[claim.Subject] {
				continue
			}
			if _, skipped := cover.skipped[componentWant{component: owner, want: want}]; skipped {
				continue
			}
			absent := absentFrom(reference, claim)
			kindOfFinding, ok := model.KindFor(claim, absent)
			if !ok {
				continue
			}
			found = append(found, model.Divergence{
				Kind:      kindOfFinding,
				Subject:   claim.Subject,
				Predicate: claim.Predicate,
				Left:      claim,
				Right:     absent,
				Severity:  model.SeverityUnknown,
				Explanation: fmt.Sprintf("%s refers to %s, which %s does not have",
					sourceLabel(claim), describeSubject(kind, parts), sourceLabel(reference.sample)),
				Status:      model.StatusOpen,
				FirstSeenAt: now,
			})
		}
	}

	// Subjects INTENT claims exist are judged against INTENT in each
	// environment, and not again environment-against-environment — the
	// reference rule, as in crossScopeConflicts. "The code reads
	// JWT_SECRET_KEY and production does not set it" is the finding; "and
	// staging does set it" is the same fault a second time, said worse.
	intentClaims := map[string]bool{}
	for _, claim := range bestClaims(intent.Facts) {
		intentClaims[claim.Subject] = true
	}
	unclaimed := func(facts []model.Fact) []model.Fact {
		kept := make([]model.Fact, 0, len(facts))
		for _, fact := range facts {
			if !intentClaims[fact.Subject] {
				kept = append(kept, fact)
			}
		}
		return kept
	}

	for index := range configured {
		check(intent.Facts, index)
		for other := range configured {
			if other != index {
				check(unclaimed(configured[other].Facts), index)
			}
		}
	}
	return found
}

// bestClaims keeps, per subject, the single highest-ranked existence
// claim. Across scopes the question is "does this environment have X",
// and one finding per X per environment answers it: `.env.example` and
// the code both mentioning a key the environment lacks is one fault, not
// two.
func bestClaims(facts []model.Fact) []model.Fact {
	bySubject := map[string][]model.Fact{}
	for _, fact := range facts {
		if existencePredicates[fact.Predicate] {
			bySubject[fact.Subject] = append(bySubject[fact.Subject], fact)
		}
	}
	claims := make([]model.Fact, 0, len(bySubject))
	for _, group := range bySubject {
		claims = append(claims, byRankThenExtractor(group)[0])
	}
	sort.Slice(claims, func(i, j int) bool { return claims[i].Subject < claims[j].Subject })
	return claims
}

// buildScopedCoverage is buildCoverage for one environment, keyed by
// ownerOf rather than by component alone — so a live database's tables,
// whose subjects name a database rather than a component, can be the
// complete set a migration's table is looked for in. Within INTENT the
// Phase 29 keying is kept exactly; widening it there would start judging
// schema absence between two INTENT sources, a behaviour change nobody
// asked this phase for.
func buildScopedCoverage(bundle model.CaptureBundle) coverage {
	result := coverage{
		reference: map[componentKind]*referenceSet{},
		skipped:   map[componentWant]string{},
	}
	for _, skip := range bundle.Skipped {
		if skip.Component != "" {
			result.skipped[componentWant{component: skip.Component, want: skip.Want}] = skip.Reason
		}
	}
	for _, fact := range bundle.Facts {
		if !existencePredicates[fact.Predicate] || fact.Provenance.ConfidenceRank < referenceRank ||
			!enumerates(fact) {
			continue
		}
		kind, parts, err := model.ParseSubject(fact.Subject)
		if err != nil {
			continue
		}
		owner := ownerOf(kind, parts)
		if owner == "" {
			continue
		}
		pair := componentKind{component: owner, kind: kind}
		if existing := result.reference[pair]; existing != nil {
			existing.subjects[fact.Subject] = true
			continue
		}
		result.reference[pair] = &referenceSet{
			extractor: fact.Provenance.Extractor,
			rank:      fact.Provenance.ConfidenceRank,
			subjects:  map[string]bool{fact.Subject: true},
			sample:    fact,
		}
	}
	return result
}

// ownerOf is whose enumeration a subject belongs to: its component, or,
// for a schema subject, its database.
func ownerOf(kind model.SubjectKind, parts model.Parts) string {
	if kind == model.KindSchema {
		return parts["database"]
	}
	return parts["component"]
}
