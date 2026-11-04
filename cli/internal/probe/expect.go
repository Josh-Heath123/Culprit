package probe

import (
	"fmt"
	"net/url"
	"sort"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Expectation resolution — Phase 31.1.
//
// A reading is a measurement against a reference. Phase 31 built every
// probe to compare against `Request.Expectation` and then never populated
// it, so `expected_source` was always null and `expected_from` was inert:
// a measurement with no reference. This file is the reference.
//
// The facts come from the same extraction `culprit check` runs (the CLI
// calls check.Run), never from a second extraction path, so a probe and
// `culprit check` cannot disagree about what the code declares. For a
// manifest whose `expected_from` is CONFIGURED, the facts come from a
// Phase 30 capture of the named environment.
//
// Deterministic, like everything in this package: the subject a probe
// measures is built from its target and inputs with model.BuildSubject,
// matched against facts by subject and predicate, and the highest
// confidence_rank (§2.4) wins.
//
// Rank picks a default; it never discards (§0.3). When two facts on the
// same subject and predicate disagree, the probe still measures against
// the highest-ranked one, and the reading carries the others as
// `intent_conflict` evidence, so the disagreement reaches the report
// rather than being resolved silently here.

// EvidenceIntentConflict is the evidence kind naming a disagreement
// between declaring sources.
const EvidenceIntentConflict = "intent_conflict"

// Expectations is the set of facts probes are measured against.
type Expectations struct {
	byPredicate map[string][]model.Fact
}

// NewExpectations indexes INTENT facts and, optionally, the CONFIGURED
// facts of one capture. Facts of any other plane are ignored: a reading
// is never measured against another reading.
func NewExpectations(facts ...[]model.Fact) *Expectations {
	index := &Expectations{byPredicate: map[string][]model.Fact{}}
	for _, set := range facts {
		for _, fact := range set {
			if fact.Plane != model.PlaneIntent && fact.Plane != model.PlaneConfigured {
				continue
			}
			index.byPredicate[fact.Predicate] = append(index.byPredicate[fact.Predicate], fact)
		}
	}
	return index
}

// Resolution is what was found for one request.
type Resolution struct {
	// Subject is what the probe measures, built from its target and
	// inputs. Empty when it could not be built.
	Subject string
	// Predicate is the manifest's produced predicate.
	Predicate string
	// Fact is the expectation, when one was found.
	Fact *model.Fact
	// Conflicts are facts on the same subject and predicate whose value
	// differs from Fact's.
	Conflicts []model.Fact
	// Missing says, when Fact is nil, why nothing was found — written so
	// it can end a reading's reason.
	Missing string
}

// Resolve finds the expectation for one request against one manifest.
func (e *Expectations) Resolve(manifest model.ProbeManifest, request Request) Resolution {
	plane := manifest.ExpectedFrom
	if plane != model.PlaneIntent && plane != model.PlaneConfigured {
		return Resolution{Missing: "this probe is not measured against a declaration"}
	}
	if len(manifest.Produces) == 0 {
		return Resolution{Missing: "this probe's manifest declares nothing it produces"}
	}
	produced := manifest.Produces[0]

	kind, parts, reason := MeasuredSubject(produced.SubjectTemplate, request)
	if reason != "" {
		return Resolution{Predicate: produced.Predicate, Missing: reason}
	}
	subject, err := model.BuildSubject(kind, parts)
	if err != nil {
		return Resolution{Predicate: produced.Predicate, Missing: fmt.Sprintf(
			"the measured subject could not be built (%v)", err)}
	}
	resolution := Resolution{Subject: subject, Predicate: produced.Predicate}

	var candidates []model.Fact
	if e != nil {
		for _, fact := range e.byPredicate[produced.Predicate] {
			if fact.Plane != plane {
				continue
			}
			if plane == model.PlaneConfigured && fact.Environment != request.Environment {
				continue
			}
			candidates = append(candidates, fact)
		}
	}

	matched := matchSubject(kind, subject, candidates)
	if len(matched) == 0 {
		resolution.Missing = fmt.Sprintf("no %s fact declares %s %s",
			plane, subject, produced.Predicate)
		return resolution
	}

	// Highest rank first; ties broken by where the fact came from, so the
	// choice is reproducible rather than an accident of extraction order.
	sort.SliceStable(matched, func(i, j int) bool {
		left, right := matched[i].Provenance, matched[j].Provenance
		if left.ConfidenceRank != right.ConfidenceRank {
			return left.ConfidenceRank > right.ConfidenceRank
		}
		if left.Artefact != right.Artefact {
			return left.Artefact < right.Artefact
		}
		return left.Locator < right.Locator
	})
	chosen := matched[0]
	resolution.Fact = &chosen
	for _, other := range matched[1:] {
		if !model.ValuesEqual(other.Value, chosen.Value) {
			resolution.Conflicts = append(resolution.Conflicts, other)
		}
	}
	return resolution
}

// matchSubject returns the facts about subject. An HTTP subject built
// from a concrete URL (`/orders/42`) also matches a declared template
// (`/orders/{}`); when several declared subjects match, the most specific
// — fewest template segments — wins, so a literal route is never
// shadowed by a parameterised one.
func matchSubject(kind model.SubjectKind, subject string, facts []model.Fact) []model.Fact {
	var exact []model.Fact
	for _, fact := range facts {
		if fact.Subject == subject {
			exact = append(exact, fact)
		}
	}
	if len(exact) > 0 || kind != model.KindHTTP {
		return exact
	}

	_, wanted, err := model.ParseSubject(subject)
	if err != nil {
		return nil
	}
	best := -1
	var matched []model.Fact
	for _, fact := range facts {
		factKind, declared, err := model.ParseSubject(fact.Subject)
		if err != nil || factKind != model.KindHTTP {
			continue
		}
		if declared["component"] != wanted["component"] ||
			declared["method"] != wanted["method"] ||
			declared["aspect"] != wanted["aspect"] {
			continue
		}
		templated, ok := pathMatches(declared["path"], wanted["path"])
		if !ok {
			continue
		}
		switch {
		case best == -1 || templated < best:
			best, matched = templated, []model.Fact{fact}
		case templated == best:
			matched = append(matched, fact)
		}
	}
	return matched
}

// pathMatches reports whether a concrete canonical path matches a
// declared one, and how many template segments that took.
func pathMatches(declared, concrete string) (int, bool) {
	left := strings.Split(strings.Trim(declared, "/"), "/")
	right := strings.Split(strings.Trim(concrete, "/"), "/")
	if len(left) != len(right) {
		return 0, false
	}
	templated := 0
	for index := range left {
		switch {
		case left[index] == right[index]:
		case left[index] == "{}":
			templated++
		default:
			return 0, false
		}
	}
	return templated, true
}

// MeasuredSubject works out which subject a probe is measuring, from the
// kind its manifest produces, its target and its inputs. It returns the
// subject's kind and parts for model.BuildSubject — subjects are never
// formatted by hand (.claude/rules/model.md) — or a reason it could not.
//
// A target of the produced kind is taken as-is: `culprit probe
// 'schema:orders-db/public.orders'` names the table outright. Otherwise
// the subject is assembled from the target's component and the probe's
// own inputs, which is how `--input url=...` against a connection target
// becomes the route on the callee.
func MeasuredSubject(template string, request Request) (model.SubjectKind, model.Parts, string) {
	kind := model.SubjectKind(strings.SplitN(template, ":", 2)[0])
	targetKind, target, err := model.ParseSubject(request.Target)
	if err != nil {
		return "", nil, fmt.Sprintf("the target %q is not a subject URI", request.Target)
	}
	aspect := ""
	if index := strings.Index(template, "#"); index >= 0 {
		aspect = template[index+1:]
	}

	if targetKind == kind {
		parts := model.Parts{}
		for key, value := range target {
			parts[key] = value
		}
		if aspect != "" {
			parts["aspect"] = aspect
		}
		return kind, parts, ""
	}

	component := calleeOf(targetKind, target)
	switch kind {
	case model.KindHTTP:
		raw, ok := stringInput(request.Inputs, "url")
		if !ok {
			return "", nil, "no route was named: give the target as an http: subject or pass --input url="
		}
		parsed, err := url.Parse(raw)
		if err != nil || parsed.Path == "" {
			return "", nil, "the url input has no path to match against a declared route"
		}
		method, _ := stringInput(request.Inputs, "method")
		if method == "" {
			method = "GET"
		}
		parts := model.Parts{"component": component, "method": method, "path": parsed.Path}
		if aspect != "" {
			parts["aspect"] = aspect
		}
		return kind, parts, ""
	case model.KindSchema:
		table, ok := stringInput(request.Inputs, "table")
		if !ok {
			return "", nil, "no table was named: give the target as a schema: subject or pass --input table="
		}
		namespace, ok := stringInput(request.Inputs, "schema")
		if !ok {
			namespace = "public"
		}
		return kind, model.Parts{"database": component, "namespace": namespace, "table": table}, ""
	case model.KindConfig:
		key, ok := stringInput(request.Inputs, "key")
		if !ok {
			return "", nil, "no configuration key was named"
		}
		return kind, model.Parts{"component": component, "key": key}, ""
	case model.KindDep:
		name, ok := stringInput(request.Inputs, "package")
		if !ok {
			return "", nil, "no package was named"
		}
		return kind, model.Parts{"component": component, "dependency": name}, ""
	}
	return "", nil, fmt.Sprintf(
		"a %s target does not name a %s subject, which is what this probe measures",
		targetKind, kind)
}

// calleeOf is the component a probe of this target is asking about. For
// a connection or an auth relationship that is the far end — the route
// conformance of `connection:orders->payments` is a question about
// payments' routes — while the ledger's refusal records keep using the
// caller (componentOf), because that is where the probe runs from.
func calleeOf(kind model.SubjectKind, parts model.Parts) string {
	switch kind {
	case model.KindConnection, model.KindAuth:
		return parts["to_component"]
	case model.KindComponent, model.KindImage:
		return parts["name"]
	case model.KindSchema:
		return parts["database"]
	default:
		return parts["component"]
	}
}

// conflictEvidence renders the facts that disagreed with the chosen
// expectation, one evidence item each. The reading is redacted after
// this, at model.RedactReading, like every other free-text field.
func conflictEvidence(chosen *model.Fact, conflicts []model.Fact) []model.Evidence {
	evidence := make([]model.Evidence, 0, len(conflicts))
	for _, other := range conflicts {
		evidence = append(evidence, model.Evidence{
			Kind: EvidenceIntentConflict,
			Value: fmt.Sprintf(
				"%s (rank %d) says %s; this reading used %s (rank %d), which says %s",
				sourceName(other.Provenance), other.Provenance.ConfidenceRank,
				model.CanonicalJSON(other.Value),
				sourceName(chosen.Provenance), chosen.Provenance.ConfidenceRank,
				model.CanonicalJSON(chosen.Value)),
		})
	}
	return evidence
}

func sourceName(provenance model.Provenance) string {
	name := provenance.Artefact
	if name == "" {
		name = provenance.Extractor
	}
	if provenance.Locator != "" {
		name += " " + provenance.Locator
	}
	return name
}

// calleeOfTarget is calleeOf for a target that has not been parsed yet.
func calleeOfTarget(target string) string {
	kind, parts, err := model.ParseSubject(target)
	if err != nil {
		return target
	}
	return calleeOf(kind, parts)
}
