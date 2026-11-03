package report

import (
	"fmt"
	"io"
	"sort"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Rendering readings (Phase 31).
//
// Every string that reaches a reader goes through model.RedactCredentials
// first, at this one point rather than per call site. Standing invariant
// 11: error text is output, and Phase 28 found four exfiltration paths
// through error strings where three of them were introduced by the fix
// for the previous one. Per-site redaction always has one more site.
//
// The order the four verdicts are printed in is deliberate. `fail` first,
// because it is the finding. Then `inconclusive` and `refused`, together,
// because "I could not check this" and "you did not let me check this"
// are the same thing from the reader's point of view: a gap in what this
// run established. `pass` last, because a wall of green is what hides the
// other three.

// RenderReadings writes the human-readable report for a probe run.
func RenderReadings(writer io.Writer, readings []model.Reading) error {
	if len(readings) == 0 {
		_, err := fmt.Fprintln(writer, "No probes ran.")
		return err
	}

	byVerdict := map[model.Verdict][]model.Reading{}
	for _, reading := range readings {
		byVerdict[reading.Verdict] = append(byVerdict[reading.Verdict], reading)
	}

	sections := []struct {
		verdict model.Verdict
		heading string
	}{
		{model.VerdictFail, "FAILING"},
		{model.VerdictInconclusive, "INCONCLUSIVE"},
		{model.VerdictRefused, "REFUSED"},
		{model.VerdictPass, "PASSING"},
	}

	for _, section := range sections {
		group := byVerdict[section.verdict]
		if len(group) == 0 {
			continue
		}
		sort.SliceStable(group, func(i, j int) bool {
			return group[i].ProbeID < group[j].ProbeID
		})
		if _, err := fmt.Fprintf(writer, "\n%s (%d)\n", section.heading, len(group)); err != nil {
			return err
		}
		for _, reading := range group {
			if err := renderReading(writer, reading); err != nil {
				return err
			}
		}
	}

	_, err := fmt.Fprintf(writer, "\n%s\n", summarise(byVerdict))
	return err
}

func renderReading(writer io.Writer, reading model.Reading) error {
	if _, err := fmt.Fprintf(writer, "  %s  %s\n",
		reading.ProbeID, reading.Target); err != nil {
		return err
	}
	if reading.Reason != "" {
		if _, err := fmt.Fprintf(writer, "      %s\n",
			model.RedactCredentials(reading.Reason)); err != nil {
			return err
		}
	}
	if measured := renderMeasured(reading.Measured); measured != "" {
		if _, err := fmt.Fprintf(writer, "      measured: %s\n", measured); err != nil {
			return err
		}
	}
	for _, evidence := range reading.Evidence {
		value := evidence.Value
		if evidence.Redacted {
			// A reading may legitimately carry evidence describing a
			// credential. What it must never do is print one, so the flag
			// is honoured here rather than trusted upstream.
			value = "<redacted>"
		} else {
			value = model.RedactCredentials(value)
		}
		if _, err := fmt.Fprintf(writer, "      %s: %s\n", evidence.Kind, value); err != nil {
			return err
		}
	}
	return nil
}

// renderMeasured prints a measurement compactly, with keys sorted so two
// runs of the same probe produce the same line.
//
// Values are rendered through RedactCredentials like everything else. A
// probe should never put a credential in `measured` — none of the
// built-in ones can — but a third-party probe is just a manifest and an
// exec procedure, and this is the point where its output becomes visible.
func renderMeasured(measured map[string]any) string {
	if len(measured) == 0 {
		return ""
	}
	keys := make([]string, 0, len(measured))
	for key := range measured {
		keys = append(keys, key)
	}
	sort.Strings(keys)

	parts := make([]string, 0, len(keys))
	for _, key := range keys {
		parts = append(parts, fmt.Sprintf("%s=%s",
			key, model.RedactCredentials(fmt.Sprintf("%v", measured[key]))))
	}
	return strings.Join(parts, " ")
}

func summarise(byVerdict map[model.Verdict][]model.Reading) string {
	return fmt.Sprintf("%d failing, %d inconclusive, %d refused, %d passing",
		len(byVerdict[model.VerdictFail]),
		len(byVerdict[model.VerdictInconclusive]),
		len(byVerdict[model.VerdictRefused]),
		len(byVerdict[model.VerdictPass]))
}
