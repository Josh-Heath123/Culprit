package model

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
)

type verificationCase struct {
	Why          string          `json:"why"`
	Verification json.RawMessage `json:"verification"`
}

type touchCase struct {
	Change  Change `json:"change"`
	Subject string `json:"subject"`
	Touches bool   `json:"touches"`
}

type verificationFixture struct {
	Verdicts              []string           `json:"verdicts"`
	ChangeKinds           []string           `json:"change_kinds"`
	Touches               []touchCase        `json:"touches"`
	VerificationsAccepted []verificationCase `json:"verifications_accepted"`
	VerificationsRejected []verificationCase `json:"verifications_rejected"`
}

func TestVerificationVocabularyMatchesTheSharedFixture(t *testing.T) {
	fixture := readFixture[verificationFixture](t, "verification_conformance.json")
	var verdicts, kinds []string
	for _, verdict := range VerificationVerdicts {
		verdicts = append(verdicts, string(verdict))
	}
	for _, kind := range ChangeKinds {
		kinds = append(kinds, string(kind))
	}
	if strings.Join(fixture.Verdicts, ",") != strings.Join(verdicts, ",") {
		t.Errorf("fixture verdicts %v, Go knows %v", fixture.Verdicts, verdicts)
	}
	if strings.Join(fixture.ChangeKinds, ",") != strings.Join(kinds, ",") {
		t.Errorf("fixture change kinds %v, Go knows %v", fixture.ChangeKinds, kinds)
	}
}

func TestWhatAChangeTouches(t *testing.T) {
	fixture := readFixture[verificationFixture](t, "verification_conformance.json")
	if len(fixture.Touches) == 0 {
		t.Fatal("the fixture has no touches cases")
	}
	for _, testCase := range fixture.Touches {
		if err := testCase.Change.Validate(); err != nil {
			t.Errorf("%+v: %v", testCase.Change, err)
		}
		if got := testCase.Change.Touches(testCase.Subject); got != testCase.Touches {
			t.Errorf("%s touches %s = %v, want %v", testCase.Change.Label(), testCase.Subject, got, testCase.Touches)
		}
	}
}

func TestVerificationsTheFixtureAcceptsAreAccepted(t *testing.T) {
	fixture := readFixture[verificationFixture](t, "verification_conformance.json")
	seen := map[VerificationVerdict]bool{}
	for _, testCase := range fixture.VerificationsAccepted {
		var verification Verification
		if err := json.Unmarshal(testCase.Verification, &verification); err != nil {
			t.Errorf("%s: rejected: %v", testCase.Why, err)
			continue
		}
		seen[verification.Verdict] = true
		// Encoding it again must succeed: MarshalJSON validates too.
		if _, err := json.Marshal(verification); err != nil {
			t.Errorf("%s: would not encode: %v", testCase.Why, err)
		}
	}
	for _, verdict := range VerificationVerdicts {
		if !seen[verdict] {
			t.Errorf("no accepted case has verdict %s", verdict)
		}
	}
}

func TestVerificationsTheFixtureRejectsAreRejected(t *testing.T) {
	fixture := readFixture[verificationFixture](t, "verification_conformance.json")
	for _, testCase := range fixture.VerificationsRejected {
		var verification Verification
		if err := json.Unmarshal(testCase.Verification, &verification); err == nil {
			t.Errorf("%s: accepted", testCase.Why)
		}
	}
}

// TestAVerifiedVerificationCannotBeConstructedWithAClauseFalse: through
// the constructor, the verdict is the record's, so asking for one cannot
// produce `verified`; and a literal claiming it is refused by Validate
// and by MarshalJSON, so it can never be written out.
func TestAVerifiedVerificationCannotBeConstructedWithAClauseFalse(t *testing.T) {
	run := func(verdict Verdict) Reading {
		return Reading{ProbeID: "probe.http.reachable", ProbeVersion: 1, Target: "component:inventory-service",
			Environment: "faults-order", Verdict: verdict, TakenAt: time.Unix(0, 0).UTC(), AgentID: "test",
			GrantsUsed: []string{"net.http.outbound"}}
	}
	before, after := "cap-before", "cap-after"
	stillFailing := []Rerun{{ReadingID: "r1", Was: VerdictFail, ProbeID: "probe.http.reachable",
		Target: "component:inventory-service", Environment: "faults-order",
		Runs: [2]Reading{run(VerdictFail), run(VerdictFail)}}}
	built, err := NewVerification("ver-1", "inv-1", "faults-order",
		[]Change{{Kind: ChangeCommit, Ref: "9f2c4e1"}}, stillFailing, &before, &after, nil, time.Now(),
		func(Judgement) string { return "test" })
	if err != nil {
		t.Fatal(err)
	}
	if built.Verdict != VerificationNotResolved {
		t.Fatalf("a still-failing reading judged %s", built.Verdict)
	}

	forged := built
	forged.Verdict, forged.FailingNowPasses = VerificationVerified, true
	if forged.Validate() == nil {
		t.Fatal("a verified verification with a still-failing reading validated")
	}
	if _, err := json.Marshal(forged); err == nil {
		t.Fatal("a verified verification with a still-failing reading was encoded")
	}
}
