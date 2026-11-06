// Package agentauth is how an agent proves who it is to the control plane
// (docs/DIAGNOSTIC_PLAN.md Phase 33, "Per-agent credentials are Ed25519
// keys that sign every request, not mutual TLS").
//
// Every request an agent sends after pairing carries four headers — its
// id, a timestamp, a nonce and an Ed25519 signature — over a canonical
// form of the request: the scheme, the method, the path relative to the
// API's root, the SHA-256 of the body, the timestamp, the nonce and the
// agent id, one per line. The control plane recomputes the canonical form
// from what it actually received, so a header cannot vouch for a body or
// a path it did not come with. It refuses a request whose timestamp is
// more than MaxSkew from its clock, whose nonce it has seen, whose key is
// unknown or revoked, or whose signature does not verify.
//
// shared/tests/agent_signing_conformance.json holds both halves to one
// definition: this package and api/app/agents/signing.py read it.
//
// Pure: no socket, no clock of its own, no randomness except NewNonce.
package agentauth

import (
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Scheme is the first line of every canonical request. A new scheme is a
// new line here and in the Python half, never a reinterpretation.
const Scheme = "culprit-agent-v1"

// MaxSkew is how far a request's timestamp may be from the control
// plane's clock, either way. Nonces are kept at least this long.
const MaxSkew = 300 * time.Second

// The headers a signed request carries.
const (
	HeaderAgent     = "X-Culprit-Agent"
	HeaderTimestamp = "X-Culprit-Timestamp"
	HeaderNonce     = "X-Culprit-Nonce"
	HeaderSignature = "X-Culprit-Signature"
)

var (
	nonceShape   = regexp.MustCompile(`^[0-9a-f]{32}$`)
	agentIDShape = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`)
)

// Request is everything the signature covers.
type Request struct {
	Method string
	// Path is relative to the control plane's API root, with its query
	// string if it has one: "/agents/me/tasks/claim".
	Path      string
	Body      []byte
	Timestamp int64
	Nonce     string
	AgentID   string
}

// Canonical is the byte string that is signed.
func Canonical(r Request) []byte {
	digest := sha256.Sum256(r.Body)
	return []byte(strings.Join([]string{
		Scheme,
		strings.ToUpper(r.Method),
		r.Path,
		hex.EncodeToString(digest[:]),
		strconv.FormatInt(r.Timestamp, 10),
		r.Nonce,
		r.AgentID,
	}, "\n"))
}

// WellFormed checks the parts of a request that are not cryptographic:
// a nonce of 32 lowercase hex digits, an agent id, a path from the root.
func WellFormed(r Request) error {
	switch {
	case !nonceShape.MatchString(r.Nonce):
		return fmt.Errorf("the nonce must be 32 lowercase hex digits")
	case !agentIDShape.MatchString(r.AgentID):
		return fmt.Errorf("the agent id is not well formed")
	case !strings.HasPrefix(r.Path, "/"):
		return fmt.Errorf("the path must start at the API root")
	case r.Timestamp <= 0:
		return fmt.Errorf("the timestamp must be positive")
	}
	return nil
}

// Sign returns the base64 signature of r's canonical form.
func Sign(key ed25519.PrivateKey, r Request) string {
	return base64.StdEncoding.EncodeToString(ed25519.Sign(key, Canonical(r)))
}

// Verify reports whether signature is key's over r's canonical form.
func Verify(key ed25519.PublicKey, r Request, signature string) bool {
	raw, err := base64.StdEncoding.DecodeString(signature)
	if err != nil || len(raw) != ed25519.SignatureSize || len(key) != ed25519.PublicKeySize {
		return false
	}
	return ed25519.Verify(key, Canonical(r), raw)
}

// Fresh reports whether a timestamp is within MaxSkew of now.
func Fresh(timestamp int64, now time.Time) bool {
	skew := now.Unix() - timestamp
	if skew < 0 {
		skew = -skew
	}
	return skew <= int64(MaxSkew/time.Second)
}

// NewNonce returns 128 random bits as 32 lowercase hex digits.
func NewNonce() (string, error) {
	raw := make([]byte, 16)
	if _, err := rand.Read(raw); err != nil {
		return "", err
	}
	return hex.EncodeToString(raw), nil
}

// Headers signs r and returns the four headers that carry it.
func Headers(key ed25519.PrivateKey, r Request) map[string]string {
	return map[string]string{
		HeaderAgent:     r.AgentID,
		HeaderTimestamp: strconv.FormatInt(r.Timestamp, 10),
		HeaderNonce:     r.Nonce,
		HeaderSignature: Sign(key, r),
	}
}

// Key is what the control plane knows about one agent's key.
type Key struct {
	Public  ed25519.PublicKey
	Revoked bool
}

// Decide is the control plane's whole decision, as the conformance
// fixture states it: known and unrevoked key, well formed, fresh,
// signature valid, nonce unseen. It returns no reason on purpose — the
// API's refusal does not say which check failed.
func Decide(key *Key, r Request, signature string, now time.Time, seen func(nonce string) bool) bool {
	if key == nil || key.Revoked {
		return false
	}
	if WellFormed(r) != nil || !Fresh(r.Timestamp, now) {
		return false
	}
	if !Verify(key.Public, r, signature) {
		return false
	}
	return !seen(r.Nonce)
}
