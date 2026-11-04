package model

import (
	"encoding/json"
	"strings"
	"testing"
)

type investigationCase struct {
	Why           string          `json:"why"`
	Investigation json.RawMessage `json:"investigation"`
}

type investigationFixture struct {
	Relations              []string            `json:"relations"`
	HypothesisStatuses     []string            `json:"hypothesis_statuses"`
	SymptomKinds           []string            `json:"symptom_kinds"`
	HypothesisKinds        []string            `json:"hypothesis_kinds"`
	InvestigationsAccepted []investigationCase `json:"investigations_accepted"`
	InvestigationsRejected []investigationCase `json:"investigations_rejected"`
}

// decodeInvestigation is every path an investigation from a file takes:
// decoding (which validates each fault edge) and then Validate.
func decodeInvestigation(raw json.RawMessage) (Investigation, error) {
	var inv Investigation
	if err := json.Unmarshal(raw, &inv); err != nil {
		return inv, err
	}
	return inv, inv.Validate()
}

func TestRelationAndStatusSetsMatchTheSharedFixture(t *testing.T) {
	fixture := readFixture[investigationFixture](t, "investigation_conformance.json")
	for _, name := range fixture.Relations {
		if !Relation(name).Valid() {
			t.Errorf("fixture relation %q is not a Go Relation", name)
		}
	}
	if len(fixture.Relations) != 3 {
		t.Errorf("fixture has %d relations, Go knows 3", len(fixture.Relations))
	}
	for _, name := range fixture.HypothesisStatuses {
		if !HypothesisStatus(name).Valid() {
			t.Errorf("fixture status %q is not a Go HypothesisStatus", name)
		}
	}
	if len(fixture.HypothesisStatuses) != 4 {
		t.Errorf("fixture has %d statuses, Go knows 4", len(fixture.HypothesisStatuses))
	}
	if strings.Join(fixture.HypothesisKinds, ",") != strings.Join(HypothesisKinds, ",") {
		t.Errorf("fixture hypothesis kinds %v, Go knows %v", fixture.HypothesisKinds, HypothesisKinds)
	}
	if len(fixture.SymptomKinds) != 3 {
		t.Errorf("fixture has %d symptom kinds, Go knows 3", len(fixture.SymptomKinds))
	}
}

func TestInvestigationsTheFixtureAcceptsAreAccepted(t *testing.T) {
	fixture := readFixture[investigationFixture](t, "investigation_conformance.json")
	for _, testCase := range fixture.InvestigationsAccepted {
		if _, err := decodeInvestigation(testCase.Investigation); err != nil {
			t.Errorf("%s: rejected: %v", testCase.Why, err)
		}
	}
}

func TestInvestigationsTheFixtureRejectsAreRejected(t *testing.T) {
	fixture := readFixture[investigationFixture](t, "investigation_conformance.json")
	for _, testCase := range fixture.InvestigationsRejected {
		if _, err := decodeInvestigation(testCase.Investigation); err == nil {
			t.Errorf("%s: accepted", testCase.Why)
		}
	}
}

// TestAFaultEdgeWithNoReadingCannotBeConstructed is §2.8's guarantee, on
// the constructor as well as on decode.
func TestAFaultEdgeWithNoReadingCannotBeConstructed(t *testing.T) {
	_, err := NewFaultEdge("component:orders", "config:orders/DATABASE_URL", RelationCausedBy)
	if err == nil || !strings.Contains(err.Error(), "cites no reading") {
		t.Fatalf("NewFaultEdge with no readings: err = %v, want a refusal", err)
	}
	edge, err := NewFaultEdge("component:orders", "config:orders/DATABASE_URL", RelationCausedBy, "r1")
	if err != nil || len(edge.EstablishedBy) != 1 {
		t.Fatalf("NewFaultEdge with a reading: %v, %+v", err, edge)
	}
	var decoded FaultEdge
	if err := json.Unmarshal([]byte(
		`{"from_subject":"component:orders","to_subject":"config:orders/DATABASE_URL",`+
			`"relation":"caused_by","established_by":[]}`), &decoded); err == nil {
		t.Fatal("an edge with no readings decoded from JSON")
	}
}
