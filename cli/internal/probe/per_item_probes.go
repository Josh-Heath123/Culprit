package probe

import (
	"context"
	"fmt"
	"strconv"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/capture"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// --- probe.db.statements_per_request -------------------------------------
//
// Phase 39 part 1 (docs/PERFORMANCE_PLAN.md, "How Phase 39 is run" and
// "Part 1 — the measurement"). Which of a database's statements one GET of a
// list route runs once per item, by model.JudgePerItem — the rule
// shared/culprit_model/per_item.py holds too.
//
//   - Only where culprit.yaml declares the environment `isolated: true`
//     (Request.Isolated, stamped by the runner, never an input). Anywhere
//     else nothing is sent, and the reading is inconclusive, saying why: in
//     a shared environment another client's statements cannot be told from
//     this request's (P7).
//   - The database is the one the route's component reads by its single
//     `sql` edge (Q34); with none, or more than one, nothing is sent.
//   - One session takes three snapshots with the existing statistics
//     templates (capture.StatsReader.Bracket): before a 2-second quiet
//     window, after it, and after the GET. A call by any other role in the
//     quiet window means the declaration did not hold, and nothing is sent.
//   - The GET is probe.http.response_items's: GET only, on the target route
//     with no query, fragment or userinfo, no header, no redirect followed,
//     through the guarded client; the items are counted from that response,
//     at the `at` input's JSON pointer (the top level when there is none).
//   - It keeps the URL, `at`, the status, the count, the quiet window's
//     calls, and per normalised statement its queryid, calls and text under
//     Q29 and Q32's rules, at most model.StatementReadingMax of them. Never
//     a parameter, a row, an item, a key or a value.
//
// Evidence, not a finding (decision 1): it declares pass, inconclusive and
// refused, and no expectation, as probe.db.plan does. Its reason names each
// statement run per item. Not in the walk (part 2 puts it there).

type dbStatementsPerRequest struct{}

func (dbStatementsPerRequest) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		// A literal, so api/tests/test_probes_api.py can read it; held equal
		// to model.StatementsPerRequestProbeID by its test.
		ID:       "probe.db.statements_per_request",
		Verdicts: evidenceVerdicts,
		Version:  1,
		// It sends a GET to the application, as probe.http.response_items does.
		Effect:       model.EffectInterrogate,
		Capabilities: []string{"db.stats.read", "net.http.outbound"},
		// The quiet window, the GET under its own 15 s, and three snapshots.
		TimeoutMS: 30_000,
		// No expectation: a statement run per item on a fast route is not a
		// fault until something declares the route fast (decision 1).
		ExpectedFrom: "",
		Produces: []model.Produces{
			{SubjectTemplate: "http:{component}/{method} {path}", Predicate: "statements_per_item"},
		},
		Cost: model.CostCheap,
		Inputs: map[string]any{
			"type": "object",
			"properties": map[string]any{
				// Either a full url on the target route, or base_url, as
				// probe.http.response_items takes them.
				"url":      map[string]any{"type": "string"},
				"base_url": map[string]any{"type": "string"},
				// Where the list is in the response: a JSON pointer, checked
				// as a budget's `at:` is.
				"at": map[string]any{"type": "string"},
			},
		},
	}
}

// notCountedReason says why a response gave no count.
func notCountedReason(count ItemCount, at string) string {
	where := at
	if where == "" {
		where = "the top level"
	}
	switch count.NotCounted {
	case model.NotCountedStatus:
		return fmt.Sprintf("the route answered %d, not 2xx, so no list was counted", count.Status)
	case model.NotCountedNotJSON:
		return "the response is not JSON, so no list was counted"
	case model.NotCountedNoArray:
		return fmt.Sprintf("the response holds no array at %s, so no list was counted", where)
	case model.NotCountedTooLarge:
		return "the response is larger than the 1 MiB this probe reads, so no list was counted"
	}
	return ""
}

func (dbStatementsPerRequest) Run(ctx context.Context, request Request, deps Deps) Outcome {
	if !request.Isolated {
		environment := request.Environment
		if environment == "" {
			environment = "(none named)"
		}
		return inconclusive(fmt.Sprintf(
			"environment %s is not declared isolated in culprit.yaml (isolated: true), so another "+
				"client's statements could not be told from this request's: nothing was sent", environment))
	}
	kind, parts, err := model.ParseSubject(request.Target)
	if err != nil || kind != model.KindHTTP {
		return inconclusive("the target is not an http: route, so there is no list request to bracket")
	}
	if !strings.EqualFold(parts["method"], "GET") {
		return inconclusive(fmt.Sprintf(
			"%s %s is not a GET route, and this probe sends GET only: nothing was sent",
			parts["method"], parts["path"]))
	}
	url, method, problem := routeOf(request)
	if problem != "" {
		return inconclusive(problem)
	}
	if !strings.EqualFold(method, "GET") {
		return inconclusive("this probe sends GET only: nothing was sent")
	}
	if problem := urlOffRoute(url, parts); problem != "" {
		return inconclusive(problem + ": nothing was sent")
	}
	at := ""
	if raw, given := request.Inputs["at"]; given {
		text, ok := raw.(string)
		if !ok {
			return inconclusive("`at` is not text: nothing was sent")
		}
		if text != "" {
			if problem := model.JSONPointerProblem(text); problem != "" {
				return inconclusive(problem + ": nothing was sent")
			}
		}
		at = text
	}
	if deps.Statements == nil {
		return inconclusive("no database client is available to this agent")
	}
	counter, ok := deps.HTTP.(ItemCounter)
	if !ok {
		return inconclusive("no HTTP client that can count a list is available to this agent")
	}

	var count ItemCount
	var getErr error
	between := func(ctx context.Context) error {
		count, getErr = counter.CountItems(ctx, url, model.PointerTokens(at))
		return getErr
	}
	bracket, database, err := deps.Statements.Bracket(ctx, parts["component"], between)
	if err != nil {
		if outcome, decided := sourceOutcome(err); decided {
			return outcome
		}
		return inconclusive(fmt.Sprintf("the statements of %s's database could not be read: %s",
			parts["component"], model.RedactCredentials(err.Error())))
	}
	return judgeBracket(url, at, database, bracket, count, getErr)
}

// judgeBracket turns a bracket and the count of the response it held into
// the reading's outcome.
func judgeBracket(url, at, database string, bracket capture.StatementBracket,
	count ItemCount, getErr error,
) Outcome {
	measured := map[string]any{
		"url": url, "method": "GET", "at": at, "database": database,
		"quiet_window_s": int(capture.QuietWindowLength.Seconds()),
		"quiet_calls":    clampCount(bracket.QuietCalls),
	}
	switch {
	case bracket.Unavailable != "" && getErr != nil:
		return Outcome{Verdict: model.VerdictInconclusive, Measured: measured, Reason: fmt.Sprintf(
			"the GET did not complete (%s), so nothing was measured",
			model.RedactCredentials(getErr.Error()))}
	case bracket.Unavailable != "":
		return Outcome{Verdict: model.VerdictInconclusive, Measured: measured,
			Reason: fmt.Sprintf("%s: %s", database, bracket.Unavailable)}
	case bracket.Reset:
		measured["reset_during_bracket"] = true
		return Outcome{Verdict: model.VerdictInconclusive, Measured: measured, Reason: "pg_stat_statements " +
			"was reset, or a statement evicted from it, during the bracket, so no change over it can be trusted"}
	case bracket.QuietCalls > 0:
		return Outcome{Verdict: model.VerdictInconclusive, Measured: measured, Reason: fmt.Sprintf(
			"%d call(s) by another client in the %d s quiet window: %s is declared isolated, but it "+
				"was not quiet, so nothing was sent", bracket.QuietCalls,
			int(capture.QuietWindowLength.Seconds()), database)}
	case !bracket.Sent:
		return Outcome{Verdict: model.VerdictInconclusive, Measured: measured,
			Reason: "the bracket ended before the GET was sent; this is a bug in the probe"}
	}
	measured["status"] = count.Status
	if !count.Counted {
		reason := notCountedReason(count, at)
		if reason == "" {
			return inconclusive("the response could not be counted; this is a bug in the probe")
		}
		measured["not_counted"] = count.NotCounted
		return Outcome{Verdict: model.VerdictInconclusive, Measured: measured, Reason: reason}
	}
	measured["items"] = count.Items

	texts := map[string]any{}
	var statements []model.PerItemStatement
	tooLarge := 0
	for _, statement := range bracket.Statements {
		if statement.Calls > maxReadingCount {
			tooLarge++
			continue
		}
		queryID := strconv.FormatInt(statement.QueryID, 10)
		statements = append(statements, model.PerItemStatement{QueryID: queryID, Calls: int(statement.Calls)})
		switch {
		case statement.TextKept:
			// The second layer, after the template's own filter.
			texts[queryID] = model.RedactCredentials(statement.Text)
		case bracket.ServerVersion > 0 && bracket.ServerVersion < capture.MinimumPlanVersion:
			texts[queryID] = TextWithheldBefore16
		default:
			texts[queryID] = TextNotKept
		}
	}
	// The rule's order, so the statements kept are every one it names
	// first (model.PerItemOrder).
	model.PerItemOrder(statements)
	kept := []any{}
	for index, statement := range statements {
		if index < model.StatementReadingMax {
			kept = append(kept, map[string]any{
				"queryid": statement.QueryID, "calls": statement.Calls, "text": texts[statement.QueryID],
			})
		}
	}
	measured["statements"] = kept
	measured["other_statements"] = len(statements) - len(kept)
	measured["statements_too_large"] = tooLarge

	verdict, reason, perItem, err := model.JudgePerItem(measured)
	if err != nil {
		return inconclusive("the bracket's measurement is not the rule's input: " + err.Error())
	}
	measured["per_item"] = perItem
	if other := len(statements) - len(kept); other > 0 {
		reason += fmt.Sprintf("; %d statement(s) called fewer times were not kept", other)
	}
	if tooLarge > 0 {
		reason += fmt.Sprintf("; %d statement(s) with more than %d calls in the bracket were not judged",
			tooLarge, maxReadingCount)
	}
	return Outcome{Verdict: verdict, Measured: measured, Reason: reason}
}

// clampCount keeps a count within what a reading may hold.
func clampCount(count int64) int {
	if count > maxReadingCount {
		return maxReadingCount
	}
	return int(count)
}
