package capture

import (
	"crypto/ed25519"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"os"
	"strconv"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The signed envelope (field 7): "A capture is a signed, timestamped
// bundle of CONFIGURED facts plus the grant set that produced it."
//
// # Why the payload is bytes, not an embedded object
//
// A signature is over bytes. If the envelope embedded the capture as a
// JSON object, a verifier would have to reproduce the signer's exact
// serialisation to check it — and the verifier is Python (the API) while
// the signer is Go, and the two do not agree about how to print a
// timestamp, let alone a float. Every signing scheme that has tried
// "canonicalise, then verify" has a history of the two sides
// canonicalising differently.
//
// So the payload is carried as base64 of the exact bytes that were
// hashed and signed, the way DSSE (in-toto, Sigstore) does it, and the
// signature is over DSSE's pre-authentication encoding of those bytes and
// their type. Verification is "decode, hash, check" in any language, with
// no canonicalisation step to get wrong. The cost is that the envelope is
// not readable at a glance; `culprit env capture --format text` is.
//
// # What a signature does and does not prove
//
// An Ed25519 signature over the payload proves the bundle — facts,
// grants, refusals, timestamps — has not changed since whoever held that
// private key signed it. It does not prove *who* that was: the public key
// travels in the envelope, so anyone can sign with a fresh key. Pinning
// which key ids you trust is the reader's decision and is not made here.
// An unsigned envelope still carries the SHA-256, which catches
// corruption and nothing else. Both limits are in docs/LIMITS.md.

// PayloadType names the payload, and is part of what is signed, so a
// signature over one kind of payload cannot be replayed as another.
const PayloadType = "application/vnd.culprit.capture+json; version=1"

// Envelope is what `culprit env capture` writes and `POST /captures`
// accepts.
type Envelope struct {
	PayloadType string      `json:"payload_type"`
	Payload     string      `json:"payload"`
	SHA256      string      `json:"sha256"`
	Signatures  []Signature `json:"signatures"`
}

// Signature is one Ed25519 signature.
type Signature struct {
	// KeyID is the first 16 hex characters of the SHA-256 of the public
	// key: short enough to read, long enough not to collide by accident.
	KeyID     string `json:"keyid"`
	PublicKey string `json:"public_key"`
	Sig       string `json:"sig"`
}

// pae is DSSE's pre-authentication encoding: the signature covers the
// payload *and* its declared type, length-prefixed so neither can be
// shifted into the other.
func pae(payloadType string, payload []byte) []byte {
	return []byte("DSSEv1 " + strconv.Itoa(len(payloadType)) + " " + payloadType + " " +
		strconv.Itoa(len(payload)) + " " + string(payload))
}

// KeyID derives a key id from a public key.
func KeyID(public ed25519.PublicKey) string {
	sum := sha256.Sum256(public)
	return hex.EncodeToString(sum[:])[:16]
}

// Seal serialises a bundle into an envelope, signing it when a key is
// given.
func Seal(bundle model.CaptureBundle, key ed25519.PrivateKey) (Envelope, error) {
	payload, err := json.Marshal(bundle)
	if err != nil {
		return Envelope{}, fmt.Errorf("could not encode the capture")
	}
	sum := sha256.Sum256(payload)
	envelope := Envelope{
		PayloadType: PayloadType,
		Payload:     base64.StdEncoding.EncodeToString(payload),
		SHA256:      hex.EncodeToString(sum[:]),
		Signatures:  []Signature{},
	}
	if key != nil {
		public := key.Public().(ed25519.PublicKey)
		envelope.Signatures = append(envelope.Signatures, Signature{
			KeyID:     KeyID(public),
			PublicKey: base64.StdEncoding.EncodeToString(public),
			Sig:       base64.StdEncoding.EncodeToString(ed25519.Sign(key, pae(PayloadType, payload))),
		})
	}
	return envelope, nil
}

// Verified is what opening an envelope established.
type Verified struct {
	Bundle model.CaptureBundle
	// SignedBy lists the key ids whose signatures verified. Empty for an
	// unsigned envelope, which is legitimate and is not an error.
	SignedBy []string
}

// Open checks an envelope and returns the bundle inside it.
//
// Refuses — never warns and continues — on a digest mismatch or a
// signature that does not verify. A capture that has been altered is not
// a slightly less trustworthy capture; it is a claim about an environment
// that nobody made.
func Open(envelope Envelope) (Verified, error) {
	if envelope.PayloadType != PayloadType {
		return Verified{}, fmt.Errorf("not a culprit capture (payload_type is not %q)", PayloadType)
	}
	payload, err := base64.StdEncoding.DecodeString(envelope.Payload)
	if err != nil {
		return Verified{}, fmt.Errorf("the capture's payload is not valid base64")
	}
	sum := sha256.Sum256(payload)
	if hex.EncodeToString(sum[:]) != envelope.SHA256 {
		return Verified{}, fmt.Errorf("the capture's sha256 does not match its payload: " +
			"it has been altered or corrupted since it was sealed")
	}
	verified := Verified{}
	for index, signature := range envelope.Signatures {
		public, err := base64.StdEncoding.DecodeString(signature.PublicKey)
		if err != nil || len(public) != ed25519.PublicKeySize {
			return Verified{}, fmt.Errorf("signatures.%d: not an Ed25519 public key", index)
		}
		sig, err := base64.StdEncoding.DecodeString(signature.Sig)
		if err != nil || !ed25519.Verify(public, pae(envelope.PayloadType, payload), sig) {
			return Verified{}, fmt.Errorf("signatures.%d: does not verify — the capture "+
				"has been altered since it was signed", index)
		}
		if KeyID(public) != signature.KeyID {
			return Verified{}, fmt.Errorf("signatures.%d: keyid does not match its public key", index)
		}
		verified.SignedBy = append(verified.SignedBy, signature.KeyID)
	}
	if err := json.Unmarshal(payload, &verified.Bundle); err != nil {
		// The decode error is not wrapped: it can quote the offending
		// input, and the input is a capture of an environment.
		return Verified{}, fmt.Errorf("the capture's payload is not a capture bundle")
	}
	if verified.Bundle.Plane != model.PlaneConfigured {
		return Verified{}, fmt.Errorf("the envelope does not hold a CONFIGURED capture")
	}
	for index, fact := range verified.Bundle.Facts {
		if err := fact.Validate(); err != nil {
			return Verified{}, fmt.Errorf("facts.%d: failed validation", index)
		}
	}
	// The free text in an envelope is text somebody else wrote. The CLI's
	// own captures build every reason from closed vocabulary, so one that
	// carries a connection string or a key was put there by hand — and
	// `culprit diff` would print it. Refused here, by field and index and
	// never by content (invariant 11); the report redacts as well, as the
	// second line of defence. Found by the Phase 30 phase audit, which put
	// a DSN in `refused[0].reason`, re-hashed the envelope, and watched it
	// come out of the text report.
	for index, skip := range verified.Bundle.Skipped {
		if model.LooksLikeCredential(skip.Reason) {
			return Verified{}, fmt.Errorf("skipped.%d.reason carries credential-shaped text", index)
		}
	}
	for index, refusal := range verified.Bundle.Refused {
		if model.LooksLikeCredential(refusal.Reason) {
			return Verified{}, fmt.Errorf("refused.%d.reason carries credential-shaped text", index)
		}
	}
	for name, value := range verified.Bundle.Meta {
		if model.LooksLikeCredential(value) {
			return Verified{}, fmt.Errorf("meta.%s carries credential-shaped text", name)
		}
	}
	return verified, nil
}

// LoadSigningKey reads a PKCS#8 PEM Ed25519 private key, the format
// `openssl genpkey -algorithm ed25519` writes.
//
// Errors name the file and never its content — it is a private key.
func LoadSigningKey(path string) (ed25519.PrivateKey, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("cannot read the signing key %s", path)
	}
	block, _ := pem.Decode(data)
	if block == nil {
		return nil, fmt.Errorf("%s is not a PEM file", path)
	}
	parsed, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		return nil, fmt.Errorf("%s is not a PKCS#8 private key", path)
	}
	key, ok := parsed.(ed25519.PrivateKey)
	if !ok {
		return nil, fmt.Errorf("%s is not an Ed25519 key", path)
	}
	return key, nil
}

// ReadEnvelope loads an envelope from a file and opens it.
func ReadEnvelope(path string) (Verified, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Verified{}, fmt.Errorf("cannot read %s", path)
	}
	var envelope Envelope
	if err := json.Unmarshal(data, &envelope); err != nil {
		return Verified{}, fmt.Errorf("%s is not a capture envelope", path)
	}
	verified, err := Open(envelope)
	if err != nil {
		return Verified{}, fmt.Errorf("%s: %w", path, err)
	}
	return verified, nil
}
