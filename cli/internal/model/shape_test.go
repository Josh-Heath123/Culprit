package model

import (
	"encoding/json"
	"strings"
	"testing"
)

// The Go half of shared/tests/shape_conformance.json. The Python half is
// shared/tests/test_shape.py; both read the same file, so the CLI's diff
// and the API's diff of the same two captures cannot disagree about what
// "the same kind of value" means without a test going red.

type shapeFixture struct {
	Schemes []struct {
		Input  string      `json:"input"`
		Scheme ValueScheme `json:"scheme"`
	} `json:"schemes"`
	Equivalence []struct {
		Why        string     `json:"why"`
		Left       ValueShape `json:"left"`
		Right      ValueShape `json:"right"`
		Equivalent bool       `json:"equivalent"`
	} `json:"equivalence"`
}

func TestSchemesMatchTheSharedFixture(t *testing.T) {
	fixture := readFixture[shapeFixture](t, "shape_conformance.json")
	if len(fixture.Schemes) == 0 {
		t.Fatal("no scheme cases, so this test proves nothing")
	}
	for _, testCase := range fixture.Schemes {
		if got := ClassifyScheme(testCase.Input); got != testCase.Scheme {
			t.Errorf("ClassifyScheme(%q) = %q, fixture says %q", testCase.Input, got, testCase.Scheme)
		}
	}
}

func TestEquivalenceMatchesTheSharedFixture(t *testing.T) {
	fixture := readFixture[shapeFixture](t, "shape_conformance.json")
	if len(fixture.Equivalence) == 0 {
		t.Fatal("no equivalence cases, so this test proves nothing")
	}
	for _, testCase := range fixture.Equivalence {
		t.Run(testCase.Why, func(t *testing.T) {
			if got := testCase.Left.Equivalent(testCase.Right); got != testCase.Equivalent {
				t.Errorf("Equivalent = %t, fixture says %t", got, testCase.Equivalent)
			}
			// Symmetric, or a diff of (a, b) and (b, a) would disagree.
			if got := testCase.Right.Equivalent(testCase.Left); got != testCase.Equivalent {
				t.Errorf("Equivalent is not symmetric for this case")
			}
		})
	}
}

// TestSchemeNeverCarriesTheValue is the Q7 guarantee stated as a test:
// whatever the input, the output is a member of the closed set.
func TestSchemeNeverCarriesTheValue(t *testing.T) {
	secret := "hunter2-this-is-the-password"
	for _, input := range []string{
		secret + "://host/db",
		"postgresql://user:" + secret + "@host/db",
		"x" + secret + "+driver://host",
	} {
		scheme := ClassifyScheme(input)
		if strings.Contains(string(scheme), "hunter2") || !knownSchemeValues[scheme] {
			t.Errorf("ClassifyScheme returned %q for an input carrying a secret", scheme)
		}
	}
}

// TestEveryFieldIsCheckedAgainstItsClosedSet pins down the defect found
// while adding `scheme`: a named string type is still a string, and
// before Phase 30 every one of these decoded without complaint and was
// then printed straight into a SARIF report.
func TestEveryFieldIsCheckedAgainstItsClosedSet(t *testing.T) {
	smuggled := "postgresql://u:hunter2@db/orders"
	base := map[string]any{
		"type": "string", "length_class": "medium", "format": "dsn", "present": true,
	}
	for _, field := range []string{"type", "length_class", "format", "scheme"} {
		t.Run(field, func(t *testing.T) {
			wire := map[string]any{}
			for key, value := range base {
				wire[key] = value
			}
			wire[field] = smuggled
			data, _ := json.Marshal(wire)
			var shape ValueShape
			err := json.Unmarshal(data, &shape)
			if err == nil {
				t.Fatalf("a DSN in value_shape.%s decoded without complaint", field)
			}
			if strings.Contains(err.Error(), "hunter2") {
				t.Errorf("the refusal quoted the value it refused: %v", err)
			}
		})
	}
}

func TestAStructLiteralOutsideTheSetFailsValidation(t *testing.T) {
	shape := ShapeOfString("x")
	shape.Format = ValueFormat("postgresql://u:hunter2@db/orders")
	fact := Fact{
		Plane:      PlaneIntent,
		Subject:    MustBuildSubject(KindConfig, Parts{"component": "orders", "key": "DATABASE_URL"}),
		Predicate:  PredicateExampleShape,
		ValueShape: &shape,
	}
	err := fact.Validate()
	if err == nil {
		t.Fatal("a fact whose shape carries a DSN in `format` validated")
	}
	if strings.Contains(err.Error(), "hunter2") {
		t.Errorf("the refusal quoted the value: %v", err)
	}
}

func TestShapeOfStringClassifiesTheScheme(t *testing.T) {
	shape := ShapeOfString("postgresql+asyncpg://u:pw@db/orders")
	if shape.Scheme != SchemePostgreSQL || shape.Format != FormatDSN {
		t.Errorf("got %+v", shape)
	}
	if plain := ShapeOfString("8000"); plain.Scheme != SchemeNotApplicable {
		t.Errorf("a port was given scheme %q", plain.Scheme)
	}
}
