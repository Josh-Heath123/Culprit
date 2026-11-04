package model

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// The Go side of the shared conformance fixtures (§2.3).
//
// These files are in shared/tests/ and are read by the Python
// implementation's tests too. That is the whole point: two
// implementations reconciled after the fact agree on whatever they both
// happened to do, not on what was specified. A case is added to the
// fixture, never to one language's test file.
//
// The path is relative and crosses out of the Go module on purpose.
// Copying the fixtures into cli/testdata/ would produce two files that
// silently drift, which is the exact failure mode the fixture exists to
// prevent — so a missing file is a hard failure here, not a skip.

func fixturePath(t *testing.T, name string) string {
	t.Helper()
	path := filepath.Join("..", "..", "..", "shared", "tests", name)
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("shared conformance fixture %s is missing (%v). It is the single "+
			"source of truth for both implementations and must not be copied or "+
			"skipped past.", path, err)
	}
	return path
}

func readFixture[T any](t *testing.T, name string) T {
	t.Helper()
	data, err := os.ReadFile(fixturePath(t, name))
	if err != nil {
		t.Fatalf("reading %s: %v", name, err)
	}
	var parsed T
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("parsing %s: %v", name, err)
	}
	return parsed
}

// --- canonicalisation --------------------------------------------------

type canonicalCase struct {
	Source     string `json:"source"`
	Canonical  string `json:"canonical"`
	Convention string `json:"convention"`
}

type canonicalFixture struct {
	Path       []canonicalCase `json:"path"`
	Method     []canonicalCase `json:"method"`
	Component  []canonicalCase `json:"component"`
	Identifier []canonicalCase `json:"identifier"`
}

func TestCanonicalConformance(t *testing.T) {
	fixture := readFixture[canonicalFixture](t, "canonical_conformance.json")

	if len(fixture.Path) == 0 {
		t.Fatal("the canonical fixture has no path cases; it cannot be asserting anything")
	}

	for _, group := range []struct {
		name  string
		cases []canonicalCase
		fn    func(string) string
	}{
		{"path", fixture.Path, CanonicalPath},
		{"method", fixture.Method, CanonicalMethod},
		{"component", fixture.Component, CanonicalComponent},
		{"identifier", fixture.Identifier, CanonicalIdentifier},
	} {
		for _, testCase := range group.cases {
			t.Run(group.name+"/"+testCase.Convention, func(t *testing.T) {
				got := group.fn(testCase.Source)
				if got != testCase.Canonical {
					t.Fatalf("%s(%q) = %q, fixture says %q",
						group.name, testCase.Source, got, testCase.Canonical)
				}
				// Idempotence, asserted for every case rather than a
				// chosen few: a subject gets rebuilt from a parsed one,
				// so a non-idempotent normaliser would make a
				// round-tripped subject stop matching the original.
				if again := group.fn(got); again != testCase.Canonical {
					t.Fatalf("%s is not idempotent: %q -> %q -> %q",
						group.name, testCase.Source, got, again)
				}
			})
		}
	}
}

func TestConcretePathSegmentsAreNotTreatedAsParameters(t *testing.T) {
	// Inferring that a numeric segment "is an id" is how /orders/count
	// silently becomes /orders/{} and two different routes merge.
	for _, path := range []string{"/orders/12345", "/orders/count"} {
		if got := CanonicalPath(path); got != path {
			t.Fatalf("CanonicalPath(%q) = %q, want it left alone", path, got)
		}
	}
}

// --- subject URIs ------------------------------------------------------

type subjectBuildCase struct {
	Why     string            `json:"why"`
	Kind    string            `json:"kind"`
	Parts   map[string]string `json:"parts"`
	Subject string            `json:"subject"`
}

type subjectParseErrorCase struct {
	Why     string `json:"why"`
	Subject string `json:"subject"`
}

type subjectFixture struct {
	Build       []subjectBuildCase      `json:"build"`
	BuildErrors []subjectBuildCase      `json:"build_errors"`
	ParseErrors []subjectParseErrorCase `json:"parse_errors"`
}

func caseName(why, fallback string) string {
	if why != "" {
		return why
	}
	return fallback
}

func TestSubjectBuildConformance(t *testing.T) {
	fixture := readFixture[subjectFixture](t, "subject_conformance.json")
	if len(fixture.Build) == 0 {
		t.Fatal("the subject fixture has no build cases")
	}

	for index, testCase := range fixture.Build {
		t.Run(caseName(testCase.Why, testCase.Subject), func(t *testing.T) {
			got, err := BuildSubject(SubjectKind(testCase.Kind), Parts(testCase.Parts))
			if err != nil {
				t.Fatalf("case %d: BuildSubject(%s, %v) failed: %v",
					index, testCase.Kind, testCase.Parts, err)
			}
			if got != testCase.Subject {
				t.Fatalf("BuildSubject(%s, %v) = %q, fixture says %q",
					testCase.Kind, testCase.Parts, got, testCase.Subject)
			}
		})
	}
}

func TestSubjectRoundTripsThroughParse(t *testing.T) {
	// BuildSubject(ParseSubject(s)) == s for every subject BuildSubject
	// produced. This is what keeps the two halves from drifting apart —
	// and, across languages, what makes a subject built in Go findable
	// by a comparison written in Python.
	fixture := readFixture[subjectFixture](t, "subject_conformance.json")
	for _, testCase := range fixture.Build {
		t.Run(caseName(testCase.Why, testCase.Subject), func(t *testing.T) {
			kind, parts, err := ParseSubject(testCase.Subject)
			if err != nil {
				t.Fatalf("ParseSubject(%q) failed: %v", testCase.Subject, err)
			}
			rebuilt, err := BuildSubject(kind, parts)
			if err != nil {
				t.Fatalf("rebuilding %q from %v failed: %v", testCase.Subject, parts, err)
			}
			if rebuilt != testCase.Subject {
				t.Fatalf("round trip changed %q into %q", testCase.Subject, rebuilt)
			}
		})
	}
}

func TestSubjectBuildErrorsConformance(t *testing.T) {
	fixture := readFixture[subjectFixture](t, "subject_conformance.json")
	if len(fixture.BuildErrors) == 0 {
		t.Fatal("the subject fixture has no build_errors cases")
	}
	for _, testCase := range fixture.BuildErrors {
		t.Run(caseName(testCase.Why, testCase.Kind), func(t *testing.T) {
			got, err := BuildSubject(SubjectKind(testCase.Kind), Parts(testCase.Parts))
			if err == nil {
				t.Fatalf("BuildSubject(%s, %v) should have failed (%s), returned %q",
					testCase.Kind, testCase.Parts, testCase.Why, got)
			}
		})
	}
}

func TestSubjectParseErrorsConformance(t *testing.T) {
	fixture := readFixture[subjectFixture](t, "subject_conformance.json")
	if len(fixture.ParseErrors) == 0 {
		t.Fatal("the subject fixture has no parse_errors cases")
	}
	for _, testCase := range fixture.ParseErrors {
		t.Run(caseName(testCase.Why, testCase.Subject), func(t *testing.T) {
			if _, _, err := ParseSubject(testCase.Subject); err == nil {
				t.Fatalf("ParseSubject(%q) should have failed (%s)",
					testCase.Subject, testCase.Why)
			}
		})
	}
}

// --- connection kinds --------------------------------------------------

type connectionKindFixture struct {
	Kinds   []string `json:"kinds"`
	Default string   `json:"default"`
	Refused []string `json:"refused"`
}

func TestConnectionKindsMatchTheSharedFixture(t *testing.T) {
	fixture := readFixture[connectionKindFixture](t, "connection_kind_conformance.json")
	if len(fixture.Kinds) != len(ConnectionKinds) {
		t.Fatalf("Go has %d connection kinds %v, the fixture %d %v",
			len(ConnectionKinds), ConnectionKinds, len(fixture.Kinds), fixture.Kinds)
	}
	for index, want := range fixture.Kinds {
		if string(ConnectionKinds[index]) != want {
			t.Errorf("kind %d: Go %q, fixture %q", index, ConnectionKinds[index], want)
		}
		got, err := ParseConnectionKind(want)
		if err != nil || string(got) != want {
			t.Errorf("ParseConnectionKind(%q) = %q, %v", want, got, err)
		}
	}
	if string(DefaultConnectionKind) != fixture.Default {
		t.Errorf("default kind: Go %q, fixture %q", DefaultConnectionKind, fixture.Default)
	}
	if got, err := ParseConnectionKind(""); err != nil || string(got) != fixture.Default {
		t.Errorf(`ParseConnectionKind("") = %q, %v; want the default %q`, got, err, fixture.Default)
	}
	for _, refused := range fixture.Refused {
		if got, err := ParseConnectionKind(refused); err == nil {
			t.Errorf("ParseConnectionKind(%q) accepted it as %q; the fixture refuses it", refused, got)
		}
	}
}
