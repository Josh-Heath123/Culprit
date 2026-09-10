package model

import "testing"

// The Go half of the divergence-identity conformance fixture.
//
// `shared/tests/test_divergence_identity.py` reads the same file. The two
// implementations exist because the CLI computes an identity before
// upload and the API computes one on receipt, and if they ever disagree
// the result is not an error — it is a duplicate row in the history
// table that nobody notices, forever. The same arrangement, and the same
// reasoning, as `subject_conformance.json`.

type divergenceIdentityFixture struct {
	Cases []struct {
		Name           string `json:"name"`
		Subject        string `json:"subject"`
		Predicate      string `json:"predicate"`
		LeftExtractor  string `json:"left_extractor"`
		LeftArtefact   string `json:"left_artefact"`
		RightExtractor string `json:"right_extractor"`
		RightArtefact  string `json:"right_artefact"`
		// Optional: present only on the Phase 30 cases. Absent decodes to
		// "", which is exactly an INTENT fact's environment.
		LeftEnvironment  string `json:"left_environment"`
		RightEnvironment string `json:"right_environment"`
		Identity         string `json:"identity"`
	} `json:"cases"`
}

func TestDivergenceIdentityMatchesTheSharedFixture(t *testing.T) {
	fixture := readFixture[divergenceIdentityFixture](t, "divergence_identity_conformance.json")
	if len(fixture.Cases) == 0 {
		t.Fatal("the conformance fixture is empty, so this test proves nothing")
	}

	// Every identity in the fixture must be distinct, or the fixture
	// cannot detect the collision it was extended to cover.
	seen := map[string]string{}
	for _, testCase := range fixture.Cases {
		if other, clash := seen[testCase.Identity]; clash {
			t.Errorf("%q and %q share an identity: %q",
				other, testCase.Name, testCase.Identity)
		}
		seen[testCase.Identity] = testCase.Name
	}

	for _, testCase := range fixture.Cases {
		t.Run(testCase.Name, func(t *testing.T) {
			divergence := Divergence{
				Subject:   testCase.Subject,
				Predicate: testCase.Predicate,
				Left: Fact{Environment: testCase.LeftEnvironment, Provenance: Provenance{
					Extractor: testCase.LeftExtractor,
					Artefact:  testCase.LeftArtefact}},
				Right: Fact{Environment: testCase.RightEnvironment, Provenance: Provenance{
					Extractor: testCase.RightExtractor,
					Artefact:  testCase.RightArtefact}},
			}
			if got := divergence.ID(); got != testCase.Identity {
				t.Errorf("ID() = %q\n  fixture = %q", got, testCase.Identity)
			}
		})
	}
}
