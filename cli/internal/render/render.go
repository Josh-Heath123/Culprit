// Package render turns a capture bundle into something to read.
//
// Two renderers, and the distinction matters more than it looks.
//
// JSON is the *contract* — it is what POST /facts/captures accepts, what
// a golden file pins, and what a later phase pipes into a comparator. It
// is emitted with sorted keys and a trailing newline so a diff between
// two runs is empty when nothing changed (acceptance criterion 2).
//
// Text is for a person at a terminal. It deliberately shows the skips as
// prominently as the facts: "I could not check X because Y is not
// installed" is the honest half of the report and the half a human acts
// on. A renderer that showed only what was found would make an
// incomplete capture look like a complete one.
package render

import (
	"encoding/json"
	"fmt"
	"io"
	"sort"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// JSON writes the bundle as one indented JSON object plus a newline.
//
// Indented rather than compact: this is read by people in CI logs at
// least as often as by programs, and the size difference is irrelevant
// next to that. json.Encoder with SetEscapeHTML(false) so a path
// containing `&` is not mangled into `&`, which would make the
// output differ from the same fact rendered by Python.
func JSON(writer io.Writer, bundle model.CaptureBundle) error {
	encoder := json.NewEncoder(writer)
	encoder.SetIndent("", "  ")
	encoder.SetEscapeHTML(false)
	return encoder.Encode(bundle)
}

// Text writes a human-readable inventory.
//
// An inventory and nothing more — Phase 28 field 17: "`culprit intent`
// prints an inventory and stops." No comparison, no judgement, no
// "problems found". Those are Phase 29's, and printing anything that
// looked like a finding here would make this phase's output impossible
// to tell apart from the next one's.
func Text(writer io.Writer, bundle model.CaptureBundle) error {
	byKind := map[string][]model.Fact{}
	for _, fact := range bundle.Facts {
		kind, _, err := model.ParseSubject(fact.Subject)
		if err != nil {
			continue
		}
		byKind[string(kind)] = append(byKind[string(kind)], fact)
	}

	kinds := make([]string, 0, len(byKind))
	for kind := range byKind {
		kinds = append(kinds, kind)
	}
	sort.Strings(kinds)

	fmt.Fprintf(writer, "INTENT capture %s\n", bundle.CaptureID)
	if components := bundle.Meta["components"]; components != "" {
		fmt.Fprintf(writer, "  components: %s\n", components)
	}
	fmt.Fprintf(writer, "  %d fact(s), %d skipped\n\n", len(bundle.Facts), len(bundle.Skipped))

	if len(bundle.Facts) == 0 {
		fmt.Fprintln(writer, "No facts. Every source was skipped — see below for why.")
	}

	for _, kind := range kinds {
		facts := byKind[kind]
		fmt.Fprintf(writer, "%s (%d)\n", strings.ToUpper(kind), len(facts))
		for _, fact := range facts {
			fmt.Fprintf(writer, "  %-58s %-16s %s\n",
				truncate(fact.Subject, 58), fact.Predicate, describeValue(fact))
			fmt.Fprintf(writer, "  %-58s %s\n", "", provenanceLine(fact.Provenance))
		}
		fmt.Fprintln(writer)
	}

	if len(bundle.Skipped) > 0 {
		fmt.Fprintf(writer, "SKIPPED (%d) — these are gaps in the capture, not clean results\n",
			len(bundle.Skipped))
		for _, skip := range bundle.Skipped {
			// The component first, because that is what a reader of a
			// multi-component report needs to see: "no .env.example
			// found" three times with nothing distinguishing the lines
			// is a report nobody can act on.
			fmt.Fprintf(writer, "  %-20s %-16s %s\n",
				truncate(skip.Component, 20), skip.Want, skip.Reason)
		}
	}
	return nil
}

// describeValue renders a fact's value for a terminal.
//
// A config fact normally has a ValueShape and no value, so the first
// branch is the one that runs and there is nothing to leak. The second
// branch *can* print a config fact's value — via the sanctioned bool
// exception (`read_by: true`), and via a granted literal, which is
// allowed by §2.7 precisely because someone opted into it per key.
//
// An earlier version of this comment claimed no such branch existed.
// It did, and saying otherwise is the kind of confident-and-wrong note
// that survives review; corrected after the Phase 28 invariant audit
// pointed at it.
func describeValue(fact model.Fact) string {
	if fact.ValueShape != nil {
		shape := *fact.ValueShape
		if !shape.Present {
			return "absent"
		}
		return fmt.Sprintf("%s/%s/%s", shape.Type, shape.Format, shape.LengthClass)
	}
	if fact.Value == nil {
		return ""
	}
	encoded, err := json.Marshal(fact.Value)
	if err != nil {
		return ""
	}
	return truncate(string(encoded), 60)
}

func provenanceLine(provenance model.Provenance) string {
	parts := []string{string(provenance.SourceKind), provenance.Extractor}
	if provenance.Artefact != "" {
		artefact := provenance.Artefact
		if provenance.Locator != "" {
			artefact += " " + provenance.Locator
		}
		parts = append(parts, artefact)
	}
	return fmt.Sprintf("rank %d · %s", provenance.ConfidenceRank, strings.Join(parts, " · "))
}

func truncate(text string, limit int) string {
	if len(text) <= limit {
		return text
	}
	if limit <= 1 {
		return text[:limit]
	}
	return text[:limit-1] + "…"
}
