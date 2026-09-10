package report

import (
	"fmt"
	"io"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// RenderCapture is `culprit env capture --format text`: a person reading
// what one environment was found to be set up as (Phase 30).
//
// Every value goes through renderValue, the same guarded function the
// divergence report uses — so a config key shows its shape and never its
// value, granted or not. A granted literal is in the sealed envelope for
// the comparator; it is not for a terminal, a CI log, or a screenshot.
func RenderCapture(writer io.Writer, bundle model.CaptureBundle) error {
	environment := "?"
	if bundle.Environment != nil {
		environment = *bundle.Environment
	}
	fmt.Fprintf(writer, "Captured %s (%s adapter): %d fact(s) across %d subject(s).\n",
		environment, bundle.Meta["adapter"], len(bundle.Facts), countSubjects(bundle))

	if len(bundle.Grants) > 0 {
		fmt.Fprintln(writer, "\nGranted")
		for _, grant := range bundle.Grants {
			used := "used"
			if !grant.Used {
				used = "not used"
			}
			allow := ""
			if len(grant.Allow) > 0 {
				allow = fmt.Sprintf(" for %d item(s)", len(grant.Allow))
			}
			fmt.Fprintf(writer, "  %-24s %s%s\n", grant.Capability, used, allow)
		}
	}

	if len(bundle.Facts) > 0 {
		fmt.Fprintln(writer, "\nFacts")
		for _, fact := range bundle.Facts {
			fmt.Fprintf(writer, "  %-52s %-18s %s\n",
				truncate(fact.Subject, 52), truncate(fact.Predicate, 18), truncate(renderValue(fact), 60))
		}
	}

	input := Input{Bundle: model.CaptureBundle{}, Captures: []model.CaptureBundle{bundle}}
	reportRefused(writer, input)
	reportGaps(writer, input)
	return nil
}
