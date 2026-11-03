package report

import (
	"bytes"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

func readingAt(verdict model.Verdict, probeID, reason string) model.Reading {
	return model.Reading{
		ProbeID:      probeID,
		ProbeVersion: 1,
		Target:       "component:orders-api",
		Environment:  "staging",
		Verdict:      verdict,
		Reason:       reason,
		TakenAt:      time.Date(2026, 9, 12, 10, 0, 0, 0, time.UTC),
		AgentID:      "culprit-cli",
	}
}

func TestReadingsReportLeadsWithFailures(t *testing.T) {
	var buffer bytes.Buffer
	err := RenderReadings(&buffer, []model.Reading{
		readingAt(model.VerdictPass, "probe.net.dns_resolve", ""),
		readingAt(model.VerdictFail, "probe.net.tcp_connect", "connection refused"),
		readingAt(model.VerdictRefused, "probe.db.connect", "db.metadata.read is not granted"),
		readingAt(model.VerdictInconclusive, "probe.http.reachable", "answered 404"),
	})
	if err != nil {
		t.Fatalf("RenderReadings: %v", err)
	}
	output := buffer.String()

	// A wall of green is what hides the other three, so the order is part
	// of the contract rather than a formatting preference.
	positions := []string{"FAILING", "INCONCLUSIVE", "REFUSED", "PASSING"}
	previous := -1
	for _, heading := range positions {
		at := strings.Index(output, heading)
		if at < 0 {
			t.Fatalf("%s section is missing:\n%s", heading, output)
		}
		if at < previous {
			t.Errorf("%s appears out of order:\n%s", heading, output)
		}
		previous = at
	}
	if !strings.Contains(output, "1 failing, 1 inconclusive, 1 refused, 1 passing") {
		t.Errorf("summary line is wrong:\n%s", output)
	}
}

// TestAReadingsReportNeverPrintsACredential is the renderer half of
// standing invariant 11.
//
// A built-in probe builds its reason from closed vocabulary and cannot
// produce this. A third-party probe is a manifest plus an exec procedure,
// and this is the point where its output becomes visible to a human — so
// the redaction is applied here, at one place, rather than trusted
// upstream.
func TestAReadingsReportNeverPrintsACredential(t *testing.T) {
	secret := "postgresql://admin:hunter2@db.internal:5432/orders"

	var buffer bytes.Buffer
	err := RenderReadings(&buffer, []model.Reading{
		{
			ProbeID: "probe.vendor.custom", ProbeVersion: 1,
			Target: "component:orders-api", Environment: "staging",
			Verdict: model.VerdictFail,
			Reason:  "could not connect using " + secret,
			Measured: map[string]any{
				"dsn": secret,
			},
			Evidence: []model.Evidence{
				{Kind: "connection", Value: secret, Redacted: true},
			},
			TakenAt: time.Now(), AgentID: "plugin",
		},
	})
	if err != nil {
		t.Fatalf("RenderReadings: %v", err)
	}

	output := buffer.String()
	if strings.Contains(output, "hunter2") {
		t.Errorf("the rendered report contains a password:\n%s", output)
	}
	if strings.Contains(output, secret) {
		t.Errorf("the rendered report contains a connection string:\n%s", output)
	}
}

func TestMeasuredKeysAreOrderedSoReportsDiffCleanly(t *testing.T) {
	reading := readingAt(model.VerdictPass, "probe.net.tcp_connect", "")
	reading.Measured = map[string]any{"zebra": 1, "alpha": 2, "monkey": 3}

	var first string
	for run := 0; run < 5; run++ {
		var buffer bytes.Buffer
		if err := RenderReadings(&buffer, []model.Reading{reading}); err != nil {
			t.Fatalf("RenderReadings: %v", err)
		}
		if run == 0 {
			first = buffer.String()
			continue
		}
		if buffer.String() != first {
			t.Fatal("two renders of the same reading differ; `culprit` output is diffed")
		}
	}
	if !strings.Contains(first, "alpha=2 monkey=3 zebra=1") {
		t.Errorf("measured keys are not sorted:\n%s", first)
	}
}

func TestAnEmptyProbeRunSaysSo(t *testing.T) {
	var buffer bytes.Buffer
	if err := RenderReadings(&buffer, nil); err != nil {
		t.Fatalf("RenderReadings: %v", err)
	}
	if !strings.Contains(buffer.String(), "No probes ran") {
		t.Errorf("an empty run should say so, got %q", buffer.String())
	}
}
