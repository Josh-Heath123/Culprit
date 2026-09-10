package extract

import (
	"fmt"
	"path/filepath"
	"strings"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Invariants become ordinary INTENT facts (Phase 29, field 10).
//
// # Why they are facts and not a second kind of rule
//
// The tempting design is a separate "assertions" engine that checks
// invariants directly against the extracted facts. It is the wrong one.
// D7 says the comparator must stay generic — it groups facts by subject
// and predicate and reports disagreement, knowing nothing about what a
// subject means. An invariant is a *source of intent*, and the fact that
// a human typed it rather than a parser reading it out of a file is
// expressed by one number: confidence rank 100, the top of §2.4, above
// everything an extractor can produce.
//
// The payoff is immediate and not hypothetical. An invariant saying a
// route exists, compared against a route table that does not list it,
// produces a divergence through exactly the same code path as an
// `openapi.json` disagreeing with the app — including the severity
// classification, the suppression check and the SARIF annotation. No new
// engine, no second set of edge cases, and rank 100 makes the human's
// statement the reference side, which is what a person means when they
// write an invariant down.
//
// # Rank 100 in both directions
//
// It also means an invariant that is *wrong* produces a loud finding
// rather than being quietly overruled by the code. That is correct. A
// stale assertion in `culprit.yaml` is a real defect — somebody stated
// intent and the system stopped meeting it — and which of the two is
// out of date is a judgement for the person reading the report, not for
// this file.

// InvariantFacts converts a manifest's invariants into INTENT facts.
//
// `capturedAt` and `captureID` are the run's, so an invariant fact is
// indistinguishable from any other fact in the bundle once built. That
// is the point: from here on nothing downstream treats it specially.
// `artefact` is how the manifest should be named in a report — a
// repo-relative path, because SARIF matches GitHub annotations by one
// and silently drops anything else.
func InvariantFacts(
	manifest *Manifest, artefact string, capturedAt time.Time, captureID string,
) ([]model.Fact, error) {
	if manifest == nil || len(manifest.Invariants) == 0 {
		return []model.Fact{}, nil
	}
	facts := make([]model.Fact, 0, len(manifest.Invariants))
	for index, invariant := range manifest.Invariants {
		fact := model.Fact{
			Plane:     model.PlaneIntent,
			Subject:   invariant.Subject,
			Predicate: invariant.Predicate,
			Value:     invariant.Value,
			Provenance: model.Provenance{
				SourceKind: model.SourceAssertion,
				Extractor:  "culprit.yaml invariants",
				Artefact:   artefact,
				// The index, not a line number: the YAML decoder does not
				// give us one, and a made-up line is worse than an honest
				// ordinal a reader can count to.
				Locator:        fmt.Sprintf("invariants[%d]", index),
				ConfidenceRank: model.RankDeveloperAssertion,
			},
			CapturedAt: capturedAt,
			CaptureID:  captureID,
		}
		if invariant.Value == nil {
			// A bare invariant asserts existence, which is the common
			// case: "this route must be there". `exists` is the predicate
			// the extractors already emit for that claim, so a bare
			// invariant compares against them without a special case.
			if fact.Predicate == "" {
				fact.Predicate = model.PredicateExists
			}
			fact.Value = true
		}
		if err := fact.Validate(); err != nil {
			// Nearly always the config-value rule: someone wrote the
			// expected value of a config key into culprit.yaml. Refusing
			// is the whole of architecture point 18 — the manifest is a
			// file people commit, and a tool that let a secret be asserted
			// in it would be handing them a footgun with a straight face.
			return nil, &PolicyError{Message: fmt.Sprintf(
				"invariants[%d] (%s): %s", index, invariant.Subject, err)}
		}
		facts = append(facts, fact)
	}
	return facts, nil
}

// rebaseTarget rewrites one target's facts so `provenance.artefact` is
// relative to the manifest directory rather than to the component root
// the extractor was handed.
//
// # Why this is keyed on the target, not on the subject
//
// The first version took the whole bundle and looked the prefix up by
// the *subject's* component. That is wrong whenever a fact's subject
// names a different component from the one that produced it — which is
// not an edge case, it is acceptance criterion 1. A client call from the
// `web` component carries the subject `http:orders-api/GET /...`, so the
// frontend's `src/lib/api.ts` was prefixed with the *backend's* root and
// the report pointed at `api/src/lib/api.ts`, a file that does not
// exist.
//
// That failure is close to silent: SARIF annotations are matched by
// GitHub against repo-relative paths, and a path that does not resolve
// produces no annotation and no error. The feature field 4 calls "most
// of the adoption story" would simply have shown nothing.
//
// So it runs inside the orchestrator's per-target loop, before
// `retargetClientCalls` moves any subject, where the producing component
// is the one thing that is certain.
//
// # Why `culprit intent` does not do this
//
// An extractor is handed one component's root and reports paths relative
// to it, which is right: it does not know where in a wider repository it
// has been pointed, and a fact naming `app/main.py` is portable between
// a monorepo and a split-out service. That is the correct frame for a
// capture bundle destined for the API, which is what `culprit intent`
// produces. A *report* is the opposite: its paths have to resolve from
// the repository root, for SARIF and for the reader's terminal alike.
func rebaseTarget(facts []model.Fact, target Target, baseDir string) {
	if target.Root == "" {
		return
	}
	relative, err := filepath.Rel(baseDir, target.Root)
	if err != nil || relative == "." || strings.HasPrefix(relative, "..") {
		// Outside the manifest directory, or the directory itself. A `..`
		// path would be worse than no prefix: SARIF would carry something
		// GitHub certainly cannot resolve.
		return
	}
	prefix := filepath.ToSlash(relative) + "/"
	for index := range facts {
		if facts[index].Provenance.Artefact == "" {
			continue
		}
		facts[index].Provenance.Artefact = prefix + facts[index].Provenance.Artefact
	}
}
