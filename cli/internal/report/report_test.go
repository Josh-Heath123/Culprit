package report_test

import (
	"bytes"
	"encoding/json"
	"encoding/xml"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/diverge"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/report"
)

// The secret. Every rendered format is searched for it, and for each of
// its parts separately — a report that helpfully split a DSN into host,
// user and password fields would pass a test looking only for the whole
// string while leaking every piece of it.
const (
	secret   = "hunter2-do-not-print-me"
	dsn      = "postgresql://orders:" + secret + "@db.internal:5432/orders"
	username = "orders"
	host     = "db.internal"
)

func TestNoRenderedFormatCanPrintAConfigValue(t *testing.T) {
	// Phase 29 field 12, and the reason it is stated separately from
	// Phase 28's: a capture bundle is something a developer chooses to
	// attach to a bug report, but a *SARIF file* is uploaded to GitHub by
	// a CI job nobody re-reads, and appears on a pull request that may be
	// public. It is the single most likely place for a leak to become
	// permanent, so it is checked like the others and then some.
	input := leakyInput(t)

	for _, format := range []string{"text", "json", "sarif", "junit"} {
		t.Run(format, func(t *testing.T) {
			var buffer bytes.Buffer
			if err := report.Render(&buffer, format, input); err != nil {
				t.Fatalf("render: %v", err)
			}
			rendered := buffer.String()
			if rendered == "" {
				t.Fatal("nothing was rendered, so this test proves nothing")
			}
			for _, forbidden := range []string{secret, dsn, username + ":", host} {
				if strings.Contains(rendered, forbidden) {
					t.Errorf("%s output contains %q\n%s", format, forbidden, rendered)
				}
			}
		})
	}
}

// leakyInput is a report whose facts carry a real credential in every
// place one could hide: a config subject's key, a value, a shape, an
// explanation and a suppression reason.
func leakyInput(t *testing.T) report.Input {
	t.Helper()

	shape := model.ValueShape{
		Type:        model.TypeString,
		LengthClass: model.LengthMedium,
		Format:      model.FormatOpaque,
		Present:     true,
	}
	subject, err := model.BuildSubject(model.KindConfig, model.Parts{
		"component": "orders-api", "key": "DATABASE_URL",
	})
	if err != nil {
		t.Fatal(err)
	}

	left := model.Fact{
		Plane:      model.PlaneIntent,
		Subject:    subject,
		Predicate:  model.PredicateExampleShape,
		ValueShape: &shape,
		Provenance: model.Provenance{
			SourceKind: model.SourceSpec, Extractor: "culprit@dev",
			Artefact: "api/.env.example", Locator: "L4", ConfidenceRank: 80,
		},
	}
	// The right-hand fact carries the credential the way a defect would
	// actually put it there: as a plain `value`, on a config subject,
	// which `Fact.Validate` refuses — so it is constructed by hand.
	right := left
	right.ValueShape = nil
	right.Value = dsn
	right.Provenance.Extractor = "culprit-extract-python@0.1.0"
	right.Provenance.Artefact = "api/app/config.py"

	finding := model.Divergence{
		Kind:           model.KindIntentConflict,
		Subject:        subject,
		Predicate:      model.PredicateExampleShape,
		Left:           left,
		Right:          right,
		Severity:       model.SeverityBreaksRequestPath,
		SeverityReason: "orders-api is an entry point",
		Explanation:    "api/.env.example and api/app/config.py disagree about example_shape",
		Status:         model.StatusOpen,
		FirstSeenAt:    time.Unix(0, 0).UTC(),
	}

	return report.Input{
		Result: diverge.Result{
			Divergences: []model.Divergence{finding},
			Unverifiable: []diverge.Unverifiable{{
				Subject: subject, Source: "culprit@dev",
				Artefact: "api/.env.example", Reason: "only culprit@dev describes this",
			}},
		},
		Bundle: model.CaptureBundle{
			CaptureID: "abc123",
			Facts:     []model.Fact{left, right},
			Skipped: []model.Skip{{
				Component: "orders-api", Want: "db_schema",
				Reason: "no alembic versions/ directory found",
			}},
		},
		Version:          "test",
		ShowUnverifiable: true,
	}
}

func TestSARIFIsWellFormedAndCarriesLocations(t *testing.T) {
	var buffer bytes.Buffer
	if err := report.Render(&buffer, "sarif", leakyInput(t)); err != nil {
		t.Fatalf("render: %v", err)
	}

	var document struct {
		Version string `json:"version"`
		Runs    []struct {
			Tool struct {
				Driver struct {
					Name  string `json:"name"`
					Rules []struct {
						ID string `json:"id"`
					} `json:"rules"`
				} `json:"driver"`
			} `json:"tool"`
			Results []struct {
				RuleID    string `json:"ruleId"`
				Level     string `json:"level"`
				Locations []struct {
					PhysicalLocation struct {
						ArtifactLocation struct {
							URI string `json:"uri"`
						} `json:"artifactLocation"`
						Region *struct {
							StartLine int `json:"startLine"`
						} `json:"region"`
					} `json:"physicalLocation"`
				} `json:"locations"`
				PartialFingerprints map[string]string `json:"partialFingerprints"`
			} `json:"results"`
		} `json:"runs"`
	}
	if err := json.Unmarshal(buffer.Bytes(), &document); err != nil {
		t.Fatalf("SARIF is not valid JSON: %v", err)
	}

	if document.Version != "2.1.0" {
		t.Errorf("version is %q, GitHub reads 2.1.0", document.Version)
	}
	if len(document.Runs) != 1 || len(document.Runs[0].Results) != 1 {
		t.Fatalf("expected exactly one run with one result, got %+v", document.Runs)
	}
	result := document.Runs[0].Results[0]
	if result.Level != "error" {
		t.Errorf("a breaks_request_path finding rendered as %q, not error", result.Level)
	}
	if len(document.Runs[0].Tool.Driver.Rules) != 1 ||
		document.Runs[0].Tool.Driver.Rules[0].ID != result.RuleID {
		// A result whose ruleId names no rule is dropped by GitHub with no
		// error shown anywhere — the failure this assertion exists for.
		t.Errorf("result ruleId %q has no matching rule", result.RuleID)
	}
	if len(result.Locations) != 1 {
		t.Fatal("a SARIF result with no location is not annotated on a pull request")
	}
	location := result.Locations[0].PhysicalLocation
	if location.ArtifactLocation.URI != "api/app/config.py" {
		t.Errorf("annotated %q; the lower-confidence side is api/app/config.py",
			location.ArtifactLocation.URI)
	}
	if result.PartialFingerprints["culpritDivergence/v1"] == "" {
		t.Error("no fingerprint: GitHub cannot tell a recurring finding from a new one")
	}
}

func TestJUnitReportsSkipsAsSkipped(t *testing.T) {
	var buffer bytes.Buffer
	if err := report.Render(&buffer, "junit", leakyInput(t)); err != nil {
		t.Fatalf("render: %v", err)
	}
	var suites struct {
		Failures int `xml:"failures,attr"`
		Suites   []struct {
			Cases []struct {
				ClassName string    `xml:"classname,attr"`
				Failure   *struct{} `xml:"failure"`
				Skipped   *struct{} `xml:"skipped"`
			} `xml:"testcase"`
		} `xml:"testsuite"`
	}
	if err := xml.Unmarshal(buffer.Bytes(), &suites); err != nil {
		t.Fatalf("JUnit XML does not parse: %v", err)
	}
	if suites.Failures != 1 {
		t.Errorf("failures=%d, expected 1", suites.Failures)
	}
	var skipped int
	for _, suite := range suites.Suites {
		for _, testCase := range suite.Cases {
			if testCase.Skipped != nil {
				skipped++
			}
		}
	}
	if skipped != 1 {
		// "Not checked" has to survive into every format. A JUnit report
		// showing one failure and nothing else would tell the reader the
		// rest was fine, when part of it was never looked at.
		t.Errorf("%d skipped cases, expected 1 for the unchecked want", skipped)
	}
}

func TestSuppressedFindingsAreNotRenderedAsFindings(t *testing.T) {
	input := leakyInput(t)
	input.Result.Divergences[0].Status = model.StatusSuppressed
	input.Result.Divergences[0].SuppressedBy = "tracked in ORD-4412"

	var text bytes.Buffer
	if err := report.Render(&text, "text", input); err != nil {
		t.Fatalf("render: %v", err)
	}
	if !strings.Contains(text.String(), "No divergences") {
		t.Errorf("a suppressed finding was reported as a finding:\n%s", text.String())
	}
	if !strings.Contains(text.String(), "1 finding(s) suppressed") {
		t.Errorf("a suppressed finding vanished instead of being counted:\n%s", text.String())
	}

	var sarif bytes.Buffer
	if err := report.Render(&sarif, "sarif", input); err != nil {
		t.Fatalf("render: %v", err)
	}
	if strings.Contains(sarif.String(), "\"results\": [\n") {
		t.Error("a suppressed finding became a pull-request annotation")
	}
}

func TestUnknownFormatIsRefused(t *testing.T) {
	if report.KnownFormat("yaml") {
		t.Error("KnownFormat accepted a format Render does not implement")
	}
	if err := report.Render(&bytes.Buffer{}, "yaml", report.Input{}); err == nil {
		t.Error("Render accepted an unknown format")
	}
}
