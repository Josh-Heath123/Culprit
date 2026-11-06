package agentauth

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// The signing contract, held to shared/tests/agent_signing_conformance.json
// (Phase 33 part 2): every case behaves as written here and in
// api/app/agents/signing.py.
//
// The fixture's keys come from fixed seeds named in the file, so either
// language can sign as well as verify. They are test keys: nothing
// accepts them anywhere but these tests.

const fixtureFile = "agent_signing_conformance.json"

type fixtureKey struct {
	Seed      string `json:"seed_sha256_of"`
	PublicKey string `json:"public_key"`
	Revoked   bool   `json:"revoked"`
}

type fixtureCase struct {
	Why        string   `json:"why"`
	AgentID    string   `json:"agent_id"`
	Method     string   `json:"method"`
	Path       string   `json:"path"`
	Body       string   `json:"body"`
	Timestamp  int64    `json:"timestamp"`
	Nonce      string   `json:"nonce"`
	Signature  string   `json:"signature"`
	SignedBy   string   `json:"signed_by"`
	Now        int64    `json:"now"`
	SeenNonces []string `json:"seen_nonces"`
	Canonical  string   `json:"canonical,omitempty"`
	Expect     string   `json:"expect"`
}

type fixture struct {
	Why            []string              `json:"why"`
	Scheme         string                `json:"scheme"`
	MaxSkewSeconds int64                 `json:"max_skew_seconds"`
	Keys           map[string]fixtureKey `json:"keys"`
	Cases          []fixtureCase         `json:"cases"`
}

func fixturePath() string {
	return filepath.Join("..", "..", "..", "shared", "tests", fixtureFile)
}

// keyFrom derives a test key: the seed is SHA-256 of a label.
func keyFrom(label string) ed25519.PrivateKey {
	seed := sha256.Sum256([]byte(label))
	return ed25519.NewKeyFromSeed(seed[:])
}

func buildFixture() fixture {
	labels := map[string]string{
		"agent-a":       "culprit test key: agent-a (never used outside tests)",
		"agent-b":       "culprit test key: agent-b (never used outside tests)",
		"agent-revoked": "culprit test key: agent-revoked (never used outside tests)",
	}
	keys := map[string]fixtureKey{}
	for name, label := range labels {
		keys[name] = fixtureKey{
			Seed:      label,
			PublicKey: base64.StdEncoding.EncodeToString(keyFrom(label).Public().(ed25519.PublicKey)),
			Revoked:   name == "agent-revoked",
		}
	}
	const now int64 = 1_793_000_000
	const nonce = "0123456789abcdef0123456789abcdef"
	body := `{"readings":[]}`
	valid := Request{Method: "POST", Path: "/readings", Body: []byte(body), Timestamp: now, Nonce: nonce, AgentID: "agent-a"}

	sign := func(by string, r Request) string { return Sign(keyFrom(labels[by]), r) }
	cases := []fixtureCase{}
	add := func(why string, r Request, signedBy string, signature string, at int64, seen []string, expect string) {
		if signature == "" {
			signature = sign(signedBy, r)
		}
		if seen == nil {
			seen = []string{}
		}
		cases = append(cases, fixtureCase{
			Why: why, AgentID: r.AgentID, Method: r.Method, Path: r.Path, Body: string(r.Body),
			Timestamp: r.Timestamp, Nonce: r.Nonce, Signature: signature, SignedBy: signedBy,
			Now: at, SeenNonces: seen, Expect: expect,
		})
	}

	add("a valid request: known key, fresh, unseen nonce, signature over exactly this request", valid, "agent-a", "", now, nil, "accept")
	cases[0].Canonical = string(Canonical(valid))
	get := valid
	get.Method, get.Path, get.Body = "GET", "/agents/me/audit/head", nil
	add("a valid request with no body: the digest is SHA-256 of nothing", get, "agent-a", "", now, nil, "accept")
	add("valid at exactly max_skew_seconds old", valid, "agent-a", "", now+300, nil, "accept")

	tampered := valid
	tampered.Body = []byte(`{"readings":[{"agent_id":"agent-b"}]}`)
	add("a tampered body: signed over another body", tampered, "agent-a", sign("agent-a", valid), now, nil, "refuse")
	moved := valid
	moved.Path = "/investigations"
	add("a changed path: signed for /readings, sent to /investigations", moved, "agent-a", sign("agent-a", valid), now, nil, "refuse")
	method := valid
	method.Method = "PUT"
	add("a changed method", method, "agent-a", sign("agent-a", valid), now, nil, "refuse")
	add("a stale timestamp: one second past max_skew_seconds", valid, "agent-a", "", now+301, nil, "refuse")
	add("a timestamp from the future, past max_skew_seconds", valid, "agent-a", "", now-301, nil, "refuse")
	add("a replayed nonce: the control plane has seen it", valid, "agent-a", "", now, []string{nonce}, "refuse")
	add("the wrong key: agent-b's signature on a request naming agent-a", valid, "agent-b", "", now, nil, "refuse")
	revoked := valid
	revoked.AgentID = "agent-revoked"
	add("a revoked key: the signature is its own and valid, and still refused", revoked, "agent-revoked", "", now, nil, "refuse")
	unknown := valid
	unknown.AgentID = "agent-unknown"
	add("an unknown agent id", unknown, "agent-a", "", now, nil, "refuse")
	badNonce := valid
	badNonce.Nonce = "not-a-nonce"
	add("a malformed nonce, correctly signed", badNonce, "agent-a", "", now, nil, "refuse")
	add("a signature that is not base64 of 64 bytes", valid, "agent-a", "c2lnbmF0dXJl", now, nil, "refuse")

	return fixture{
		Why: []string{
			"The agent request-signing contract (DIAGNOSTIC_PLAN.md Phase 33), read by cli/internal/agentauth and api/app/agents/signing.py.",
			"canonical = scheme, METHOD, path, hex sha256(body), timestamp, nonce, agent id — one per line, joined by \\n. The signature is Ed25519 over it, base64.",
			"Keys are derived from seeds: seed = sha256(seed_sha256_of). They are test keys and are accepted nowhere else.",
			"Regenerate with CULPRIT_WRITE_SIGNING_FIXTURE=1 go test ./internal/agentauth — and read the diff.",
		},
		Scheme: Scheme, MaxSkewSeconds: int64(MaxSkew / time.Second), Keys: keys, Cases: cases,
	}
}

func TestWriteTheSigningFixture(t *testing.T) {
	if os.Getenv("CULPRIT_WRITE_SIGNING_FIXTURE") != "1" {
		t.Skip("set CULPRIT_WRITE_SIGNING_FIXTURE=1 to regenerate the fixture")
	}
	encoded, err := json.MarshalIndent(buildFixture(), "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(fixturePath(), append(encoded, '\n'), 0o644); err != nil {
		t.Fatal(err)
	}
}

func readFixture(t *testing.T) fixture {
	t.Helper()
	data, err := os.ReadFile(fixturePath())
	if err != nil {
		t.Fatal(err)
	}
	var parsed fixture
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatal(err)
	}
	return parsed
}

func TestEverySigningCaseBehavesAsWritten(t *testing.T) {
	shared := readFixture(t)
	if shared.Scheme != Scheme || shared.MaxSkewSeconds != int64(MaxSkew/time.Second) {
		t.Fatalf("fixture scheme %q / skew %d, Go has %q / %v", shared.Scheme, shared.MaxSkewSeconds, Scheme, MaxSkew)
	}
	if len(shared.Cases) < 10 {
		t.Fatalf("the fixture has %d cases; it cannot be asserting the contract", len(shared.Cases))
	}
	accepts, refuses := 0, 0
	for _, testCase := range shared.Cases {
		request := Request{Method: testCase.Method, Path: testCase.Path, Body: []byte(testCase.Body),
			Timestamp: testCase.Timestamp, Nonce: testCase.Nonce, AgentID: testCase.AgentID}
		var key *Key
		if stored, ok := shared.Keys[testCase.AgentID]; ok {
			public, err := base64.StdEncoding.DecodeString(stored.PublicKey)
			if err != nil {
				t.Fatal(err)
			}
			key = &Key{Public: public, Revoked: stored.Revoked}
		}
		seen := func(nonce string) bool {
			for _, s := range testCase.SeenNonces {
				if s == nonce {
					return true
				}
			}
			return false
		}
		got := Decide(key, request, testCase.Signature, time.Unix(testCase.Now, 0), seen)
		want := testCase.Expect == "accept"
		if got != want {
			t.Errorf("%s: accepted=%v, want %s", testCase.Why, got, testCase.Expect)
		}
		if want {
			accepts++
		} else {
			refuses++
		}
		if testCase.Canonical != "" && string(Canonical(request)) != testCase.Canonical {
			t.Errorf("%s: canonical\n%q\nwant\n%q", testCase.Why, Canonical(request), testCase.Canonical)
		}
	}
	if accepts == 0 || refuses == 0 {
		t.Errorf("%d accepted and %d refused: the fixture must exercise both", accepts, refuses)
	}
}

// Ed25519 is deterministic, so Go must produce every valid signature in
// the fixture byte for byte from the named seed: the canonical form is
// the same, not merely compatible.
func TestGoReproducesTheFixturesSignatures(t *testing.T) {
	shared := readFixture(t)
	for _, testCase := range shared.Cases {
		if testCase.Expect != "accept" {
			continue
		}
		key := keyFrom(shared.Keys[testCase.SignedBy].Seed)
		request := Request{Method: testCase.Method, Path: testCase.Path, Body: []byte(testCase.Body),
			Timestamp: testCase.Timestamp, Nonce: testCase.Nonce, AgentID: testCase.AgentID}
		if got := Sign(key, request); got != testCase.Signature {
			t.Errorf("%s: Go signs %s, the fixture says %s", testCase.Why, got, testCase.Signature)
		}
	}
}

func TestNoncesAreFreshAndWellFormed(t *testing.T) {
	seen := map[string]bool{}
	for index := 0; index < 64; index++ {
		nonce, err := NewNonce()
		if err != nil {
			t.Fatal(err)
		}
		if !nonceShape.MatchString(nonce) || seen[nonce] {
			t.Fatalf("nonce %q is malformed or repeated", nonce)
		}
		seen[nonce] = true
	}
}
