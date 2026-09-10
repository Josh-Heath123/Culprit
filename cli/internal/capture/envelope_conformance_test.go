package capture

import (
	"crypto/ed25519"
	"encoding/json"
	"flag"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The envelope Go seals must be the envelope Python opens.
//
// shared/tests/capture_envelope_conformance.json is a real signed
// envelope, sealed here with a fixed Ed25519 key, and verified by
// api/tests/test_capture_envelope.py through app/model/envelope.py — the
// same arrangement the subject and identity fixtures use, for the same
// reason. A signature scheme that one language produces and the other
// cannot check would fail only in production, on the first upload.
//
// Ed25519 is deterministic, so the fixture is byte-stable: this test
// fails if Go's output drifts from the committed file.
// `go test ./internal/capture -run TestEnvelopeConformance -update-envelope`
// rewrites it — then read the diff.

var updateEnvelope = flag.Bool("update-envelope", false, "rewrite shared/tests/capture_envelope_conformance.json")

// conformanceSeed is a fixed, public test key. It signs nothing but this
// fixture.
var conformanceSeed = []byte("culprit-envelope-conformance-key")

func conformanceBundle() model.CaptureBundle {
	at := time.Date(2026, 9, 10, 12, 0, 0, 0, time.UTC)
	environment := "staging"
	captureID := "5b2f4c9e-7d1a-5e3b-8c4d-0a1b2c3d4e5f"
	provenance := model.Provenance{
		SourceKind: model.SourceIntrospection, Extractor: "culprit@conformance",
		Artefact: "compose:orders-api", ConfidenceRank: model.RankRuntimeIntrospection,
	}
	shape := model.ShapeOfString("postgresql://orders:pw@db:5432/orders")
	fact := func(subject, predicate string, value any, grant string) model.Fact {
		return model.Fact{Plane: model.PlaneConfigured, Subject: subject, Predicate: predicate,
			Value: value, GrantRef: grant, Environment: environment, Provenance: provenance,
			CapturedAt: at, CaptureID: captureID}
	}
	shapeFact := fact("config:orders-api/DATABASE_URL", model.PredicateValueShape, nil, "config.read.names")
	shapeFact.ValueShape = &shape
	return model.CaptureBundle{
		Protocol: model.ExtractorProtocolVersion, Plane: model.PlaneConfigured,
		Environment: &environment, Extractor: "culprit@conformance", CaptureID: captureID,
		StartedAt: at, FinishedAt: &at,
		Facts: []model.Fact{
			fact("config:orders-api/DATABASE_URL", model.PredicateExists, true, "config.read.names"),
			shapeFact,
			fact("config:orders-api/LOG_LEVEL", PredicateValue, "debug", "config.read.values:orders-api/LOG_LEVEL"),
			fact("image:orders-api", PredicateDigest, "sha256:"+
				"1111111111111111111111111111111111111111111111111111111111111111", "deploy.metadata.read"),
			fact("schema:orders-api-db/public.orders", model.PredicateColumns,
				[]string{"id", "total_cents"}, "db.metadata.read"),
		},
		Skipped: []model.Skip{},
		Meta:    map[string]string{"adapter": "compose"},
		Grants: []model.Grant{
			{Capability: "config.read.names", Used: true},
			{Capability: "config.read.values", Allow: []string{"orders-api/LOG_LEVEL"}, Used: true},
			{Capability: "db.metadata.read", Used: true},
			{Capability: "deploy.metadata.read", Used: true},
		},
		Refused: []model.Refusal{{
			Capability: "net.dns.resolve", Component: "orders-api", Check: CheckDNS,
			Reason: "net.dns.resolve is not granted",
		}},
	}
}

func TestEnvelopeConformance(t *testing.T) {
	key := ed25519.NewKeyFromSeed(conformanceSeed)
	envelope, err := Seal(conformanceBundle(), key)
	if err != nil {
		t.Fatal(err)
	}
	rendered, err := json.MarshalIndent(envelope, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	rendered = append(rendered, '\n')

	path := filepath.Join("..", "..", "..", "shared", "tests", "capture_envelope_conformance.json")
	if *updateEnvelope {
		if err := os.WriteFile(path, rendered, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	committed, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("the fixture is missing (run with -update-envelope): %v", err)
	}
	if string(committed) != string(rendered) {
		t.Fatalf("Seal's output has drifted from the committed fixture %s.\n"+
			"If the change is intended, rerun with -update-envelope and read the diff:\n"+
			"api/tests/test_capture_envelope.py verifies that file with the Python implementation.", path)
	}
	if _, err := Open(envelope); err != nil {
		t.Fatalf("Go cannot open its own conformance envelope: %v", err)
	}
}
