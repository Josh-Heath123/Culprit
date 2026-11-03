package model

import (
	"encoding/json"
	"testing"
)

// The Go half of shared/tests/reading_conformance.json. The Python half is
// shared/tests/test_readings.py.
//
// Same reasoning as subject_conformance.json: two implementations
// reconciled after the fact agree on whatever they both happened to do,
// not on what was specified. A verdict the CLI can emit and the API
// refuses is a reading that vanishes between the probe that took it and
// the database meant to keep it.

type verdictCase struct {
	Name        string `json:"name"`
	NeedsReason bool   `json:"needs_reason"`
}

type effectCase struct {
	Name    string `json:"name"`
	Allowed bool   `json:"allowed"`
}

type rejectedManifest struct {
	Why      string        `json:"why"`
	Manifest ProbeManifest `json:"manifest"`
}

type acceptedReading struct {
	Why     string  `json:"why"`
	Reading Reading `json:"reading"`
}

type readingFixture struct {
	Verdicts          []verdictCase      `json:"verdicts"`
	Effects           []effectCase       `json:"effects"`
	Costs             []string           `json:"costs"`
	ManifestsAccepted []ProbeManifest    `json:"manifests_accepted"`
	ManifestsRejected []rejectedManifest `json:"manifests_rejected"`
	ReadingsAccepted  []acceptedReading  `json:"readings_accepted"`
	ReadingsRejected  []acceptedReading  `json:"readings_rejected"`
}

func TestVerdictSetMatchesTheSharedFixture(t *testing.T) {
	fixture := readFixture[readingFixture](t, "reading_conformance.json")

	known := map[Verdict]bool{
		VerdictPass: true, VerdictFail: true,
		VerdictInconclusive: true, VerdictRefused: true,
	}
	if len(fixture.Verdicts) != len(known) {
		t.Fatalf("fixture has %d verdicts, Go knows %d",
			len(fixture.Verdicts), len(known))
	}
	for _, testCase := range fixture.Verdicts {
		verdict := Verdict(testCase.Name)
		if !verdict.Valid() {
			t.Errorf("fixture verdict %q is not valid in Go", testCase.Name)
		}
		if verdict.NeedsReason() != testCase.NeedsReason {
			t.Errorf("verdict %q: NeedsReason() = %v, fixture says %v",
				testCase.Name, verdict.NeedsReason(), testCase.NeedsReason)
		}
	}
}

func TestEffectSetMatchesTheSharedFixture(t *testing.T) {
	fixture := readFixture[readingFixture](t, "reading_conformance.json")

	for _, testCase := range fixture.Effects {
		manifest := ProbeManifest{
			ID: "probe.test.case", Version: 1,
			Effect: Effect(testCase.Name), TimeoutMS: 1000,
		}
		err := manifest.Validate()
		if testCase.Allowed && err != nil {
			t.Errorf("effect %q should be allowed, got %v", testCase.Name, err)
		}
		if !testCase.Allowed && err == nil {
			t.Errorf("effect %q should be refused, was accepted", testCase.Name)
		}
	}
}

func TestAcceptedManifestsValidate(t *testing.T) {
	fixture := readFixture[readingFixture](t, "reading_conformance.json")

	if len(fixture.ManifestsAccepted) == 0 {
		t.Fatal("fixture has no accepted manifests")
	}
	for _, manifest := range fixture.ManifestsAccepted {
		if err := manifest.Validate(); err != nil {
			t.Errorf("manifest %q should validate: %v", manifest.ID, err)
		}
	}
}

func TestRejectedManifestsAreRefused(t *testing.T) {
	fixture := readFixture[readingFixture](t, "reading_conformance.json")

	if len(fixture.ManifestsRejected) == 0 {
		t.Fatal("fixture has no rejected manifests")
	}
	for _, testCase := range fixture.ManifestsRejected {
		if err := testCase.Manifest.Validate(); err == nil {
			t.Errorf("manifest %q should be refused (%s), was accepted",
				testCase.Manifest.ID, testCase.Why)
		}
	}
}

func TestAcceptedReadingsValidate(t *testing.T) {
	fixture := readFixture[readingFixture](t, "reading_conformance.json")

	if len(fixture.ReadingsAccepted) == 0 {
		t.Fatal("fixture has no accepted readings")
	}
	for _, testCase := range fixture.ReadingsAccepted {
		if err := testCase.Reading.Validate(); err != nil {
			t.Errorf("reading (%s) should validate: %v", testCase.Why, err)
		}
	}
}

func TestRejectedReadingsAreRefused(t *testing.T) {
	fixture := readFixture[readingFixture](t, "reading_conformance.json")

	if len(fixture.ReadingsRejected) == 0 {
		t.Fatal("fixture has no rejected readings")
	}
	for _, testCase := range fixture.ReadingsRejected {
		if err := testCase.Reading.Validate(); err == nil {
			t.Errorf("reading should be refused (%s), was accepted", testCase.Why)
		}
	}
}

// TestNoProbeMayDeclareMutate asserts the rule directly as well as through
// the fixture, because it is the one a future reader is most likely to
// want to find by name.
func TestNoProbeMayDeclareMutate(t *testing.T) {
	manifest := ProbeManifest{
		ID: "probe.db.truncate", Version: 1,
		Effect: EffectMutate, TimeoutMS: 1000,
	}
	if err := manifest.Validate(); err == nil {
		t.Fatal("effect: mutate was accepted; §2.6 says no exceptions in this plan")
	}
}

// TestReadingRoundTripsThroughJSON guards the wire shape the API is handed.
func TestReadingRoundTripsThroughJSON(t *testing.T) {
	fixture := readFixture[readingFixture](t, "reading_conformance.json")

	for _, testCase := range fixture.ReadingsAccepted {
		encoded, err := json.Marshal(testCase.Reading)
		if err != nil {
			t.Fatalf("marshalling (%s): %v", testCase.Why, err)
		}
		var decoded Reading
		if err := json.Unmarshal(encoded, &decoded); err != nil {
			t.Fatalf("unmarshalling (%s): %v", testCase.Why, err)
		}
		if err := decoded.Validate(); err != nil {
			t.Errorf("round-tripped reading (%s) no longer validates: %v",
				testCase.Why, err)
		}
		if decoded.Verdict != testCase.Reading.Verdict ||
			decoded.Target != testCase.Reading.Target {
			t.Errorf("round trip changed the reading (%s)", testCase.Why)
		}
	}
}
