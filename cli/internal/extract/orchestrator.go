package extract

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The orchestrator: built-in readers first, then plugins, then one
// bundle.
//
// **Determinism is a requirement here, not a nicety.** Acceptance
// criterion 2 is that running `culprit intent` twice on an unchanged
// tree produces byte-identical output. Three things would break that if
// left alone, and each is handled explicitly below:
//
//   - Map iteration order. Go randomises it deliberately. Every map is
//     drained into a slice and sorted before it reaches a fact.
//   - The capture id. A random UUID per run changes every byte of every
//     fact. It is derived instead — see DeriveCaptureID.
//   - The timestamp. `captured_at` is a real time and would differ on
//     every run, so the Clock is injectable and `intent` pins it to one
//     value for the whole capture rather than calling time.Now() per
//     fact. A caller who wants byte-identical output pins it further.

// Options configure one extraction run.
type Options struct {
	// Manifest is the loaded culprit.yaml, and ManifestDir the directory
	// it came from. Relative roots resolve against the latter.
	Manifest    *Manifest
	ManifestDir string
	// Only, when non-empty, restricts extraction to these components.
	Only []string
	// Want narrows what is asked for. Empty means everything.
	Want []model.Want
	// Now is the capture time. One value for the whole run.
	Now time.Time
	// PluginTimeout bounds each extractor. Zero means DefaultPluginTimeout.
	PluginTimeout time.Duration
	// SkipPlugins runs artefact readers only. This is what proves
	// acceptance criterion 4 in a test — the "no extractor installed"
	// path, exercised deliberately rather than by uninstalling things.
	SkipPlugins bool
	// Version identifies this binary in provenance and in the bundle.
	Version string
	// RepoRelativeArtefacts rewrites each fact's provenance.artefact to
	// be relative to the manifest directory rather than to the component
	// root it was extracted from. `culprit check` sets it; `culprit
	// intent` does not — see rebaseTarget for why the two differ.
	RepoRelativeArtefacts bool
}

// builtinReaders is the fixed set, in a fixed order. Order matters for
// byte-identical output.
func builtinReaders() []reader {
	return []reader{
		openAPIReader(),
		dotenvReader(),
		composeReader(),
		migrationHeadReader(),
		dependencyReader(),
	}
}

// Run performs the extraction and returns a capture bundle.
//
// It returns an error only for things that make the whole run
// meaningless — no manifest, no components. Everything else, up to and
// including every extractor being absent, is reported inside the bundle
// as skips. A command that exits non-zero because a plugin was missing
// would make the plugin mandatory in practice.
func Run(parent context.Context, options Options) (model.CaptureBundle, error) {
	if options.Manifest == nil {
		return model.CaptureBundle{}, fmt.Errorf("no culprit.yaml was loaded")
	}
	targets := options.Manifest.Targets(options.ManifestDir)
	if len(options.Only) > 0 {
		wanted := map[string]bool{}
		for _, name := range options.Only {
			wanted[model.CanonicalComponent(name)] = true
		}
		filtered := targets[:0:0]
		for _, target := range targets {
			if wanted[model.CanonicalComponent(target.Component)] {
				filtered = append(filtered, target)
			}
		}
		if len(filtered) == 0 {
			return model.CaptureBundle{}, fmt.Errorf(
				"no component in culprit.yaml matches %s", strings.Join(options.Only, ", "))
		}
		targets = filtered
	}
	if len(targets) == 0 {
		return model.CaptureBundle{}, fmt.Errorf(
			"culprit.yaml declares no components; there is nothing to extract")
	}

	wants := options.Want
	if len(wants) == 0 {
		wants = model.AllWants
	}
	wanted := map[model.Want]bool{}
	for _, want := range wants {
		wanted[want] = true
	}

	timeout := options.PluginTimeout
	if timeout == 0 {
		timeout = DefaultPluginTimeout
	}
	now := options.Now
	if now.IsZero() {
		now = time.Now().UTC()
	}
	now = now.UTC()

	orchestrator := "culprit@" + options.Version
	captureID := DeriveCaptureID(options.ManifestDir, targets, now)

	// Empty slices, not nil. A nil slice marshals to JSON `null`, and the
	// control plane's `CaptureBundle.facts` is a list — so a capture that
	// found nothing, which is the honest and common "no extractor
	// installed" outcome, would be rejected with a 422 by the one
	// endpoint that exists to receive it. Found by
	// shared/tests/test_wire_contract.py validating a real golden bundle
	// (the Express fixture yields zero artefact facts) against the
	// pydantic model.
	facts := []model.Fact{}
	skipped := []model.Skip{}

	for _, target := range targets {
		if target.Root == "" {
			skipped = append(skipped, model.Skip{
				Want:      "*",
				Component: target.Component,
				Reason: fmt.Sprintf(
					"%s has no source root: nothing was extracted for it. Add "+
						"extract.components.%s.root to culprit.yaml, or leave it "+
						"undeclared if it has no source of its own (a managed "+
						"database, a third-party service).",
					target.Component, target.Component),
				Extractor: orchestrator,
			})
			continue
		}

		ctx := captureContext{
			Component:  target.Component,
			Root:       target.Root,
			CaptureID:  captureID,
			CapturedAt: now,
			Extractor:  orchestrator,
		}

		for _, builtin := range builtinReaders() {
			if !wanted[builtin.want] {
				continue
			}
			readerFacts, readerSkips := builtin.run(ctx)
			if options.RepoRelativeArtefacts {
				rebaseTarget(readerFacts, target, options.ManifestDir)
			}
			facts = append(facts, readerFacts...)
			skipped = append(skipped, stamp(readerSkips, target.Component)...)
		}

		if options.SkipPlugins {
			// Said out loud rather than left as an unexplained absence.
			// A report missing every route because plugins were switched
			// off must not read like a report of a system with no routes.
			skipped = append(skipped, model.Skip{
				Want:      "*",
				Reason:    "extractor plugins were disabled for this run (--no-plugins); artefact readers only",
				Extractor: orchestrator,
			})
			continue
		}

		for _, spec := range target.Extractors {
			specWants := intersect(spec.Wants(), wanted)
			if len(specWants) == 0 {
				continue
			}
			result := RunPlugin(parent, spec, model.ExtractorRequest{
				Protocol:    model.ExtractorProtocolVersion,
				Root:        target.Root,
				Want:        specWants,
				Environment: nil, // INTENT is environment-independent (§0.2)
				Component:   target.Component,
				// Q34: the database this component's schema facts are on,
				// derived from the model, so an extractor's subjects join
				// the live capture's and the budgets'.
				Database: options.Manifest.SchemaDatabase(target.Component),
			}, timeout)

			// A plugin's facts are re-stamped with this run's capture id
			// and time — always, not only when the plugin left them
			// empty. Both belong to the *capture*, and an extractor has
			// no way to know either: it is one subprocess among several,
			// started at whatever moment the orchestrator got to it.
			//
			// The "only if empty" version of this was a real
			// determinism bug. Each plugin stamped its own wall clock,
			// so two runs of an unchanged tree differed in every
			// plugin-supplied fact — acceptance criterion 2, failing for
			// a reason that had nothing to do with extraction. Found by
			// running the command twice with SOURCE_DATE_EPOCH pinned
			// and diffing, which is exactly how the criterion is meant
			// to be checked.
			for index := range result.Facts {
				result.Facts[index].CaptureID = captureID
				result.Facts[index].CapturedAt = now
			}
			// Rebasing happens here, inside the per-target loop, because
			// this is the only place that knows which component *produced*
			// a fact. See rebaseTarget.
			if options.RepoRelativeArtefacts {
				rebaseTarget(result.Facts, target, options.ManifestDir)
			}
			retargeted, dropped := retargetClientCalls(result.Facts, target)
			facts = append(facts, retargeted...)
			skipped = append(skipped, stamp(result.Skipped, target.Component)...)
			if dropped > 0 {
				skipped = append(skipped, model.Skip{
					Want:      string(model.WantClientCalls),
					Component: target.Component,
					Reason: fmt.Sprintf(
						"%d client-call fact(s) from %s could not be retargeted at %s and were dropped",
						dropped, target.Component, target.CallsTo),
					Extractor: orchestrator,
				})
			}
		}

		if len(target.Extractors) == 0 {
			skipped = append(skipped, model.Skip{
				Want: "*",
				Reason: fmt.Sprintf(
					"no extractor is configured for %s; artefact readers only "+
						"(add one under extract.extractors in culprit.yaml)", target.Component),
				Component: target.Component,
				Extractor: orchestrator,
			})
		}
	}

	sortFacts(facts)
	sortSkips(skipped)

	finished := now
	meta := map[string]string{
		"cli_version": options.Version,
		"components":  strings.Join(componentNames(targets), ","),
	}
	return model.CaptureBundle{
		Protocol:    model.ExtractorProtocolVersion,
		Plane:       model.PlaneIntent,
		Environment: nil,
		Extractor:   orchestrator,
		CaptureID:   captureID,
		StartedAt:   now,
		FinishedAt:  &finished,
		Facts:       facts,
		Skipped:     skipped,
		Meta:        meta,
	}, nil
}

func intersect(wants []model.Want, wanted map[model.Want]bool) []model.Want {
	result := make([]model.Want, 0, len(wants))
	for _, want := range wants {
		if wanted[want] {
			result = append(result, want)
		}
	}
	return result
}

func componentNames(targets []Target) []string {
	names := make([]string, 0, len(targets))
	for _, target := range targets {
		names = append(names, target.Component)
	}
	return names
}

// DeriveCaptureID produces a stable id for a capture.
//
// A UUID v4 would be the obvious choice and is the wrong one here: a
// random id changes on every run, and acceptance criterion 2 requires
// two runs over an unchanged tree to produce byte-identical output. So
// the id is a hash of what the capture is *of* — the manifest directory,
// the components, and the capture time — rendered in UUID v5 shape so it
// is still a valid uuid to Postgres and to pydantic.
//
// The capture time is part of the input on purpose. Two captures of the
// same tree at different times are genuinely different captures and must
// not collide in `captures.id`; a caller wanting byte-identical output
// pins the clock, which is exactly what the golden-file tests do.
func DeriveCaptureID(manifestDir string, targets []Target, now time.Time) string {
	hasher := sha256.New()
	fmt.Fprintf(hasher, "culprit-capture-v1\x00%s\x00%s\x00",
		manifestDir, now.UTC().Format(time.RFC3339Nano))
	for _, name := range componentNames(targets) {
		fmt.Fprintf(hasher, "%s\x00", name)
	}
	sum := hasher.Sum(nil)
	// Version 5 / variant RFC 4122, so this is a well-formed UUID rather
	// than 32 hex characters with hyphens in them.
	sum[6] = (sum[6] & 0x0f) | 0x50
	sum[8] = (sum[8] & 0x3f) | 0x80
	hex := hex.EncodeToString(sum[:16])
	return fmt.Sprintf("%s-%s-%s-%s-%s", hex[0:8], hex[8:12], hex[12:16], hex[16:20], hex[20:32])
}

// sortFacts puts a fact list in a total, stable order.
//
// Subject, then predicate, then the extractor that produced it. The
// last key is what makes the order *total* rather than merely
// deterministic: two sources legitimately assert the same
// subject+predicate — that is what an intent_conflict is — and without a
// tiebreaker their relative order would depend on which reader ran
// first, which is exactly the instability criterion 2 forbids.
func sortFacts(facts []model.Fact) {
	sort.SliceStable(facts, func(i, j int) bool {
		left, right := facts[i], facts[j]
		if left.Subject != right.Subject {
			return left.Subject < right.Subject
		}
		if left.Predicate != right.Predicate {
			return left.Predicate < right.Predicate
		}
		if left.Provenance.Extractor != right.Provenance.Extractor {
			return left.Provenance.Extractor < right.Provenance.Extractor
		}
		if left.Provenance.Artefact != right.Provenance.Artefact {
			return left.Provenance.Artefact < right.Provenance.Artefact
		}
		return left.Provenance.Locator < right.Provenance.Locator
	})
}

func sortSkips(skips []model.Skip) {
	sort.SliceStable(skips, func(i, j int) bool {
		left, right := skips[i], skips[j]
		// Component first: a reader of a multi-component report needs the
		// gaps grouped by the thing they are gaps in, not by want.
		if left.Component != right.Component {
			return left.Component < right.Component
		}
		if left.Want != right.Want {
			return left.Want < right.Want
		}
		if left.Extractor != right.Extractor {
			return left.Extractor < right.Extractor
		}
		return left.Reason < right.Reason
	})
}

// retargetClientCalls rewrites a `calls` fact's subject from the caller's
// component to the component it calls, when culprit.yaml says which.
//
// Rebuilt through BuildSubject, never edited as a string. That is
// .claude/rules/model.md applied at the one place it is most tempting to
// break: the change is "swap one field", the string edit is one line, and
// a subject assembled by hand here would differ from the server's own by
// exactly the kind of detail (a trailing slash, a case) that makes
// comparison silently find nothing.
func retargetClientCalls(facts []model.Fact, target Target) ([]model.Fact, int) {
	if target.CallsTo == "" {
		return facts, 0
	}
	result := make([]model.Fact, 0, len(facts))
	dropped := 0
	for _, fact := range facts {
		if fact.Predicate != model.PredicateCalls {
			result = append(result, fact)
			continue
		}
		kind, parts, err := model.ParseSubject(fact.Subject)
		if err != nil || kind != model.KindHTTP {
			result = append(result, fact)
			continue
		}
		parts["component"] = target.CallsTo
		subject, err := model.BuildSubject(kind, parts)
		if err != nil {
			// Reported, not silently kept under the wrong component: a
			// fact on the caller's subject when the author asked for it
			// on the callee's is a fact that will never be compared, and
			// an uncompared fact reads as "nothing wrong here".
			dropped++
			continue
		}
		fact.Subject = subject
		result = append(result, fact)
	}
	return result, dropped
}

// stamp records which component a set of skips is about.
//
// Done here rather than in each reader because only the orchestrator
// knows, and because a reader that had to remember would eventually
// forget. Without it a three-service report reads "no .env.example
// found" three times with no way to tell which service each line is
// about — found by running the command against this repository's own
// demo services.
func stamp(skips []model.Skip, component string) []model.Skip {
	for index := range skips {
		if skips[index].Component == "" {
			skips[index].Component = component
		}
	}
	return skips
}
