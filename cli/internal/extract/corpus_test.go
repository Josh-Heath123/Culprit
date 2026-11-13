package extract

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"testing"
)

// The differential corpus (Q28): shared/tests/manifest_corpus.json records
// what the API's loader makes of every case — refused, or the hash of the
// typed document's canonical JSON — and this test holds the binary to the
// same record (api/tests/test_manifest_corpus.py holds the API). So on every
// case the two readers give equal JSON or both refuse.

type corpusSpec struct {
	Base       string            `json:"base"`
	Defaults   map[string]string `json:"defaults"`
	Forms      []string          `json:"forms"`
	Structural map[string]string `json:"structural"`
	Seeds      map[string]string `json:"seeds"`
	// Pairs are manifests in which one form fills every <<form>> at once,
	// crossed with every form; their other placeholders take their
	// defaults (Q34: a name held equal to another is still read in every
	// form).
	Pairs map[string]string `json:"pairs"`
	// ClosedSplits are the close-out phase-auditor's splits, each labelled
	// with what each reader did at d37542e (A2, 2026-11-13).
	ClosedSplits map[string]string `json:"closeout_splits"`
	Expect       map[string]string `json:"expect"`
}

func loadCorpus(t *testing.T) corpusSpec {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "shared", "tests", "manifest_corpus.json"))
	if err != nil {
		t.Fatal(err)
	}
	var spec corpusSpec
	if err := json.Unmarshal(raw, &spec); err != nil {
		t.Fatal(err)
	}
	return spec
}

// corpusCases is api/tests/test_manifest_corpus.py's corpus_cases.
func corpusCases(spec corpusSpec) map[string]string {
	cases := map[string]string{}
	for field := range spec.Defaults {
		for _, form := range spec.Forms {
			text := spec.Base
			for name, value := range spec.Defaults {
				if name == field {
					value = form
				}
				text = strings.ReplaceAll(text, "<<"+name+">>", value)
			}
			cases["field "+field+" = "+form] = text
		}
	}
	for name, text := range spec.Structural {
		cases["structural "+name] = text
	}
	for name, text := range spec.Seeds {
		cases["seed "+name] = text
	}
	for pair, template := range spec.Pairs {
		for _, form := range spec.Forms {
			text := template
			for name, value := range spec.Defaults {
				text = strings.ReplaceAll(text, "<<"+name+">>", value)
			}
			cases["pair "+pair+" = "+form] = strings.ReplaceAll(text, "<<form>>", form)
		}
	}
	return cases
}

func canonicalString(text string) string {
	var out strings.Builder
	out.WriteByte('"')
	for _, char := range text {
		switch {
		case char == '"':
			out.WriteString(`\"`)
		case char == '\\':
			out.WriteString(`\\`)
		case char < 0x20:
			fmt.Fprintf(&out, `\u%04x`, char)
		default:
			out.WriteRune(char)
		}
	}
	out.WriteByte('"')
	return out.String()
}

// pythonRepr is Python's repr of a float: the shortest digits that read
// back, positional for exponents -4 to 15, otherwise d.ddde±XX.
func pythonRepr(f float64) string {
	switch {
	case math.IsNaN(f):
		return "nan"
	case math.IsInf(f, 1):
		return "inf"
	case math.IsInf(f, -1):
		return "-inf"
	}
	sign := ""
	if math.Signbit(f) {
		sign, f = "-", -f
	}
	if f == 0 {
		return sign + "0.0"
	}
	mantissa, exponent, _ := strings.Cut(strconv.FormatFloat(f, 'e', -1, 64), "e")
	exp, _ := strconv.Atoi(exponent)
	digits := strings.Replace(mantissa, ".", "", 1)
	if exp >= -4 && exp < 16 {
		if exp < 0 {
			return sign + "0." + strings.Repeat("0", -exp-1) + digits
		}
		if len(digits) <= exp+1 {
			return sign + digits + strings.Repeat("0", exp+1-len(digits)) + ".0"
		}
		return sign + digits[:exp+1] + "." + digits[exp+1:]
	}
	expSign := "+"
	if exp < 0 {
		expSign, exp = "-", -exp
	}
	return fmt.Sprintf("%s%se%s%02d", sign, mantissa, expSign, exp)
}

func canonicalJSON(value any) string {
	switch typed := value.(type) {
	case nil:
		return "null"
	case bool:
		return strconv.FormatBool(typed)
	case int64:
		return strconv.FormatInt(typed, 10)
	case float64:
		return canonicalString("!!float " + pythonRepr(typed))
	case string:
		return canonicalString(typed)
	case []any:
		parts := make([]string, len(typed))
		for index, item := range typed {
			parts[index] = canonicalJSON(item)
		}
		return "[" + strings.Join(parts, ",") + "]"
	case map[string]any:
		keys := make([]string, 0, len(typed))
		for key := range typed {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		parts := make([]string, len(keys))
		for index, key := range keys {
			parts[index] = canonicalString(key) + ":" + canonicalJSON(typed[key])
		}
		return "{" + strings.Join(parts, ",") + "}"
	}
	panic(fmt.Sprintf("not plain data: %T", value))
}

func corpusOutcome(t *testing.T, directory, text string) string {
	path := filepath.Join(directory, "culprit.yaml")
	if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadManifest(path); err != nil {
		return "refused"
	}
	_, document, err := parseManifest([]byte(text))
	if err != nil {
		t.Fatalf("LoadManifest loaded what parseManifest refuses: %v", err)
	}
	sum := sha256.Sum256([]byte(canonicalJSON(document)))
	return hex.EncodeToString(sum[:])[:16]
}

func TestTheBinaryReadsEveryCorpusCaseAsRecorded(t *testing.T) {
	spec := loadCorpus(t)
	cases := corpusCases(spec)
	if len(cases) != len(spec.Expect) {
		t.Fatalf("the corpus generates %d cases and records %d", len(cases), len(spec.Expect))
	}
	names := make([]string, 0, len(cases))
	for name := range cases {
		names = append(names, name)
	}
	sort.Strings(names)
	directory := t.TempDir()
	var wrong []string
	for _, name := range names {
		if got := corpusOutcome(t, directory, cases[name]); got != spec.Expect[name] {
			wrong = append(wrong, fmt.Sprintf("%s: recorded %s, read %s", name, spec.Expect[name], got))
		}
	}
	if len(wrong) > 0 {
		shown := wrong
		if len(shown) > 400 {
			shown = shown[:400]
		}
		t.Fatalf("%d of %d case(s) differ from the API's reading:\n%s", len(wrong), len(cases), strings.Join(shown, "\n"))
	}
}

// TestTheGoSchemaIsTheSharedSchema: one type per field, the same as the
// API's derivation (api/tests/test_manifest_corpus.py).
func TestTheGoSchemaIsTheSharedSchema(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "shared", "tests", "manifest_schema.json"))
	if err != nil {
		t.Fatal(err)
	}
	var shared struct {
		Fields map[string]string `json:"fields"`
	}
	if err := json.Unmarshal(raw, &shared); err != nil {
		t.Fatal(err)
	}
	mine := ManifestSchema()
	for path, kind := range shared.Fields {
		if mine[path] != kind {
			t.Errorf("%s: shared %q, Go %q", path, kind, mine[path])
		}
	}
	for path, kind := range mine {
		if _, ok := shared.Fields[path]; !ok {
			t.Errorf("%s: Go %q, not in the shared schema", path, kind)
		}
	}
}

func TestEverySchemaFieldIsInTheCorpus(t *testing.T) {
	spec := loadCorpus(t)
	schema := ManifestSchema()
	if got, want := sortedKeys(spec.Defaults), sortedKeys(schema); strings.Join(got, ",") != strings.Join(want, ",") {
		t.Fatalf("corpus fields %v, schema fields %v", got, want)
	}
}

func TestPythonRepr(t *testing.T) {
	for value, want := range map[float64]string{
		1000: "1000.0", 1.5: "1.5", 0.5: "0.5", 1e16: "1e+16", 1e15: "1000000000000000.0",
		1e-5: "1e-05", 0.0001: "0.0001", 1.25e-7: "1.25e-07", 1e20: "1e+20", -2.5: "-2.5",
		123456789.125: "123456789.125",
	} {
		if got := pythonRepr(value); got != want {
			t.Errorf("pythonRepr(%v) = %s, want %s", value, got, want)
		}
	}
}

// TestTheAuditorsSplitsAreReadAsRecorded (A2, 2026-11-13): each split the
// close-out phase-auditor found is a seed, labelled with what each reader
// did at d37542e, and this reader now gives the recorded outcome for it.
// Checked by label, not by a count.
func TestTheAuditorsSplitsAreReadAsRecorded(t *testing.T) {
	spec := loadCorpus(t)
	if len(spec.ClosedSplits) == 0 {
		t.Fatal("the corpus labels no split")
	}
	directory := t.TempDir()
	for name, label := range spec.ClosedSplits {
		text, ok := spec.Seeds[name]
		expect, recorded := spec.Expect["seed "+name]
		if !ok || !recorded || !strings.HasPrefix(label, "at d37542e ") {
			t.Errorf("split %s (%q): seed %v, recorded %v", name, label, ok, recorded)
			continue
		}
		if got := corpusOutcome(t, directory, text); got != expect {
			t.Errorf("split %s (%s): recorded %s, read %s", name, label, expect, got)
		}
	}
}
