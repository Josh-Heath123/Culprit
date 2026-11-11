package model

import "regexp"

// Free text — a skip reason, a refusal reason, a meta value — that crosses
// a trust boundary: read out of a capture envelope somebody else wrote,
// or rendered into a report somebody else will read.
//
// Standing invariant 11: error text is output, and "redaction bolted on
// per call site will always have one more call site". The CLI builds its
// own reasons from closed vocabulary, so for text *it* wrote this changes
// nothing. It exists for the text it did not write: a capture envelope is
// a file, anyone can hand-edit one and re-hash it, and the Phase 30 phase
// audit put a DSN into a refusal reason and watched `culprit diff` print
// it. So there is one function that decides whether text looks like a
// credential, used both to refuse such an envelope when it is opened and
// to redact such text wherever a report renders it.
//
// Unanchored, unlike ClassifyFormat: a credential inside a sentence is
// still a credential. The same six patterns the value classifier and the
// manifest loader use, so "looks like a credential" means one thing.
var credentialPattern = regexp.MustCompile(
	`(?i)[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@` + // user:pass@ in a URL
		// ?password=… — consuming the value, so redaction removes it and
		// does not leave it standing after the marker.
		`|[a-z][a-z0-9+.-]*://\S*[?&](password|passwd|secret|token|api[_-]?key)=[^&\s]*` +
		`|-----BEGIN [A-Z ]*PRIVATE KEY-----(?s:.*?)(-----END [A-Z ]*PRIVATE KEY-----|$)` +
		`|\bAKIA[0-9A-Z]{16}\b` +
		`|\bgh[pousr]_[A-Za-z0-9]{20,}` +
		`|\bsk-[A-Za-z0-9]{20,}` +
		// Anthropic's keys (sk-ant-api03-...): hyphens break the pattern
		// above. Phase 35 part 2 made this a key the control plane holds.
		`|\bsk-ant-[A-Za-z0-9_-]{20,}` +
		`|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.`)

// LooksLikeCredential reports whether free text carries something
// credential-shaped anywhere in it.
func LooksLikeCredential(text string) bool {
	return credentialPattern.MatchString(text)
}

// RedactCredentials replaces anything credential-shaped with a marker.
// For rendering: a report must show that a reason existed even when it
// cannot show what it said.
func RedactCredentials(text string) string {
	return credentialPattern.ReplaceAllString(text, "[redacted]")
}
