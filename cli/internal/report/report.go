// Package report renders findings (Phase 29, field 4).
//
// Four formats, and they are not four ways of saying the same thing —
// each has a reader in mind:
//
//   - **text** is a person at a terminal, deciding whether to care.
//   - **json** is a program, and is the stable contract.
//   - **sarif** is GitHub. SARIF is why a CI tool gets adopted: findings
//     appear as annotations on the changed lines of a pull request
//     instead of buried in a log nobody opens. The plan calls this "most
//     of the adoption story", and it is right.
//   - **junit** is every other CI system's test-report viewer.
//
// # The rule every format obeys
//
// **A report never prints a config value** (field 12). It cannot: a
// `config:` fact carries a `ValueShape`, and a `ValueShape` has four
// closed fields with nowhere to put a literal. But "cannot by
// construction" is only true while nothing downstream reconstructs one,
// so `redactionTest` in the test file greps every rendered format for a
// real secret, and the SARIF path is checked too — it is the format most
// likely to be pasted into a public pull request.
package report

import (
	"encoding/json"
	"encoding/xml"
	"fmt"
	"io"
	"sort"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/diverge"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Input is everything a renderer needs.
type Input struct {
	Result  diverge.Result
	Bundle  model.CaptureBundle
	Version string
	// Root is the repository root, so file paths in SARIF are relative
	// to it — GitHub matches annotations by repo-relative path and
	// silently drops anything else.
	Root string
	// ShowUnverifiable switches the §0.1 coverage report on. Off by
	// default: it is a different question from "what is wrong", and
	// mixing them would make a clean run look alarming.
	ShowUnverifiable bool
	// Captures are the environments a `culprit diff` compared (Phase 30).
	// Empty for `culprit check`. Their skips join the "not checked" list
	// and their refusals get a section of their own: field 14's "the
	// report says which checks were `refused`" is this.
	Captures []model.CaptureBundle
}

// Render writes one format.
func Render(writer io.Writer, format string, input Input) error {
	switch format {
	case "text":
		return renderText(writer, input)
	case "json":
		return renderJSON(writer, input)
	case "sarif":
		return renderSARIF(writer, input)
	case "junit":
		return renderJUnit(writer, input)
	default:
		return fmt.Errorf("unknown --format %q (want text, json, sarif or junit)", format)
	}
}

// --- text -------------------------------------------------------------

func renderText(writer io.Writer, input Input) error {
	open := openFindings(input.Result.Divergences)
	suppressed := len(input.Result.Divergences) - len(open)

	if len(open) == 0 {
		fmt.Fprintf(writer, "No divergences. %d fact(s) compared across %d subject(s).\n",
			totalFacts(input), countSubjects(input.Bundle, input.Captures...))
		if suppressed > 0 {
			fmt.Fprintf(writer, "%d finding(s) suppressed by culprit.yaml.\n", suppressed)
		}
		reportRefused(writer, input)
		reportGaps(writer, input)
		reportBudgets(writer, input)
		if input.ShowUnverifiable {
			renderUnverifiableText(writer, input)
		}
		return nil
	}

	fmt.Fprintf(writer, "%d divergence(s)\n\n", len(open))
	for _, finding := range open {
		fmt.Fprintf(writer, "  [%s] %s\n", finding.Severity, finding.Subject)
		fmt.Fprintf(writer, "      %s\n", finding.Explanation)
		// Both sides, with where each came from. This is what makes a
		// finding checkable rather than assertable: the reader can open
		// both files and decide for themselves.
		//
		// Value first, source second, and no "expected"/"found" labels.
		// Those labels were the first attempt and they are wrong half the
		// time: in a conflict the left side is the higher-confidence
		// source, but in an absence finding the left side is the *claim*
		// and the right side is the source that fails to corroborate it.
		// A label accurate for one kind of finding and backwards for the
		// other is worse than none, so each line simply says what one
		// source says and where to go and read it.
		fmt.Fprintf(writer, "      %s\n", describeSide(finding.Left))
		fmt.Fprintf(writer, "      %s\n", describeSide(finding.Right))
		if finding.SeverityReason != "" {
			fmt.Fprintf(writer, "      why %s: %s\n", finding.Severity, finding.SeverityReason)
		}
		fmt.Fprintln(writer)
	}

	if suppressed > 0 {
		fmt.Fprintf(writer, "%d further finding(s) suppressed by culprit.yaml.\n", suppressed)
	}
	reportRefused(writer, input)
	reportGaps(writer, input)
	reportBudgets(writer, input)
	if input.ShowUnverifiable {
		renderUnverifiableText(writer, input)
	}
	return nil
}

// reportRefused prints what an environment capture was not allowed to
// look at (Phase 30).
//
// Its own section, ahead of the gaps, because it is a different kind of
// gap with a different remedy: a skip is "culprit tried and could not", a
// refusal is "you have not granted this" — and the reader can fix the
// second with one line of culprit.yaml.
func reportRefused(writer io.Writer, input Input) {
	refusals := allRefusals(input)
	if len(refusals) == 0 {
		return
	}
	fmt.Fprintf(writer, "\nRefused (%d) — not looked at, because the capability was not granted\n",
		len(refusals))
	for _, refusal := range refusals {
		fmt.Fprintf(writer, "  %-28s %-22s %s\n",
			truncate(refusal.where, 28), truncate(refusal.Check, 22), refusal.Reason)
	}
}

// reportGaps prints what was *not* compared.
//
// Not an afterthought. A report that lists three findings without saying
// "and I could not look at these four things" invites the reader to
// conclude the rest is fine, which is the failure mode this whole
// product exists to avoid. The skips come straight from the capture.
func reportGaps(writer io.Writer, input Input) {
	skips := allSkips(input)
	if len(skips) == 0 {
		return
	}
	fmt.Fprintf(writer, "\nNot checked (%d) — these are gaps, not clean results\n", len(skips))
	for _, skip := range skips {
		fmt.Fprintf(writer, "  %-18s %-16s %s\n",
			truncate(skip.Component, 18), skip.Want, skip.Reason)
	}
}

// reportBudgets prints budget coverage (Phase 36): budgets that name
// nothing declared, always, and the unbudgeted surface when the manifest
// declares `budgets:` at all. Neither is a divergence: one is a manifest
// mistake nothing would otherwise surface, the other a list of routes no
// declaration holds to a time.
func reportBudgets(writer io.Writer, input Input) {
	budgets := input.Result.Budgets
	if len(budgets.Unmatched) > 0 {
		fmt.Fprintf(writer, "\nBudgets that name nothing declared (%d) — they would never be measured\n",
			len(budgets.Unmatched))
		for _, entry := range budgets.Unmatched {
			location := entry.Artefact
			if entry.Locator != "" {
				location += " " + entry.Locator
			}
			fmt.Fprintf(writer, "  %-58s %s\n", truncate(entry.Subject, 58), location)
		}
	}
	if budgets.Declared {
		fmt.Fprintf(writer, "\nUnbudgeted surface (%d) — declared routes no budget holds to a time\n",
			len(budgets.Unbudgeted))
		for _, subject := range budgets.Unbudgeted {
			fmt.Fprintf(writer, "  %s\n", subject)
		}
	}
}

// labelledRefusal is a refusal with the environment it happened in.
type labelledRefusal struct {
	model.Refusal
	Environment string `json:"environment"`
	where       string
}

func allRefusals(input Input) []labelledRefusal {
	var refusals []labelledRefusal
	for _, capture := range input.Captures {
		environment := captureEnvironment(capture)
		for _, refusal := range redactRefusals(capture.Refused) {
			where := environment
			if refusal.Component != "" {
				where += "/" + refusal.Component
			}
			refusals = append(refusals, labelledRefusal{
				Refusal: refusal, Environment: environment, where: where,
			})
		}
	}
	return refusals
}

// allSkips is INTENT's skips followed by each capture's, with a capture's
// component prefixed by its environment so "orders-api could not be
// read" says *where*.
func allSkips(input Input) []model.Skip {
	skips := make([]model.Skip, 0, len(input.Bundle.Skipped))
	for _, skip := range input.Bundle.Skipped {
		skip.Reason = model.RedactCredentials(skip.Reason)
		skips = append(skips, skip)
	}
	for _, capture := range input.Captures {
		environment := captureEnvironment(capture)
		for _, skip := range capture.Skipped {
			skip.Component = environment + "/" + skip.Component
			skip.Reason = model.RedactCredentials(skip.Reason)
			skips = append(skips, skip)
		}
	}
	return skips
}

// redactRefusals is the one path a refusal's reason takes into any
// rendering. Every skip and refusal reason in every format goes through
// model.RedactCredentials: the CLI writes its own from closed vocabulary,
// but a loaded envelope's were written by whoever wrote the envelope, and
// an extractor plugin's skip reasons by whoever wrote the plugin.
// Standing invariant 11 — one choke point, not one per format.
func redactRefusals(refusals []model.Refusal) []model.Refusal {
	redacted := make([]model.Refusal, 0, len(refusals))
	for _, refusal := range refusals {
		refusal.Reason = model.RedactCredentials(refusal.Reason)
		redacted = append(redacted, refusal)
	}
	return redacted
}

func captureEnvironment(capture model.CaptureBundle) string {
	if capture.Environment != nil {
		return *capture.Environment
	}
	return "?"
}

func totalFacts(input Input) int {
	total := len(input.Bundle.Facts)
	for _, capture := range input.Captures {
		total += len(capture.Facts)
	}
	return total
}

func renderUnverifiableText(writer io.Writer, input Input) {
	fmt.Fprintf(writer, "\nUnverifiable surface (%d)\n", len(input.Result.Unverifiable))
	fmt.Fprintln(writer,
		"  Subjects only one source describes, so nothing could ever contradict them.")
	fmt.Fprintln(writer,
		"  Not defects — places where a mistake would go uncaught (§0.1).")
	fmt.Fprintln(writer)
	for _, entry := range input.Result.Unverifiable {
		location := entry.Artefact
		if entry.Locator != "" {
			location += " " + entry.Locator
		}
		fmt.Fprintf(writer, "  %-58s %s\n", truncate(entry.Subject, 58), location)
	}
}

func describeSide(fact model.Fact) string {
	where := fact.Provenance.Artefact
	if fact.Provenance.Locator != "" {
		where += " " + fact.Provenance.Locator
	}
	if where == "" {
		where = fact.Provenance.Extractor
	}
	// A CONFIGURED fact is labelled with the environment it was read in
	// rather than a rank: §2.4's ranks are about how much to trust a claim
	// of what *should* be true, and "what production is set to" is not
	// that kind of claim. Which environment is the thing a reader needs.
	if fact.Environment != "" {
		return fmt.Sprintf("%-42s %s (in %s)",
			truncate(renderValue(fact), 42), where, fact.Environment)
	}
	return fmt.Sprintf("%-42s %s (rank %d)",
		truncate(renderValue(fact), 42), where, fact.Provenance.ConfidenceRank)
}

// renderValue prints a fact's value — or, for a config key, its shape.
//
// # The config branch is a guarantee, not a formatting choice
//
// The first version of this function had no such branch. The reasoning
// was that a config fact cannot carry a literal value, because
// `Fact.Validate` refuses one without a grant — so the fall-through to
// `CanonicalJSON(fact.Value)` could never see a credential.
//
// The redaction test disagreed immediately, and it was right. This
// function renders whatever fact it is handed. Validation happens
// elsewhere, on another code path, in another package, and "elsewhere
// guarantees it" is exactly the shape of reasoning that produces a leak
// the day someone adds a fourth way for a fact to arrive. A config value
// printed into a SARIF file lands on a pull request that may be public
// and stays in GitHub's code-scanning history afterwards.
//
// So the subject is parsed and a `config:` subject never reaches the
// value branch, whatever the fact carries. The guarantee is now a
// property of the renderer rather than an assumption about its callers.
func renderValue(fact model.Fact) string {
	if fact.ValueShape != nil {
		shape := *fact.ValueShape
		// A shape built outside the closed sets is not rendered field by
		// field: until Phase 30 the Go side did not check membership, and
		// a `format` holding a DSN would have been printed verbatim here.
		// Decoding now refuses one; this refuses to print one regardless.
		if !shape.Valid() {
			return "(an unrecognised shape, not shown)"
		}
		if !shape.Present {
			return "absent"
		}
		format := string(shape.Format)
		// The scheme is what explains a "postgresql against mysql"
		// finding; without it both sides would read `string/dsn/medium`
		// and the reader could not see why they differ. A closed enum, so
		// printing it cannot print a value.
		if shape.Scheme != "" && shape.Scheme != model.SchemeNotApplicable {
			format += "(" + string(shape.Scheme) + ")"
		}
		return fmt.Sprintf("%s/%s/%s", shape.Type, format, shape.LengthClass)
	}
	if kind, _, err := model.ParseSubject(fact.Subject); err == nil && kind == model.KindConfig {
		// A bool is the one value a config fact may legitimately carry
		// (`read_by`, `required`) — two inhabitants, so it cannot hide a
		// credential. Everything else is described, never printed.
		if boolean, ok := fact.Value.(bool); ok {
			return fmt.Sprintf("%t", boolean)
		}
		if fact.Value == nil {
			return "(declared)"
		}
		return "(a value, not shown)"
	}
	if fact.Value == nil {
		return "(exists)"
	}
	return model.CanonicalJSON(fact.Value)
}

// --- json -------------------------------------------------------------

type jsonReport struct {
	Version      string                 `json:"culprit_version"`
	CaptureID    string                 `json:"capture_id"`
	Summary      jsonSummary            `json:"summary"`
	Divergences  []jsonDivergence       `json:"divergences"`
	NotChecked   []model.Skip           `json:"not_checked"`
	Unverifiable []diverge.Unverifiable `json:"unverifiable,omitempty"`
	// Phase 36: budget coverage. Omitted when there is none to report, so
	// a manifest with no budgets keeps the same JSON contract.
	UnmatchedBudgets []diverge.Unverifiable `json:"unmatched_budgets,omitempty"`
	Unbudgeted       []string               `json:"unbudgeted,omitempty"`
	// Phase 30: one entry per environment a diff compared. Omitted for
	// `culprit check`, so its JSON contract is unchanged.
	Environments []jsonEnvironment `json:"environments,omitempty"`
}

// jsonEnvironment is what a reader needs to judge a capture: which one it
// was, what it was allowed to look at, and what it was refused.
type jsonEnvironment struct {
	Name      string          `json:"name"`
	CaptureID string          `json:"capture_id"`
	Facts     int             `json:"facts"`
	Grants    []model.Grant   `json:"grants"`
	Refused   []model.Refusal `json:"refused"`
}

type jsonSummary struct {
	Facts                int `json:"facts"`
	Subjects             int `json:"subjects"`
	Open                 int `json:"open"`
	Suppressed           int `json:"suppressed"`
	BreaksRequestPath    int `json:"breaks_request_path"`
	Degrades             int `json:"degrades"`
	Cosmetic             int `json:"cosmetic"`
	Unknown              int `json:"unknown"`
	UnverifiableSubjects int `json:"unverifiable_subjects"`
}

type jsonDivergence struct {
	ID             string   `json:"id"`
	Kind           string   `json:"kind"`
	Subject        string   `json:"subject"`
	Predicate      string   `json:"predicate"`
	Severity       string   `json:"severity"`
	SeverityReason string   `json:"severity_reason,omitempty"`
	Explanation    string   `json:"explanation"`
	Status         string   `json:"status"`
	SuppressedBy   string   `json:"suppressed_by,omitempty"`
	Left           jsonSide `json:"left"`
	Right          jsonSide `json:"right"`
}

type jsonSide struct {
	Value     string `json:"value"`
	Extractor string `json:"extractor"`
	Artefact  string `json:"artefact,omitempty"`
	Locator   string `json:"locator,omitempty"`
	Rank      int    `json:"confidence_rank"`
	// Plane and Environment say which side of a Phase 30 finding this
	// is. Plane is always present; Environment only for a CONFIGURED
	// side, so an INTENT-only report is unchanged apart from the plane.
	Plane       string `json:"plane"`
	Environment string `json:"environment,omitempty"`
}

func side(fact model.Fact) jsonSide {
	return jsonSide{
		Value:       renderValue(fact),
		Extractor:   fact.Provenance.Extractor,
		Artefact:    fact.Provenance.Artefact,
		Locator:     fact.Provenance.Locator,
		Rank:        fact.Provenance.ConfidenceRank,
		Plane:       string(fact.Plane),
		Environment: fact.Environment,
	}
}

func buildJSON(input Input) jsonReport {
	report := jsonReport{
		Version:     input.Version,
		CaptureID:   input.Bundle.CaptureID,
		Divergences: []jsonDivergence{},
		NotChecked:  allSkips(input),
	}
	if report.NotChecked == nil {
		report.NotChecked = []model.Skip{}
	}
	for _, capture := range input.Captures {
		environment := jsonEnvironment{
			Name:      captureEnvironment(capture),
			CaptureID: capture.CaptureID,
			Facts:     len(capture.Facts),
			Grants:    capture.Grants,
			Refused:   redactRefusals(capture.Refused),
		}
		if environment.Grants == nil {
			environment.Grants = []model.Grant{}
		}
		if environment.Refused == nil {
			environment.Refused = []model.Refusal{}
		}
		report.Environments = append(report.Environments, environment)
	}
	if input.ShowUnverifiable {
		report.Unverifiable = input.Result.Unverifiable
		if report.Unverifiable == nil {
			report.Unverifiable = []diverge.Unverifiable{}
		}
	}

	report.UnmatchedBudgets = input.Result.Budgets.Unmatched
	if input.Result.Budgets.Declared {
		report.Unbudgeted = input.Result.Budgets.Unbudgeted
	}

	report.Summary.Facts = totalFacts(input)
	report.Summary.Subjects = countSubjects(input.Bundle, input.Captures...)
	report.Summary.UnverifiableSubjects = len(input.Result.Unverifiable)

	for _, finding := range input.Result.Divergences {
		if finding.Status == model.StatusSuppressed {
			report.Summary.Suppressed++
		} else {
			report.Summary.Open++
			switch finding.Severity {
			case model.SeverityBreaksRequestPath:
				report.Summary.BreaksRequestPath++
			case model.SeverityDegrades:
				report.Summary.Degrades++
			case model.SeverityCosmetic:
				report.Summary.Cosmetic++
			default:
				report.Summary.Unknown++
			}
		}
		report.Divergences = append(report.Divergences, jsonDivergence{
			ID:             finding.ID(),
			Kind:           string(finding.Kind),
			Subject:        finding.Subject,
			Predicate:      finding.Predicate,
			Severity:       string(finding.Severity),
			SeverityReason: finding.SeverityReason,
			Explanation:    finding.Explanation,
			Status:         string(finding.Status),
			SuppressedBy:   finding.SuppressedBy,
			Left:           side(finding.Left),
			Right:          side(finding.Right),
		})
	}
	return report
}

func renderJSON(writer io.Writer, input Input) error {
	encoder := json.NewEncoder(writer)
	encoder.SetIndent("", "  ")
	encoder.SetEscapeHTML(false)
	return encoder.Encode(buildJSON(input))
}

// --- sarif ------------------------------------------------------------

// SARIF 2.1.0, the subset GitHub reads.
//
// Deliberately hand-built rather than pulled from a library: the subset
// is small, the schema is stable, and a dependency here would be a
// dependency in a binary whose whole selling point is that it has almost
// none.

type sarifLog struct {
	Schema  string     `json:"$schema"`
	Version string     `json:"version"`
	Runs    []sarifRun `json:"runs"`
}

type sarifRun struct {
	Tool    sarifTool     `json:"tool"`
	Results []sarifResult `json:"results"`
	// Invocations carry what the run did *not* look at — refusals and
	// gaps — as tool execution notifications (SARIF 2.1.0 §3.20.21). The
	// first version of the Phase 30 SARIF output had none: a diff with no
	// grants at all produced an empty, clean-looking log while the text
	// report listed twelve refusals. That is "I was not allowed to look"
	// presented as "I looked and found nothing", in the format most likely
	// to be read by a machine that will not go and check the text. Found
	// by the Phase 30 phase audit.
	Invocations []sarifInvocation `json:"invocations,omitempty"`
}

type sarifInvocation struct {
	ExecutionSuccessful        bool                `json:"executionSuccessful"`
	ToolExecutionNotifications []sarifNotification `json:"toolExecutionNotifications"`
}

type sarifNotification struct {
	Level   string    `json:"level"`
	Message sarifText `json:"message"`
}

type sarifTool struct {
	Driver sarifDriver `json:"driver"`
}

type sarifDriver struct {
	Name           string      `json:"name"`
	Version        string      `json:"version"`
	InformationURI string      `json:"informationUri"`
	Rules          []sarifRule `json:"rules"`
}

type sarifRule struct {
	ID               string            `json:"id"`
	Name             string            `json:"name"`
	ShortDescription sarifText         `json:"shortDescription"`
	FullDescription  sarifText         `json:"fullDescription"`
	DefaultConfig    sarifRuleConfig   `json:"defaultConfiguration"`
	Properties       map[string]string `json:"properties,omitempty"`
}

type sarifRuleConfig struct {
	Level string `json:"level"`
}

type sarifText struct {
	Text string `json:"text"`
}

type sarifResult struct {
	RuleID    string          `json:"ruleId"`
	Level     string          `json:"level"`
	Message   sarifText       `json:"message"`
	Locations []sarifLocation `json:"locations"`
	// PartialFingerprints let GitHub track a finding across commits, so
	// the same fault does not read as new every time the file moves.
	PartialFingerprints map[string]string `json:"partialFingerprints,omitempty"`
}

type sarifLocation struct {
	PhysicalLocation sarifPhysical `json:"physicalLocation"`
}

type sarifPhysical struct {
	ArtifactLocation sarifArtifact `json:"artifactLocation"`
	Region           *sarifRegion  `json:"region,omitempty"`
}

type sarifArtifact struct {
	URI string `json:"uri"`
}

type sarifRegion struct {
	StartLine int `json:"startLine"`
}

// sarifLevel maps severity onto SARIF's own vocabulary.
//
// `cosmetic` becomes `note`, not `warning`: a PR annotation that shouts
// about a dev-dependency version teaches people to ignore the tool, and
// a tool people ignore finds nothing.
func sarifLevel(level model.Severity) string {
	switch level {
	case model.SeverityBreaksRequestPath:
		return "error"
	case model.SeverityDegrades:
		return "warning"
	case model.SeverityUnknown:
		return "warning"
	default:
		return "note"
	}
}

func renderSARIF(writer io.Writer, input Input) error {
	open := openFindings(input.Result.Divergences)

	rules := map[string]sarifRule{}
	results := make([]sarifResult, 0, len(open))

	for _, finding := range open {
		ruleID := "culprit/" + string(finding.Kind) + "/" + finding.Predicate
		if _, exists := rules[ruleID]; !exists {
			rules[ruleID] = sarifRule{
				ID:   ruleID,
				Name: string(finding.Kind) + "." + finding.Predicate,
				ShortDescription: sarifText{
					Text: fmt.Sprintf("Two sources disagree about %s", finding.Predicate),
				},
				FullDescription: sarifText{
					Text: "Culprit compares independent descriptions of the same thing — " +
						"a route table and the calls made against it, an ORM model and " +
						"the migrations, a config key and its declaration. This rule " +
						"fires when two of them disagree.",
				},
				DefaultConfig: sarifRuleConfig{Level: sarifLevel(finding.Severity)},
				Properties:    map[string]string{"predicate": finding.Predicate},
			}
		}

		// Annotate the *lower-confidence* side. It is the one more likely
		// to be wrong, and more importantly it is usually the one the
		// author just changed — a PR comment on the call site that
		// stopped matching is actionable; one on the route table it
		// failed to match is a puzzle.
		location := finding.Right
		if finding.Left.Provenance.ConfidenceRank < finding.Right.Provenance.ConfidenceRank {
			location = finding.Left
		}
		// Phase 30: a CONFIGURED side has no file — its artefact is
		// "compose:orders-api" — and GitHub silently drops an annotation
		// whose path does not resolve. So an environment finding is
		// annotated on its INTENT side, the file in the repository that
		// makes the claim the environment fails, and an env-against-env
		// finding (no INTENT side at all) falls back to culprit.yaml.
		if location.Plane != model.PlaneIntent {
			switch {
			case finding.Left.Plane == model.PlaneIntent:
				location = finding.Left
			case finding.Right.Plane == model.PlaneIntent:
				location = finding.Right
			default:
				location = model.Fact{}
			}
		}

		results = append(results, sarifResult{
			RuleID: ruleID,
			Level:  sarifLevel(finding.Severity),
			Message: sarifText{Text: fmt.Sprintf("%s — %s (%s)",
				finding.Subject, finding.Explanation, finding.SeverityReason)},
			Locations:           []sarifLocation{sarifLocationFor(input.Root, location)},
			PartialFingerprints: map[string]string{"culpritDivergence/v1": finding.ID()},
		})
	}

	ruleList := make([]sarifRule, 0, len(rules))
	for _, rule := range rules {
		ruleList = append(ruleList, rule)
	}
	sort.Slice(ruleList, func(i, j int) bool { return ruleList[i].ID < ruleList[j].ID })

	run := sarifRun{
		Tool: sarifTool{Driver: sarifDriver{
			Name:           "Culprit",
			Version:        input.Version,
			InformationURI: "https://github.com/Josh-Heath123/Culprit",
			Rules:          ruleList,
		}},
		Results: results,
	}
	var notifications []sarifNotification
	for _, refusal := range allRefusals(input) {
		notifications = append(notifications, sarifNotification{
			Level: "warning",
			Message: sarifText{Text: fmt.Sprintf("Refused, not looked at: %s %s — %s",
				refusal.where, refusal.Check, refusal.Reason)},
		})
	}
	for _, skip := range allSkips(input) {
		notifications = append(notifications, sarifNotification{
			Level: "note",
			Message: sarifText{Text: fmt.Sprintf("Not checked: %s %s — %s",
				skip.Component, skip.Want, skip.Reason)},
		})
	}
	if len(notifications) > 0 {
		run.Invocations = []sarifInvocation{{
			ExecutionSuccessful: true, ToolExecutionNotifications: notifications,
		}}
	}

	document := sarifLog{
		Schema:  "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
		Version: "2.1.0",
		Runs:    []sarifRun{run},
	}

	encoder := json.NewEncoder(writer)
	encoder.SetIndent("", "  ")
	encoder.SetEscapeHTML(false)
	return encoder.Encode(document)
}

func sarifLocationFor(root string, fact model.Fact) sarifLocation {
	uri := fact.Provenance.Artefact
	if uri == "" {
		// SARIF requires a location. `culprit.yaml` is the honest
		// fallback: a fact with no artefact came from the model itself.
		uri = "culprit.yaml"
	}
	location := sarifLocation{PhysicalLocation: sarifPhysical{
		ArtifactLocation: sarifArtifact{URI: strings.TrimPrefix(uri, "./")},
	}}
	if line := lineFromLocator(fact.Provenance.Locator); line > 0 {
		location.PhysicalLocation.Region = &sarifRegion{StartLine: line}
	}
	return location
}

// lineFromLocator reads `L142` and `some_test:L88`, the two shapes the
// extractors emit. A JSON pointer (`$.paths./orders.post`) has no line,
// and SARIF is happy with a file-level annotation.
func lineFromLocator(locator string) int {
	if locator == "" {
		return 0
	}
	if index := strings.LastIndex(locator, "L"); index >= 0 {
		line := 0
		for _, character := range locator[index+1:] {
			if character < '0' || character > '9' {
				return 0
			}
			line = line*10 + int(character-'0')
		}
		return line
	}
	return 0
}

// --- junit ------------------------------------------------------------

type junitSuites struct {
	XMLName  xml.Name     `xml:"testsuites"`
	Name     string       `xml:"name,attr"`
	Tests    int          `xml:"tests,attr"`
	Failures int          `xml:"failures,attr"`
	Suites   []junitSuite `xml:"testsuite"`
}

type junitSuite struct {
	Name     string      `xml:"name,attr"`
	Tests    int         `xml:"tests,attr"`
	Failures int         `xml:"failures,attr"`
	Cases    []junitCase `xml:"testcase"`
}

type junitCase struct {
	Name      string        `xml:"name,attr"`
	ClassName string        `xml:"classname,attr"`
	Failure   *junitFailure `xml:"failure,omitempty"`
	Skipped   *junitSkipped `xml:"skipped,omitempty"`
}

type junitFailure struct {
	Message string `xml:"message,attr"`
	Type    string `xml:"type,attr"`
	Text    string `xml:",chardata"`
}

type junitSkipped struct {
	Message string `xml:"message,attr"`
}

// renderJUnit maps findings onto test cases.
//
// One case per finding rather than one per subject, and the skips become
// *skipped* cases — which is the honest mapping: a JUnit viewer showing
// "4 failures, 9 skipped" tells the reader both what is wrong and what
// was not looked at, which is the same pair the text report insists on.
func renderJUnit(writer io.Writer, input Input) error {
	open := openFindings(input.Result.Divergences)
	suite := junitSuite{Name: "culprit check"}

	for _, finding := range open {
		suite.Cases = append(suite.Cases, junitCase{
			Name:      finding.Subject + " " + finding.Predicate,
			ClassName: "culprit." + string(finding.Kind),
			Failure: &junitFailure{
				Message: finding.Explanation,
				Type:    string(finding.Severity),
				Text: fmt.Sprintf("expected: %s\nfound:    %s\nwhy %s: %s",
					describeSide(finding.Left), describeSide(finding.Right),
					finding.Severity, finding.SeverityReason),
			},
		})
		suite.Failures++
	}
	for _, refusal := range allRefusals(input) {
		suite.Cases = append(suite.Cases, junitCase{
			Name:      refusal.where + " " + refusal.Check,
			ClassName: "culprit.refused",
			Skipped:   &junitSkipped{Message: refusal.Reason},
		})
	}
	for _, skip := range allSkips(input) {
		suite.Cases = append(suite.Cases, junitCase{
			Name:      skip.Component + " " + skip.Want,
			ClassName: "culprit.not_checked",
			Skipped:   &junitSkipped{Message: skip.Reason},
		})
	}
	suite.Tests = len(suite.Cases)

	document := junitSuites{
		Name:     "culprit",
		Tests:    suite.Tests,
		Failures: suite.Failures,
		Suites:   []junitSuite{suite},
	}
	if _, err := io.WriteString(writer, xml.Header); err != nil {
		return err
	}
	encoder := xml.NewEncoder(writer)
	encoder.Indent("", "  ")
	if err := encoder.Encode(document); err != nil {
		return err
	}
	_, err := io.WriteString(writer, "\n")
	return err
}

// --- shared -----------------------------------------------------------

func openFindings(divergences []model.Divergence) []model.Divergence {
	open := make([]model.Divergence, 0, len(divergences))
	for _, finding := range divergences {
		if finding.Status != model.StatusSuppressed {
			open = append(open, finding)
		}
	}
	return open
}

func countSubjects(bundle model.CaptureBundle, more ...model.CaptureBundle) int {
	subjects := map[string]bool{}
	for _, each := range append([]model.CaptureBundle{bundle}, more...) {
		for _, fact := range each.Facts {
			subjects[fact.Subject] = true
		}
	}
	return len(subjects)
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

// KnownFormat reports whether Render understands a format name.
//
// Exported so `culprit check` can reject a bad `--format` before it
// spends thirty seconds extracting facts nobody will see. Rejecting late
// is not merely rude in CI; it hides the typo behind a wait long enough
// that the reader assumes the tool is broken.
func KnownFormat(name string) bool {
	switch name {
	case "text", "json", "sarif", "junit":
		return true
	default:
		return false
	}
}
