// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package extract

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
	"unicode/utf8"
)

// F44-090. A .env.example key whose bytes are not UTF-8 became a subject
// with U+FFFD in it, config:svc/��BADKEY, which no environment
// can match. It is named as unreadable, its bytes escaped, and never
// becomes a subject; the file's other keys are read as before.
func TestAKeyThatIsNotUTF8IsNamedNotASubject(t *testing.T) {
	root := t.TempDir()
	body := []byte("GOOD=1\n\xff\xfeBADKEY=2\n")
	if err := os.WriteFile(filepath.Join(root, ".env.example"), body, 0o644); err != nil {
		t.Fatal(err)
	}
	ctx := captureContext{Component: "svc", Root: root, CapturedAt: time.Now(),
		CaptureID: "00000000-0000-5000-8000-000000000000", Extractor: "test"}
	facts, skips := readDotenv(ctx)
	for _, fact := range facts {
		if !utf8.ValidString(fact.Subject) || strings.ContainsRune(fact.Subject, utf8.RuneError) ||
			strings.Contains(fact.Subject, "BADKEY") {
			t.Errorf("a key that is not UTF-8 became a subject: %q", fact.Subject)
		}
	}
	if len(facts) != 2 {
		t.Errorf("GOOD was not read: %d facts", len(facts))
	}
	named := false
	for _, skip := range skips {
		if strings.Contains(skip.Reason, `\xff\xfeBADKEY`) && strings.Contains(skip.Reason, ".env.example") &&
			utf8.ValidString(skip.Reason) {
			named = true
		}
	}
	if !named {
		t.Errorf("the key was not named, escaped: %+v", skips)
	}
}
