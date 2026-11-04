package report

import (
	"fmt"
	"io"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// RenderInvestigation prints an investigation for a person: the symptom,
// the diagnosis and its rubric, the fault tree with the readings behind
// every edge, and every hypothesis — including the ones the walk could not
// test, and why, because a partial diagnosis must look partial.
//
// Readings are printed as RenderReadings prints them, so they carry the
// redaction every reading already had when it was taken.
func RenderInvestigation(w io.Writer, inv model.Investigation) error {
	p := &printer{w: w}
	p.line("Symptom    %s", inv.Symptom.Subject)
	if inv.Symptom.Description != "" {
		p.line("           %s", inv.Symptom.Description)
	}
	p.line("Environment %s   investigation %s", inv.Environment, inv.ID)
	p.line("")

	if d := inv.Diagnosis; d != nil {
		status := "COMPLETE"
		if !d.Complete {
			status = "PARTIAL"
		}
		p.line("Diagnosis (%s)", status)
		p.line("  root   %s", d.RootSubject)
		p.line("  %s", d.Statement)
		if d.Remediation != "" {
			p.line("  fix    %s", d.Remediation)
		}
		p.line("")
		p.line("Confidence — four checks, never a number")
		for _, c := range []struct {
			name      string
			criterion model.Criterion
		}{
			{"reproduced", d.Confidence.Reproduced}, {"discriminated", d.Confidence.Discriminated},
			{"counterfactual", d.Confidence.Counterfactual}, {"verified", d.Confidence.Verified},
		} {
			mark := "no "
			if c.criterion.Holds {
				mark = "yes"
			}
			p.line("  %-15s %s  %s", c.name, mark, c.criterion.Reason)
		}
		p.line("")
	}

	p.line("Fault tree — every edge cites the readings that established it")
	if len(inv.FaultTree) == 0 {
		p.line("  (none: no reading established an edge)")
	}
	for _, edge := range inv.FaultTree {
		p.line("  %s", edge.FromSubject)
		p.line("    -[%s]-> %s   (%s)", edge.Relation, edge.ToSubject, strings.Join(edge.EstablishedBy, ", "))
	}
	p.line("")

	byStatus := map[model.HypothesisStatus][]model.Hypothesis{}
	for _, h := range inv.Hypotheses {
		byStatus[h.Status] = append(byStatus[h.Status], h)
	}
	for _, group := range []struct {
		status model.HypothesisStatus
		title  string
	}{
		{model.HypothesisSupported, "Supported"},
		{model.HypothesisRuledOut, "Ruled out"},
		{model.HypothesisUnexplored, "Unexplored — not tested, so not ruled out"},
		{model.HypothesisOpen, "Not reached — the walk never needed them"},
	} {
		hypotheses := byStatus[group.status]
		if len(hypotheses) == 0 {
			continue
		}
		p.line("%s (%d)", group.title, len(hypotheses))
		for _, h := range hypotheses {
			cited := ""
			if len(h.Readings) > 0 {
				cited = "  (" + strings.Join(h.Readings, ", ") + ")"
			}
			p.line("  %-24s %s%s", h.Kind, h.Subject, cited)
			if h.Reason != "" {
				p.line("      %s", h.Reason)
			}
		}
		p.line("")
	}

	p.line("Readings")
	for _, item := range inv.Readings {
		r := item.Reading
		p.line("  %-4s %-13s %s  %s", item.ID, r.Verdict, r.ProbeID, r.Target)
		if r.Reason != "" {
			p.line("       %s", r.Reason)
		}
	}
	return p.err
}

type printer struct {
	w   io.Writer
	err error
}

func (p *printer) line(format string, args ...any) {
	if p.err != nil {
		return
	}
	_, p.err = fmt.Fprintf(p.w, format+"\n", args...)
}
