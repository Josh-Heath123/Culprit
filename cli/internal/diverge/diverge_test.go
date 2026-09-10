package diverge

import (
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The comparator's two rules, at the boundaries.
//
// The fault corpus in `internal/check` exercises these end to end and is
// the better test of whether the engine is *right*. These are the cases
// that decide whether it is right for the right reason — the ones where
// getting it wrong still produces a plausible-looking answer.

var clock = time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)

func fact(subject, predicate string, value any, extractor, artefact string, rank int) model.Fact {
	kind := model.SourceStatic
	if rank >= 90 {
		kind = model.SourceIntrospection
	} else if rank >= 80 {
		kind = model.SourceSpec
	}
	return model.Fact{
		Plane:     model.PlaneIntent,
		Subject:   subject,
		Predicate: predicate,
		Value:     value,
		Provenance: model.Provenance{
			SourceKind:     kind,
			Extractor:      extractor,
			Artefact:       artefact,
			ConfidenceRank: rank,
		},
		CapturedAt: clock,
	}
}

func compare(facts []model.Fact, skips ...model.Skip) Result {
	return Compare(
		model.CaptureBundle{Facts: facts, Skipped: skips},
		Options{Now: clock},
	)
}

const (
	routeA = "http:orders-api/GET /orders"
	routeB = "http:orders-api/GET /orders/{}/refunds"
)

// --- rule one: conflict -------------------------------------------------

func TestTwoSourcesThatAgreeProduceNothing(t *testing.T) {
	result := compare([]model.Fact{
		fact(routeA, "status_codes", []any{"200"}, "app", "main.py", 90),
		fact(routeA, "status_codes", []any{"200"}, "spec", "openapi.json", 80),
	})
	if len(result.Divergences) != 0 {
		t.Fatalf("agreement produced %d finding(s): %+v",
			len(result.Divergences), result.Divergences)
	}
}

func TestTheHigherRankedSourceBecomesTheReference(t *testing.T) {
	// Which side is the reference decides which file the report tells the
	// reader to change, so it is not an implementation detail.
	result := compare([]model.Fact{
		fact(routeA, "status_codes", []any{"200"}, "spec", "openapi.json", 80),
		fact(routeA, "status_codes", []any{"200", "409"}, "app", "main.py", 90),
	})
	if len(result.Divergences) != 1 {
		t.Fatalf("expected one finding, got %d", len(result.Divergences))
	}
	if got := result.Divergences[0].Left.Provenance.Artefact; got != "main.py" {
		t.Errorf("the reference is %q; the rank-90 source should be", got)
	}
}

func TestThreeDisagreeingSourcesProduceTwoFindingsNotThree(t *testing.T) {
	// Pairwise against the reference, not all-against-all. The reader
	// wants to know what to fix, and N² findings about one subject is a
	// wall of text describing a single problem.
	result := compare([]model.Fact{
		fact(routeA, "status_codes", []any{"200"}, "app", "main.py", 90),
		fact(routeA, "status_codes", []any{"201"}, "spec", "openapi.json", 80),
		fact(routeA, "status_codes", []any{"202"}, "tests", "test_api.py", 50),
	})
	if len(result.Divergences) != 2 {
		t.Fatalf("expected two findings, got %d", len(result.Divergences))
	}
}

func TestOneExtractorReadingOneFileTwiceIsADuplicateNotADisagreement(t *testing.T) {
	result := compare([]model.Fact{
		fact(routeA, "status_codes", []any{"200"}, "spec", "openapi.json", 80),
		fact(routeA, "status_codes", []any{"404"}, "spec", "openapi.json", 80),
	})
	if len(result.Divergences) != 0 {
		t.Errorf("the same extractor reading the same file twice was reported "+
			"as a disagreement: %+v", result.Divergences)
	}
}

func TestOneExtractorReadingTwoFilesIsTwoSources(t *testing.T) {
	// The case that acceptance criterion 2 depends on: one extractor
	// reports both what the ORM declares and what the migrations create,
	// and an unmigrated column is exactly those two disagreeing. Keying
	// the duplicate guard on the extractor alone made this undetectable.
	result := compare([]model.Fact{
		fact("schema:orders-api-db/public.orders", "columns",
			[]any{"id", "total_cents"}, "python", "models.py", 90),
		fact("schema:orders-api-db/public.orders", "columns",
			[]any{"id"}, "python", "migrations/versions", 80),
	})
	if len(result.Divergences) != 1 {
		t.Fatalf("expected one finding, got %d: %+v",
			len(result.Divergences), result.Divergences)
	}
}

// --- rule two: absence --------------------------------------------------

func TestACallToARouteTheReferenceDoesNotListIsAFinding(t *testing.T) {
	result := compare([]model.Fact{
		fact(routeA, "exists", true, "app", "main.py", 90),
		fact(routeA, "calls", true, "node", "api.ts", 40),
		fact(routeB, "calls", true, "node", "api.ts", 40),
	})
	if len(result.Divergences) != 1 {
		t.Fatalf("expected one finding, got %d: %+v",
			len(result.Divergences), result.Divergences)
	}
	finding := result.Divergences[0]
	if finding.Subject != routeB {
		t.Errorf("the finding is about %q, expected %q", finding.Subject, routeB)
	}
	// The synthesised side must share the subject and predicate, or the
	// Python Divergence model refuses it on upload — and it must not
	// carry the reference sample's locator, which points at a different
	// route entirely.
	if finding.Right.Subject != finding.Subject ||
		finding.Right.Predicate != finding.Predicate {
		t.Errorf("the two sides do not describe the same claim: %q/%q vs %q/%q",
			finding.Left.Subject, finding.Left.Predicate,
			finding.Right.Subject, finding.Right.Predicate)
	}
	if finding.Right.Provenance.Locator != "" {
		t.Errorf("the absent side carries a locator (%q) that points at "+
			"some other route", finding.Right.Provenance.Locator)
	}
}

func TestNothingAuthoritativeMeansNoAbsenceFindings(t *testing.T) {
	// The guard that matters most: with no complete description of the
	// component's routes, "we did not look" must never become "it is not
	// there". A route table that could not be read shows as a skip.
	result := compare(
		[]model.Fact{
			fact(routeA, "calls", true, "node", "api.ts", 40),
			fact(routeB, "calls", true, "node", "api.ts", 40),
		},
		model.Skip{
			Component: "orders-api", Want: "http_routes",
			Reason: "importing the application raised KeyError",
		},
	)
	if len(result.Divergences) != 0 {
		t.Fatalf("absence was inferred from a component nobody described: %+v",
			result.Divergences)
	}
}

func TestALowRankedSourceIsNeverAReference(t *testing.T) {
	// A scrape of call sites is not a complete list of anything. If rank
	// 40 could define a reference set, every route the scraper happened
	// to miss would become a finding.
	result := compare([]model.Fact{
		fact(routeA, "calls", true, "node", "api.ts", 40),
		fact(routeB, "exists", true, "tests", "test_api.py", 50),
	})
	if len(result.Divergences) != 0 {
		t.Fatalf("a rank-40 source defined a reference set: %+v", result.Divergences)
	}
}

func TestADeveloperAssertionIsNeverAReference(t *testing.T) {
	// Rank 100 is the top of §2.4 and says nothing about whether the
	// source enumerated. An invariant says "this route must exist"; it
	// never says "and these are all of them".
	invariant := fact(routeB, "exists", true, "culprit.yaml invariants", "culprit.yaml", 100)
	invariant.Provenance.SourceKind = model.SourceAssertion

	result := compare([]model.Fact{
		invariant,
		fact(routeA, "exists", true, "app", "main.py", 90),
	})

	// Exactly one finding: the invariant's route is absent from the app's
	// route table. Not two — the app's own route must not be reported as
	// absent from a set of one hand-written line.
	if len(result.Divergences) != 1 {
		t.Fatalf("expected one finding, got %d: %+v",
			len(result.Divergences), result.Divergences)
	}
	if result.Divergences[0].Subject != routeB {
		t.Errorf("the finding is about %q, expected the asserted route %q",
			result.Divergences[0].Subject, routeB)
	}
}

// --- §0.1: what nothing could ever check --------------------------------

func TestUnverifiableIsSeparateFromFindings(t *testing.T) {
	// A place nobody checks is not a place something is wrong. Mixing the
	// two would make a clean run look alarming, and the coverage report
	// is a different question from "what is broken".
	result := compare([]model.Fact{
		fact(routeA, "exists", true, "app", "main.py", 90),
		fact(routeA, "exists", true, "spec", "openapi.json", 80),
		fact(routeB, "exists", true, "app", "main.py", 90),
	})
	if len(result.Divergences) != 0 {
		t.Fatalf("unexpected findings: %+v", result.Divergences)
	}
	if len(result.Unverifiable) != 1 || result.Unverifiable[0].Subject != routeB {
		t.Fatalf("expected exactly %q to be unverifiable, got %+v",
			routeB, result.Unverifiable)
	}
}

// --- determinism --------------------------------------------------------

func TestOutputIsStableAcrossRuns(t *testing.T) {
	// Go randomises map iteration deliberately, and this package groups
	// facts in a map. A report whose lines reorder between two runs on an
	// unchanged tree is one nobody can diff.
	facts := []model.Fact{
		fact(routeB, "status_codes", []any{"200"}, "app", "main.py", 90),
		fact(routeB, "status_codes", []any{"404"}, "spec", "openapi.json", 80),
		fact(routeA, "status_codes", []any{"200"}, "app", "main.py", 90),
		fact(routeA, "status_codes", []any{"201"}, "spec", "openapi.json", 80),
	}

	first := compare(facts)
	for run := 0; run < 20; run++ {
		next := compare(facts)
		if len(next.Divergences) != len(first.Divergences) {
			t.Fatalf("run %d produced %d findings, the first produced %d",
				run, len(next.Divergences), len(first.Divergences))
		}
		for index := range next.Divergences {
			if next.Divergences[index].ID() != first.Divergences[index].ID() {
				t.Fatalf("run %d ordered findings differently at %d: %q vs %q",
					run, index,
					next.Divergences[index].ID(), first.Divergences[index].ID())
			}
		}
	}
}

// TestTwoFindingsOnOneSubjectHaveDistinctIdentities.
//
// The identity is what the history table upserts on, so two different
// findings sharing one is not a cosmetic problem: the second upload's
// ON CONFLICT DO UPDATE overwrites the first, one row survives holding
// only the later finding, and the endpoint reports both as handled. A
// real fault deleted, with the response saying nothing was lost.
//
// It happened because `ID()` keyed on the two extractors while the
// comparator's own `sameSource` defines a source as extractor *and*
// artefact — the same conflation, made twice, in two places.
func TestTwoFindingsOnOneSubjectHaveDistinctIdentities(t *testing.T) {
	const table = "schema:orders-api-db/public.orders"

	// One extractor, three artefacts, all describing the same table:
	// the ORM, the migration chain, and a committed schema.sql. Two
	// findings, both against the rank-90 reference.
	result := compare([]model.Fact{
		fact(table, "columns", []any{"id", "total_cents"}, "python", "models.py", 90),
		fact(table, "columns", []any{"id"}, "python", "migrations/versions", 80),
		fact(table, "columns", []any{"id", "legacy"}, "python", "schema.sql", 80),
	})

	if len(result.Divergences) != 2 {
		t.Fatalf("expected two findings, got %d: %+v",
			len(result.Divergences), result.Divergences)
	}
	first, second := result.Divergences[0].ID(), result.Divergences[1].ID()
	if first == second {
		t.Fatalf("two different findings share an identity, so one would be "+
			"silently overwritten on upload: %q", first)
	}
}

// TestAbsenceDoesNotSwallowASecondPredicate.
//
// The de-duplication in `absences` keys on subject, predicate and
// extractor. Keyed on subject and extractor alone, one source claiming a
// subject under two existence predicates reported only the first.
func TestAbsenceDoesNotSwallowASecondPredicate(t *testing.T) {
	result := compare([]model.Fact{
		fact(routeA, "exists", true, "app", "main.py", 90),
		fact(routeB, "calls", true, "node", "api.ts", 40),
		fact(routeB, "exercised_by_test", true, "node", "api.ts", 40),
	})
	if len(result.Divergences) != 2 {
		t.Fatalf("expected both predicates reported, got %d: %+v",
			len(result.Divergences), result.Divergences)
	}
}
