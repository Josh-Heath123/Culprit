// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package model

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestRedactCredentials(t *testing.T) {
	for _, testCase := range []struct {
		name, text, secret string
	}{
		{"inline user:pass", "could not reach postgresql://orders:hunter2-r@db/orders today", "hunter2-r"},
		{"query-string password", "dsn https://db.example.com/x?user=a&password=hunter2-q&ssl=1", "hunter2-q"},
		{"a PEM block", "key -----BEGIN PRIVATE KEY-----\nMIIEvQhunter2pem\n-----END PRIVATE KEY----- end", "hunter2pem"},
		{"a provider key", "token sk-ABCDEFGHIJKLMNOPQRSTUVWX leaked", "sk-ABCDEFGHIJKLMNOPQRSTUVWX"},
		{"an anthropic key", "key sk-ant-api03-ABCDEFGHIJ_KLMNOPQRST-uv leaked", "ABCDEFGHIJ_KLMNOPQRST"},
		{"a JWT", "bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.sig", "eyJhbGciOiJIUzI1NiJ9"},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			if !LooksLikeCredential(testCase.text) {
				t.Fatalf("not recognised as credential-shaped: %q", testCase.text)
			}
			redacted := RedactCredentials(testCase.text)
			if strings.Contains(redacted, testCase.secret) || !strings.Contains(redacted, "[redacted]") {
				t.Errorf("RedactCredentials(%q) = %q", testCase.text, redacted)
			}
		})
	}
	for _, clean := range []string{
		"no docker-compose file found",
		"postgresql+asyncpg://localhost:5432/culprit-intent-placeholder",
		"the values of 7 key(s) were not captured — only their shape",
	} {
		if LooksLikeCredential(clean) {
			t.Errorf("an ordinary reason was treated as a credential: %q", clean)
		}
	}
}

// TestRedactionHoldsToTheSharedCases: the Go half of
// shared/tests/redaction_conformance.json, which redaction.py reads too.
func TestRedactionHoldsToTheSharedCases(t *testing.T) {
	fixture := readFixture[struct {
		Cases []struct {
			Why        string `json:"why"`
			Text       string `json:"text"`
			Redacted   string `json:"redacted"`
			Credential bool   `json:"credential"`
		} `json:"cases"`
	}](t, "redaction_conformance.json")
	if len(fixture.Cases) == 0 {
		t.Fatal("the redaction fixture is empty")
	}
	for _, c := range fixture.Cases {
		if got := RedactCredentials(c.Text); got != c.Redacted {
			t.Errorf("%s: %q, want %q", c.Why, got, c.Redacted)
		}
		if got := LooksLikeCredential(c.Text); got != c.Credential {
			t.Errorf("%s: looks like a credential = %v, want %v", c.Why, got, c.Credential)
		}
	}
}

// TestRedactionKeepsWhatMustSurvive: the fixture's "survive" rows come back
// unchanged and are not credential-shaped (a subject or a digest is never
// redacted), and its "over_redacted" rows are redacted exactly as accepted
// there (Phase 44 batch 1, decision 2).
func TestRedactionKeepsWhatMustSurvive(t *testing.T) {
	fixture := readFixture[struct {
		Survive []struct {
			Why  string `json:"why"`
			Text string `json:"text"`
		} `json:"survive"`
		OverRedacted []struct {
			Why      string `json:"why"`
			Text     string `json:"text"`
			Redacted string `json:"redacted"`
		} `json:"over_redacted"`
	}](t, "redaction_conformance.json")
	if len(fixture.Survive) == 0 || len(fixture.OverRedacted) == 0 {
		t.Fatal("the redaction fixture has no survive or over_redacted rows")
	}
	for _, c := range fixture.Survive {
		if got := RedactCredentials(c.Text); got != c.Text {
			t.Errorf("%s: %q became %q", c.Why, c.Text, got)
		}
		if LooksLikeCredential(c.Text) {
			t.Errorf("%s: %q looks like a credential", c.Why, c.Text)
		}
	}
	for _, c := range fixture.OverRedacted {
		if got := RedactCredentials(c.Text); got != c.Redacted {
			t.Errorf("%s: %q, want %q", c.Why, got, c.Redacted)
		}
	}
}

// TestRedactReadingHoldsToTheSharedCases: the Go half of
// reading_conformance.json's "readings_redacted" (F44-004), which
// shared/tests/test_readings.py reads too.
func TestRedactReadingHoldsToTheSharedCases(t *testing.T) {
	fixture := readFixture[struct {
		Cases []struct {
			Why              string         `json:"why"`
			Measured         map[string]any `json:"measured"`
			Expected         map[string]any `json:"expected"`
			RedactedMeasured map[string]any `json:"redacted_measured"`
			RedactedExpected map[string]any `json:"redacted_expected"`
		} `json:"readings_redacted"`
	}](t, "reading_conformance.json")
	if len(fixture.Cases) == 0 {
		t.Fatal("reading_conformance.json has no readings_redacted cases")
	}
	for _, c := range fixture.Cases {
		got := RedactReading(Reading{Measured: c.Measured, Expected: c.Expected})
		for _, pair := range []struct {
			name      string
			got, want map[string]any
		}{{"measured", got.Measured, c.RedactedMeasured}, {"expected", got.Expected, c.RedactedExpected}} {
			gotJSON, _ := json.Marshal(pair.got)
			wantJSON, _ := json.Marshal(pair.want)
			if string(gotJSON) != string(wantJSON) {
				t.Errorf("%s: %s = %s, want %s", c.Why, pair.name, gotJSON, wantJSON)
			}
		}
	}
}

// TestRedactReadingWalksTypedStringLists: Go's probes put []string, not
// []any, into measured — a response's body keys, a token's audiences — and
// the walk must reach them as they are typed (F44-004), keeping the type.
func TestRedactReadingWalksTypedStringLists(t *testing.T) {
	reading := Reading{Measured: map[string]any{
		"fields":    []string{"id", "postgresql://u:Hunter7pw@h/d"},
		"audiences": []string{"DB_PASSWORD=Hunter8pw"},
		"nested":    []map[string]any{{"dsn": "redis://:Hunter9pw@r"}},
	}}
	redacted := RedactReading(reading)
	encoded, _ := json.Marshal(redacted.Measured)
	for _, secret := range []string{"Hunter7pw", "Hunter8pw", "Hunter9pw"} {
		if strings.Contains(string(encoded), secret) {
			t.Errorf("measured still carries %s: %s", secret, encoded)
		}
	}
	if fields, ok := redacted.Measured["fields"].([]string); !ok || fields[0] != "id" {
		t.Errorf("fields lost its type or its order: %#v", redacted.Measured["fields"])
	}
	if reading.Measured["fields"].([]string)[1] != "postgresql://u:Hunter7pw@h/d" {
		t.Error("the caller's reading was changed")
	}
}
