// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package render

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// A bundle as `culprit intent` builds it when an extractor fails: its skip
// reason is the extractor's first line of stderr, written by whoever wrote
// the extractor or the application it imported (F44-001).
func leakyBundle() model.CaptureBundle {
	return model.CaptureBundle{
		Protocol:  1,
		Plane:     model.Plane("INTENT"),
		Extractor: "culprit",
		CaptureID: "cap-1",
		StartedAt: time.Date(2026, 11, 23, 0, 0, 0, 0, time.UTC),
		Facts:     []model.Fact{},
		Skipped: []model.Skip{{
			Want:      "routes",
			Component: "svc",
			Extractor: "leak",
			Reason: `extractor "leak" exited 3: connect failed: ` +
				`postgresql://app:LeakPw77@db.internal/app DB_PASSWORD=LeakPw88`,
		}},
	}
}

func TestSkipReasonsAreRedactedInText(t *testing.T) {
	var out bytes.Buffer
	if err := Text(&out, leakyBundle()); err != nil {
		t.Fatal(err)
	}
	text := out.String()
	for _, secret := range []string{"LeakPw77", "LeakPw88"} {
		if strings.Contains(text, secret) {
			t.Errorf("text output carries %s:\n%s", secret, text)
		}
	}
	// The reason is still there to read, with its credential removed.
	if !strings.Contains(text, "DB_PASSWORD=[redacted]") || !strings.Contains(text, "db.internal/app") {
		t.Errorf("the skip reason was not kept, redacted:\n%s", text)
	}
}

func TestSkipReasonsAreRedactedInJSON(t *testing.T) {
	var out bytes.Buffer
	if err := JSON(&out, leakyBundle()); err != nil {
		t.Fatal(err)
	}
	for _, secret := range []string{"LeakPw77", "LeakPw88"} {
		if strings.Contains(out.String(), secret) {
			t.Errorf("JSON output carries %s:\n%s", secret, out.String())
		}
	}
	var decoded model.CaptureBundle
	if err := json.Unmarshal(out.Bytes(), &decoded); err != nil {
		t.Fatal(err)
	}
	if len(decoded.Skipped) != 1 || !strings.Contains(decoded.Skipped[0].Reason, "[redacted]") {
		t.Errorf("the skip did not survive, redacted: %+v", decoded.Skipped)
	}
}

// Rendering never changes the bundle it was given: the caller's copy keeps
// what it held.
func TestRenderingDoesNotChangeTheBundle(t *testing.T) {
	bundle := leakyBundle()
	before := bundle.Skipped[0].Reason
	var out bytes.Buffer
	if err := JSON(&out, bundle); err != nil {
		t.Fatal(err)
	}
	if err := Text(&out, bundle); err != nil {
		t.Fatal(err)
	}
	if bundle.Skipped[0].Reason != before {
		t.Errorf("the bundle was changed: %q", bundle.Skipped[0].Reason)
	}
}

func TestTextShowsFactsAndSkips(t *testing.T) {
	bundle := leakyBundle()
	bundle.Skipped[0].Reason = "no openapi.json found"
	var out bytes.Buffer
	if err := Text(&out, bundle); err != nil {
		t.Fatal(err)
	}
	text := out.String()
	for _, want := range []string{"INTENT capture cap-1", "0 fact(s), 1 skipped", "No facts.", "SKIPPED (1)", "no openapi.json found"} {
		if !strings.Contains(text, want) {
			t.Errorf("text output lacks %q:\n%s", want, text)
		}
	}
}
