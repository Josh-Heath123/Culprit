package report

import (
	"io"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// RenderVerification prints a verification for a person: the verdict and
// why, the three clauses, every reading as it was and as it is on each of
// the two runs, and every difference between the environment before and
// after with what explains it.
func RenderVerification(w io.Writer, v model.Verification) error {
	p := &printer{w: w}
	p.line("Verification %s of investigation %s", v.ID, v.InvestigationID)
	p.line("Environment  %s", v.Environment)
	var changes []string
	for _, change := range v.AppliedChange {
		changes = append(changes, change.Label())
	}
	if len(changes) == 0 {
		changes = []string{"none named"}
	}
	p.line("Change       %s", strings.Join(changes, ", "))
	p.line("")
	p.line("Verdict (%s)", strings.ToUpper(string(v.Verdict)))
	p.line("  %s", v.Reason)
	p.line("")
	p.line("  %s every reading that failed passes on both runs", mark(v.FailingNowPasses))
	p.line("  %s every reading that passed still passes", mark(v.NoRegressions))
	p.line("  %s every change in the environment is explained by the change named", mark(v.ChangesExplained))
	p.line("")
	p.line("Readings, measured again (was -> run 1, run 2)")
	for _, rerun := range v.Reran {
		where := ""
		if rerun.Environment != v.Environment {
			where = "   in " + rerun.Environment
		}
		p.line("  %-4s %-30s %s%s", rerun.ReadingID, rerun.ProbeID, rerun.Target, where)
		p.line("       %s -> %s, %s", rerun.Was, rerun.Runs[0].Verdict, rerun.Runs[1].Verdict)
		for _, run := range rerun.Runs {
			if run.Reason != "" && run.Verdict.NeedsReason() {
				p.line("       %s", run.Reason)
				break
			}
		}
	}
	p.line("")
	switch {
	case v.BeforeCapture == nil:
		p.line("Environment: no record of it before, so nothing could be compared")
	case len(v.Differences) == 0:
		p.line("Environment: nothing the capture records changed (%s, then %s)", *v.BeforeCapture, *v.AfterCapture)
	default:
		p.line("Environment: what changed since diagnosis (%s, then %s)", *v.BeforeCapture, *v.AfterCapture)
		for _, difference := range v.Differences {
			explained := "NOT explained by the change named"
			if difference.ExplainedBy != nil {
				explained = "explained by " + *difference.ExplainedBy
			}
			p.line("  %s (%s): %s", difference.Subject, difference.Predicate, explained)
		}
	}
	return p.err
}

func mark(holds bool) string {
	if holds {
		return "[x]"
	}
	return "[ ]"
}
