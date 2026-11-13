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

// againstManifest is a reading checked against a probe's declared
// verdicts (Q31): the manifest by id from manifests_accepted, the reading
// readings_accepted[0] with this verdict.
type againstManifest struct {
	Why      string  `json:"why"`
	Accepted bool    `json:"accepted"`
	Manifest string  `json:"manifest"`
	Verdict  Verdict `json:"verdict"`
	ProbeID  string  `json:"probe_id"`
}

type readingFixture struct {
	Verdicts          []verdictCase      `json:"verdicts"`
	Effects           []effectCase       `json:"effects"`
	Costs             []string           `json:"costs"`
	ManifestsAccepted []ProbeManifest    `json:"manifests_accepted"`
	ManifestsRejected []rejectedManifest `json:"manifests_rejected"`
	ReadingsAccepted  []acceptedReading  `json:"readings_accepted"`
	ReadingsRejected  []acceptedReading  `json:"readings_rejected"`
	AgainstManifests  []againstManifest  `json:"readings_against_manifests"`
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
			Verdicts: []Verdict{VerdictPass, VerdictInconclusive},
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

// TestReadingsAreHeldToTheirProbesDeclaredVerdicts (Q31): a reading whose
// verdict its probe did not declare is refused, as readings.py refuses it.
func TestReadingsAreHeldToTheirProbesDeclaredVerdicts(t *testing.T) {
	fixture := readFixture[readingFixture](t, "reading_conformance.json")
	manifests := map[string]ProbeManifest{}
	for _, manifest := range fixture.ManifestsAccepted {
		manifests[manifest.ID] = manifest
	}
	if len(fixture.AgainstManifests) == 0 {
		t.Fatal("fixture has no readings against manifests")
	}
	for _, testCase := range fixture.AgainstManifests {
		manifest, ok := manifests[testCase.Manifest]
		if !ok {
			t.Fatalf("%s: no accepted manifest %q", testCase.Why, testCase.Manifest)
		}
		reading := fixture.ReadingsAccepted[0].Reading
		reading.ProbeID = testCase.Manifest
		if testCase.ProbeID != "" {
			reading.ProbeID = testCase.ProbeID
		}
		reading.Verdict = testCase.Verdict
		reading.Reason = "as the fixture says"
		reading.GrantsUsed = nil
		err := reading.ValidateFor(manifest)
		if testCase.Accepted && err != nil {
			t.Errorf("%s: refused: %v", testCase.Why, err)
		}
		if !testCase.Accepted && err == nil {
			t.Errorf("%s: accepted", testCase.Why)
		}
	}
}
