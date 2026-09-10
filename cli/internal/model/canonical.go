// Package model is the Go half of the three-plane core model
// (docs/DIAGNOSTIC_PLAN.md §2), mirroring shared/culprit_model/.
//
// It exists because §2.3 requires that two independent sources describing
// the same thing produce a byte-identical subject URI, and from Phase 28
// one of those sources is a Go binary and the other is Python. Two
// implementations are a liability unless they are held to one table, so
// both read the same fixtures out of shared/tests/ — subject_conformance.json
// and canonical_conformance.json. Change one side, change the fixture,
// and the other side's tests tell you immediately.
//
// Deterministic by construction: no network, no LLM, no clock except
// where a caller passes one in. See .claude/rules/determinism.md.
package model

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
)

// Parameter placeholders inside one path segment, in the four templating
// conventions this project actually meets. Applied *within* a segment
// rather than to whole segments, so "/files/{name}.json" and
// "/v1/item-:id" normalise correctly too.
//
// Order matters and mirrors canonical.py exactly: regex groups first,
// because "(?P<pk>[0-9]+)" must collapse before the Express ":id" rule
// gets a chance to see a colon inside it.
var paramPatterns = []*regexp.Regexp{
	// OpenAPI / FastAPI / Starlette: {id}, {id:path}, {file_path:path}
	regexp.MustCompile(`\{[^{}/]*\}`),
	// Flask / Django path(): <id>, <int:pk>, <path:subpath>
	regexp.MustCompile(`<[^<>/]*>`),
	// Django re_path named group: (?P<pk>[0-9]+); and bare regex groups.
	// Non-nested only — a nested group leaves the segment untouched,
	// which is a documented limit rather than a silently wrong answer.
	regexp.MustCompile(`\((?:\?P<[^>]*>)?[^()]*\)[*+?]?`),
	// Express / Rails / Sinatra: :id, and :id(\d+) once the group above
	// has already been collapsed.
	regexp.MustCompile(`:[A-Za-z_][A-Za-z0-9_]*`),
	// Express/Ant-style catch-alls.
	regexp.MustCompile(`\*\*?`),
}

const placeholder = "{}"

// aspectSeparator is also the `#` in a subject URI's `...#request.body`,
// which is why a path may never still contain one by the time
// BuildSubject sees it.
const aspectSeparator = "#"

// CanonicalPath normalises a route path to /literal/{}/literal form.
//
// Idempotent: CanonicalPath(CanonicalPath(p)) == CanonicalPath(p) for
// every input, which is what lets a subject URI be rebuilt from a parsed
// one without drifting.
//
// Parameter names are erased, not preserved: /orders/{id} and
// /orders/{order_id} both become /orders/{}. A Django view calling its
// capture "pk" and an OpenAPI document calling it "id" describe the same
// route, and keeping the name would mean the two never compare.
func CanonicalPath(path string) string {
	path = strings.TrimSpace(path)
	path = strings.TrimPrefix(path, "^")
	path = strings.TrimSuffix(path, "$")

	if !strings.HasPrefix(path, "/") {
		path = "/" + path
	}

	var segments []string
	for _, segment := range strings.Split(path, "/") {
		if segment == "" {
			continue
		}
		segments = append(segments, canonicalSegment(segment))
	}
	normalised := "/" + strings.Join(segments, "/")

	// Query string and fragment are cut *after* parameter normalisation,
	// not before. A Django re_path route legitimately contains a "?"
	// inside "(?P<pk>...)", and cutting first turns "^orders/(?P<pk>\d+)$"
	// into "/orders/(" — a wrong answer that still looks like a path.
	for _, cut := range []string{"?", aspectSeparator} {
		if index := strings.Index(normalised, cut); index >= 0 {
			normalised = normalised[:index]
		}
	}
	normalised = strings.TrimRight(normalised, "/")
	if normalised == "" {
		return "/"
	}
	return normalised
}

func canonicalSegment(segment string) string {
	for _, pattern := range paramPatterns {
		segment = pattern.ReplaceAllString(segment, placeholder)
	}
	// Collapse "{}{}", which only arises from an already-odd source path
	// like "<int:a><int:b>"; one parameter per position is the invariant.
	for strings.Contains(segment, placeholder+placeholder) {
		segment = strings.ReplaceAll(segment, placeholder+placeholder, placeholder)
	}
	return segment
}

// CanonicalMethod upper-cases and trims an HTTP method. Methods are
// case-insensitive in every source we read them from and upper-case in
// every one we print them to.
func CanonicalMethod(method string) string {
	return strings.ToUpper(strings.TrimSpace(method))
}

// CanonicalComponent normalises a component/service name.
//
// Lower-cased and trimmed: these are DNS-ish names that appear in a
// Docker service name, an OTel service.name attribute and a registry
// row, and those three disagree on case far more often than on identity.
// Underscores are deliberately *not* folded to hyphens — "order_service"
// and "order-service" are genuinely two different strings, and papering
// over that would hide a real naming divergence rather than surface it.
func CanonicalComponent(name string) string {
	return strings.ToLower(strings.TrimSpace(name))
}

// CanonicalIdentifier normalises a Postgres identifier. Lower-cased,
// because Postgres folds unquoted identifiers that way.
func CanonicalIdentifier(name string) string {
	return strings.ToLower(strings.TrimSpace(name))
}

// CanonicalValue recursively normalises a fact value for comparison,
// mirroring `culprit_model.canonical.canonical_value`.
//
// Mappings are key-ordered and sets become sorted lists, because neither
// has an order and any order but a deterministic one would make equal
// values compare unequal. **Lists are not sorted**: order is meaningful
// in a list of path segments or middleware, and sorting would erase a
// real divergence.
//
// JSON numbers arrive from `encoding/json` as float64 and from a Go
// literal as int, so both are folded to float64 — otherwise `200` read
// from a file and `200` written in a test would differ, which is a
// difference about the decoder rather than about the system.
func CanonicalValue(value any) any {
	switch typed := value.(type) {
	case map[string]any:
		normalised := make(map[string]any, len(typed))
		for key, inner := range typed {
			normalised[key] = CanonicalValue(inner)
		}
		return normalised
	case []any:
		normalised := make([]any, len(typed))
		for index, inner := range typed {
			normalised[index] = CanonicalValue(inner)
		}
		return normalised
	case []string:
		normalised := make([]any, len(typed))
		for index, inner := range typed {
			normalised[index] = inner
		}
		return normalised
	case int:
		return float64(typed)
	case int64:
		return float64(typed)
	case float32:
		return float64(typed)
	default:
		return value
	}
}

// CanonicalJSON is a stable string form of a value, for equality.
//
// `json.Marshal` sorts map keys, which is exactly the normalisation
// wanted; the recursion above handles the rest. A value that cannot be
// marshalled falls back to its Go representation rather than erroring —
// an unexpected type should make comparison noisy, not crash a run.
func CanonicalJSON(value any) string {
	encoded, err := json.Marshal(CanonicalValue(value))
	if err != nil {
		return fmt.Sprintf("%#v", value)
	}
	return string(encoded)
}

// ValuesEqual is the only sanctioned equality test between fact values.
func ValuesEqual(left, right any) bool {
	return CanonicalJSON(left) == CanonicalJSON(right)
}
