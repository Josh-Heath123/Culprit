package extract

import (
	"fmt"
	"reflect"
	"regexp"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// budgetValuePath and budgetEntryPath are where a budget's written form is
// checked, before its type: a value not written as plain decimal digits is
// refused for its form (model.BudgetLiteralProblem), and a merge inside an
// entry is refused outright, as the API refuses both.
var (
	budgetValuePath = regexp.MustCompile(`^budgets\[\d+\]\.value$`)
	budgetEntryPath = regexp.MustCompile(`^budgets\[\d+\]$`)
)

// One schema, typed (Q28, ruled 2026-11-12, docs/PERFORMANCE_PLAN.md end
// of Phase 37). The binary and the API read culprit.yaml with two YAML
// libraries and two models. yaml.v3 decodes a scalar into whatever Go type
// the field has — `why: 300` becomes the text "300", `max_probes: 1.5`
// becomes 1 — while the API's models refuse some kinds and coerce others,
// so the two readers split one file 23 ways in 85 at the close-out's audit.
//
// So every manifest field has one type, and a scalar is accepted only when
// its resolved YAML 1.2 tag is that type, before anything is decoded:
//
//   - text takes !!str (a date is text, as written); an integer takes !!int
//     within int64; true/false take !!bool;
//   - null and empty are refused everywhere, naming the field: leaving the
//     key out is how "not set" is written;
//   - a field with no fixed type (an invariant's value, a label) takes any
//     core scalar, and a date stays its text;
//   - any tag but the core ones — !!binary, !!timestamp, !!python/... — is
//     not plain data;
//   - an unknown key is refused at every level, naming it.
//
// The API's loader does the same over the same schema
// (api/app/model/manifest.py, _typed): shared/tests/manifest_schema.json
// holds the two derivations equal, and shared/tests/manifest_corpus.json —
// every field crossed with every scalar form, plus merges, anchors and
// documents — holds what the two readers make of each file equal.

// manifestType is what one field holds.
type manifestType struct {
	kind   string // str, int, bool, any, grant, list, map, struct
	elem   *manifestType
	fields map[string]*manifestType
}

// typeOverrides are the fields whose Go type says less than the field
// holds: a budget's value is read as `any` so its written form can be
// checked (budgets.go), and a grant is true, false or a list of names.
var typeOverrides = map[string]string{
	"budgets[].value":         "int",
	"environments{}.grants{}": "grant",
}

var anyType = &manifestType{kind: "any"}

func schemaOf(t reflect.Type, path string) *manifestType {
	if kind, ok := typeOverrides[path]; ok {
		return &manifestType{kind: kind}
	}
	switch t.Kind() {
	case reflect.Pointer:
		return schemaOf(t.Elem(), path)
	case reflect.String:
		return &manifestType{kind: "str"}
	case reflect.Int, reflect.Int64:
		return &manifestType{kind: "int"}
	case reflect.Bool:
		return &manifestType{kind: "bool"}
	case reflect.Interface:
		return anyType
	case reflect.Slice:
		return &manifestType{kind: "list", elem: schemaOf(t.Elem(), path+"[]")}
	case reflect.Map:
		return &manifestType{kind: "map", elem: schemaOf(t.Elem(), path+"{}")}
	case reflect.Struct:
		fields := map[string]*manifestType{}
		for index := 0; index < t.NumField(); index++ {
			field := t.Field(index)
			name, _, _ := strings.Cut(field.Tag.Get("yaml"), ",")
			if name == "" || name == "-" {
				continue
			}
			child := name
			if path != "" {
				child = path + "." + name
			}
			fields[name] = schemaOf(field.Type, child)
		}
		return &manifestType{kind: "struct", fields: fields}
	}
	panic(fmt.Sprintf("culprit.yaml field %s: no manifest type for %s", path, t))
}

var manifestSchema = schemaOf(reflect.TypeOf(Manifest{}), "")

// ManifestSchema is every field's path and type, flat: what
// shared/tests/manifest_schema.json holds, and the API's derivation too.
func ManifestSchema() map[string]string {
	flat := map[string]string{}
	var walk func(t *manifestType, path string)
	walk = func(t *manifestType, path string) {
		switch t.kind {
		case "struct":
			for name, field := range t.fields {
				child := name
				if path != "" {
					child = path + "." + name
				}
				walk(field, child)
			}
		case "list":
			walk(t.elem, path+"[]")
		case "map":
			walk(t.elem, path+"{}")
		default:
			flat[path] = t.kind
		}
	}
	walk(manifestSchema, "")
	return flat
}

// refusal names the field and the line, never the value (invariant 7).
func refusal(n *yaml.Node, format string, args ...any) error {
	return fmt.Errorf("%s (line %d)", fmt.Sprintf(format, args...), n.Line)
}

func where(path string) string {
	if path == "" {
		return "<root>"
	}
	return path
}

// scalarOf is a scalar's kind (str, int, float, bool, null) and value, as
// yaml.v3 decodes it. An explicit tag must agree with the text, which
// yaml.v3's own decode holds; !!str takes any text; a date is text.
func scalarOf(n *yaml.Node, path string) (string, any, error) {
	switch tag := n.ShortTag(); tag {
	case "!!str":
		return "str", n.Value, nil
	case "!!timestamp":
		if n.Style&yaml.TaggedStyle != 0 {
			return "", nil, refusal(n, "%s: a value tagged %s is not plain data", path, tag)
		}
		// A date is its text (Q28): decoded as text from here on.
		n.Tag = "!!str"
		return "str", n.Value, nil
	case "!!int", "!!float", "!!bool", "!!null":
	default:
		return "", nil, refusal(n, "%s: a value tagged %s is not plain data", path, tag)
	}
	var value any
	if err := n.Decode(&value); err != nil {
		return "", nil, refusal(n, "%s: the text cannot be read as %s", path, n.ShortTag())
	}
	switch typed := value.(type) {
	case nil:
		return "null", nil, nil
	case bool:
		return "bool", typed, nil
	case int:
		return "int", int64(typed), nil
	case int64:
		return "int", typed, nil
	case uint64:
		return "", nil, refusal(n, "%s: an integer out of range", path)
	case float64:
		return "float", typed, nil
	}
	return "", nil, refusal(n, "%s: not plain data", path)
}

type pair struct {
	name       string
	key, value *yaml.Node
}

func unalias(n *yaml.Node) *yaml.Node {
	for n != nil && n.Kind == yaml.AliasNode {
		n = n.Alias
	}
	return n
}

// pairsOf is a mapping's pairs in yaml.v3's order — its own keys, then what
// each merge brings in, a merged mapping's own keys before its merges —
// where the first to set a key wins. Every key is text, none written twice.
func pairsOf(n *yaml.Node, path string) ([]pair, error) {
	var own []pair
	var merges []*yaml.Node
	for index := 0; index+1 < len(n.Content); index += 2 {
		key, value := unalias(n.Content[index]), n.Content[index+1]
		for earlier := 0; earlier < index; earlier += 2 {
			other := unalias(n.Content[earlier])
			if other.Kind == key.Kind && other.Value == key.Value {
				return nil, refusal(key, "%s: a key is written twice in one mapping", where(path))
			}
		}
		if key.Kind == yaml.ScalarNode && key.ShortTag() == "!!merge" {
			merges = append(merges, unalias(value))
			continue
		}
		if key.Kind != yaml.ScalarNode {
			return nil, refusal(key, "%s: every key is text", where(path))
		}
		if kind, _, err := scalarOf(key, where(path)); err != nil || kind != "str" {
			return nil, refusal(key, "%s: every key is text", where(path))
		}
		own = append(own, pair{key.Value, key, value})
	}
	for _, merged := range merges {
		items := []*yaml.Node{merged}
		if merged.Kind == yaml.SequenceNode {
			items = merged.Content
		}
		for _, item := range items {
			item = unalias(item)
			if item.Kind != yaml.MappingNode {
				return nil, refusal(item, "%s: a merge (<<) of something not a mapping", where(path))
			}
			more, err := pairsOf(item, path)
			if err != nil {
				return nil, err
			}
			own = append(own, more...)
		}
	}
	seen := map[string]bool{}
	var first []pair
	for _, p := range own {
		if !seen[p.name] {
			seen[p.name] = true
			first = append(first, p)
		}
	}
	return first, nil
}

var kindNames = map[string]string{"str": "text", "int": "an integer", "bool": "true or false"}

// typed is the node as plain data of the type the field holds, or refused,
// naming the field.
func typed(n *yaml.Node, t *manifestType, path string) (any, error) {
	if budgetValuePath.MatchString(path) {
		plain := n.Kind == yaml.ScalarNode && n.Style == 0 && n.Anchor == ""
		if problem := model.BudgetLiteralProblem(n.Value, plain); problem != "" {
			return nil, refusal(n, "%s: %s", path, problem)
		}
	}
	n = unalias(n)
	at := where(path)
	if n.Kind == yaml.MappingNode && budgetEntryPath.MatchString(path) {
		for index := 0; index+1 < len(n.Content); index += 2 {
			if key := n.Content[index]; key.ShortTag() == "!!merge" || key.Value == "<<" {
				return nil, refusal(key, "%s: %s", path, model.BudgetMergeProblem)
			}
		}
	}
	switch n.Kind {
	case yaml.ScalarNode:
		found, value, err := scalarOf(n, at)
		if err != nil {
			return nil, err
		}
		if found == "null" {
			return nil, refusal(n, "%s: null or empty; leave the key out to leave it unset", at)
		}
		kind := t.kind
		if kind == "grant" {
			kind = "bool"
		}
		if kind == "any" {
			return value, nil
		}
		if name, ok := kindNames[kind]; ok {
			if found != kind {
				return nil, refusal(n, "%s: expected %s, written as %s", at, name, found)
			}
			return value, nil
		}
		if kind == "struct" || kind == "map" {
			return nil, refusal(n, "%s: expected a mapping", at)
		}
		return nil, refusal(n, "%s: expected a list", at)
	case yaml.SequenceNode:
		if n.ShortTag() != "!!seq" {
			return nil, refusal(n, "%s: a value tagged %s is not plain data", at, n.ShortTag())
		}
		element := t.elem
		switch t.kind {
		case "grant":
			element = &manifestType{kind: "str"}
		case "any":
			element = anyType
		case "list":
		default:
			return nil, refusal(n, "%s: a list where the field is not one", at)
		}
		items := []any{}
		for index, item := range n.Content {
			value, err := typed(item, element, fmt.Sprintf("%s[%d]", path, index))
			if err != nil {
				return nil, err
			}
			items = append(items, value)
		}
		return items, nil
	case yaml.MappingNode:
		if n.ShortTag() != "!!map" {
			return nil, refusal(n, "%s: a value tagged %s is not plain data", at, n.ShortTag())
		}
		if t.kind != "struct" && t.kind != "map" && t.kind != "any" {
			return nil, refusal(n, "%s: a mapping where the field is not one", at)
		}
		pairs, err := pairsOf(n, path)
		if err != nil {
			return nil, err
		}
		out := map[string]any{}
		for _, p := range pairs {
			child := p.name
			if path != "" {
				child = path + "." + p.name
			}
			field := anyType
			switch t.kind {
			case "struct":
				known, ok := t.fields[p.name]
				if !ok {
					return nil, refusal(p.key, "%s: unknown key %q", at, p.name)
				}
				field = known
			case "map":
				field = t.elem
			}
			value, err := typed(p.value, field, child)
			if err != nil {
				return nil, err
			}
			out[p.name] = value
		}
		return out, nil
	}
	return nil, refusal(n, "%s: not plain data", at)
}

// typedDocument is the manifest as typed plain data, before the model's own
// checks: what the differential corpus compares with the API's.
func typedDocument(root *yaml.Node) (map[string]any, error) {
	if root.Kind == yaml.DocumentNode {
		if len(root.Content) == 0 {
			return nil, fmt.Errorf("empty")
		}
		root = root.Content[0]
	}
	document, err := typed(root, manifestSchema, "")
	if err != nil {
		return nil, err
	}
	mapping, _ := document.(map[string]any)
	return mapping, nil
}

// sortedKeys is a test and message helper.
func sortedKeys(m map[string]string) []string {
	keys := make([]string, 0, len(m))
	for key := range m {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}
