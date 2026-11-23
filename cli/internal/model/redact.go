// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package model

import (
	"regexp"
	"strings"
)

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
// still a credential.
//
// Phase 44 batch 1 (F44-002): the pattern's coverage is exactly the rows of
// shared/tests/redaction_conformance.json, which Python's redaction.py is
// held to as well; a shape not there is not promised (docs/SECURITY.md §8).
//
// A key whose name has a credential word as one of its parts (DB_PASSWORD,
// x-auth-token, spring.datasource.password, "api_key"), in any case. The
// key and its separator are kept and only the value goes, so a subject or a
// probe id is never removed with it. A colon counts only when quoted
// (JSON), or for a YAML key: no dots, starting the text or a line, or
// after {, a comma, (, [ or a quote, and followed by whitespace. So
// `auth:a->b/audience` is a subject and `probe.auth.token_shape: no token
// ...` a probe id, not keys.
const (
	credentialWord = `(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key` +
		`|private[_-]?key|credentials?|auth)`
	credentialKey   = `\b(?:[a-z0-9]+[_.-])*` + credentialWord + `(?:[_.-][a-z0-9]+)*`
	yamlKey         = `(?:^|[\n{,(\['"])[ \t]*(?:[a-z0-9]+[_-])*` + credentialWord + `(?:[_-][a-z0-9]+)*`
	credentialValue = `(?:'[^']*'|"[^"]*"|[^\s&;,'"}]+)`
	// A Bearer or Basic credential: a run with an upper-case letter, a
	// digit or base64 punctuation after its third character, so "Bearer
	// token" and "basic authentication" stay words.
	opaqueCredential = `[a-z0-9._~+/-]{3,}(?-i:[A-Z0-9+/=])[a-z0-9._~+/=-]*`
)

var credentialPattern = regexp.MustCompile(
	`(?i)(?P<key>` + credentialKey + `(?:\s*=\s*|["']\s*:\s*))` + credentialValue +
		`|(?P<yaml>` + yamlKey + `\s*:\s+)` + credentialValue +
		`|(?P<authz>\b(?:proxy-)?authorization["']?\s*[=:]\s*)(?:[a-z]+\s+)?[^\s,;'"]+` +
		`|(?P<scheme>\b(?:bearer|basic)\s+)` + opaqueCredential +
		// URL userinfo, an empty user included (redis://:pw@), the
		// password running to the last @ before the host.
		`|[a-z][a-z0-9+.-]*://[^/\s:@]*:[^\s/?#]*@` +
		`|-----BEGIN [A-Z ]*PRIVATE KEY-----(?s:.*?)(?:-----END [A-Z ]*PRIVATE KEY-----|\z)` +
		// Provider formats.
		`|\bAKIA[0-9A-Z]{16}\b` +
		`|\bgh[pousr]_[A-Za-z0-9]{20,}` +
		`|\bgithub_pat_[A-Za-z0-9_]{20,}` +
		`|\bglpat-[A-Za-z0-9_-]{20,}` +
		`|\bsk_(?:live|test)_[A-Za-z0-9]{10,}` +
		`|\bAIza[0-9A-Za-z_-]{35}` +
		`|\bsk-[A-Za-z0-9]{20,}` +
		// Anthropic's keys (sk-ant-api03-...): hyphens break the pattern
		// above. Phase 35 part 2 made this a key the control plane holds.
		`|\bsk-ant-[A-Za-z0-9_-]{20,}` +
		// A JWT, its signature included.
		`|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*` +
		`|\bxox[a-z]-[A-Za-z0-9-]{10,}` +
		`|\bxapp-[0-9]+-[A-Za-z0-9-]{10,}` +
		// user:pass@host with no scheme (Phase 37 part 1).
		`|\b[A-Za-z0-9._%+-]+:[^\s/@:]+@` +
		// SQL's own form: CREATE/ALTER ROLE or USER ... PASSWORD '...',
		// which pg_stat_statements keeps verbatim for a utility statement.
		`|\bPASSWORD\s+'[^']*'`)

// The groups whose text is kept before the marker: a key and its
// separator (a YAML key with the character before it), an Authorization
// header's name, the word Bearer or Basic.
var keptGroups = func() []int {
	var kept []int
	for index, name := range credentialPattern.SubexpNames() {
		if name == "key" || name == "yaml" || name == "authz" || name == "scheme" {
			kept = append(kept, index)
		}
	}
	return kept
}()

// LooksLikeCredential reports whether free text carries something
// credential-shaped anywhere in it.
func LooksLikeCredential(text string) bool {
	return credentialPattern.MatchString(text)
}

// RedactCredentials replaces anything credential-shaped with a marker.
// For rendering: a report must show that a reason existed even when it
// cannot show what it said.
func RedactCredentials(text string) string {
	matches := credentialPattern.FindAllStringSubmatchIndex(text, -1)
	if matches == nil {
		return text
	}
	var out strings.Builder
	last := 0
	for _, match := range matches {
		out.WriteString(text[last:match[0]])
		for _, group := range keptGroups {
			if start := match[2*group]; start >= 0 {
				out.WriteString(text[start:match[2*group+1]])
				break
			}
		}
		out.WriteString("[redacted]")
		last = match[1]
	}
	out.WriteString(text[last:])
	return out.String()
}
