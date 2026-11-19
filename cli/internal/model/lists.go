// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package model

import (
	"fmt"
	"math"
	"sort"
	"strings"
)

// Lists — Phase 38 part 2 (docs/PERFORMANCE_PLAN.md, "Part 2 — lists").
//
// A list route is bounded only where a bound is declared: `maxItems` in the
// spec (the INTENT fact PredicateResponseList), or a `response_items_max`
// budget in culprit.yaml. Culprit never infers one from paging-parameter
// names. probe.http.response_items counts the items one GET answers and
// judges the count against the budget, by JudgeResponseItems — the rule
// shared/culprit_model/lists.py holds too, so a reading's verdict is a pure
// function of its own measurement and expectation.

// ListBudgetPredicates are the budgets on how many items a route answers.
// A whole number of items, on a GET route's http: subject; it may carry
// `at:`, the JSON pointer of the list in the response.
var ListBudgetPredicates = map[string]bool{"response_items_max": true}

// MaxListItems is the largest list budget, in items. Python holds the same.
const MaxListItems = 1_000_000

// MaxPointerBytes bounds a budget's `at:`.
const MaxPointerBytes = 256

// ResponseItemsProbeID is the probe that counts a list.
const ResponseItemsProbeID = "probe.http.response_items"

// PredicateResponseList is the spec's own list (INTENT, from either
// OpenAPI reader): on a route whose 2xx JSON response is an array, or an
// object with exactly one array property, the value is
// {"max_items": <whole number or null>}.
const PredicateResponseList = "response_list"

// JSONPointerProblem says why pointer is not a budget's `at:`, or "".
// It is an RFC 6901 pointer into the response, written from its first
// "/": the whole document is written by leaving `at:` out.
func JSONPointerProblem(pointer string) string {
	if !strings.HasPrefix(pointer, "/") {
		return "`at` is a JSON pointer starting with /; leave it out for a top-level list"
	}
	if len(pointer) > MaxPointerBytes {
		return fmt.Sprintf("`at` is at most %d bytes", MaxPointerBytes)
	}
	for index := 0; index < len(pointer); index++ {
		switch {
		case pointer[index] < 0x20 || pointer[index] == 0x7f:
			return "`at` holds a control character"
		case pointer[index] == '~':
			if index+1 >= len(pointer) || (pointer[index+1] != '0' && pointer[index+1] != '1') {
				return "`at` has a ~ that is not ~0 or ~1"
			}
		}
	}
	return ""
}

// PointerTokens splits a pointer JSONPointerProblem accepts into its
// unescaped reference tokens; "" is the whole document, no tokens.
func PointerTokens(pointer string) []string {
	if pointer == "" {
		return nil
	}
	tokens := strings.Split(pointer[1:], "/")
	for index, token := range tokens {
		tokens[index] = strings.ReplaceAll(strings.ReplaceAll(token, "~1", "/"), "~0", "~")
	}
	return tokens
}

// ListBudget is a response_items_max fact's value: the bound, and where
// the list is ("" for the top level).
func ListBudget(value any) (int, string, bool) {
	fields, ok := value.(map[string]any)
	if !ok || len(fields) != 2 {
		return 0, "", false
	}
	at, ok := fields["at"].(string)
	if !ok || (at != "" && JSONPointerProblem(at) != "") {
		return 0, "", false
	}
	bound, err := boundedNumber(fields["max_items"], "max_items", 1, MaxListItems)
	if err != nil {
		return 0, "", false
	}
	return bound, at, true
}

// ListBudgetValue is the fact value of a response_items_max budget.
func ListBudgetValue(bound int, at string) map[string]any {
	return map[string]any{"max_items": bound, "at": at}
}

// Why a list was not counted, as a reading's measured["not_counted"].
const (
	NotCountedStatus   = "status"    // the answer was not 2xx
	NotCountedNotJSON  = "not_json"  // the body is not JSON
	NotCountedNoArray  = "no_array"  // nothing at `at`, or not an array
	NotCountedTooLarge = "too_large" // the body is over the read cap
)

var notCountedReasons = map[string]string{
	NotCountedStatus:   "the route answered %s, not 2xx, so no list was counted",
	NotCountedNotJSON:  "the response is not JSON, so no list was counted",
	NotCountedNoArray:  "the response holds no array at %s, so no list was counted",
	NotCountedTooLarge: "the response is larger than the %s this probe reads, so no list was counted",
}

// JudgeResponseItems is the rule: the verdict and reason of a
// probe.http.response_items reading, from its measured and expected alone.
//
//   - measured: {"url", "method", "at", "status", "items"} when counted, or
//     {"url", "method", "at", "status", "not_counted"} when not;
//   - expected: {"response_items_max": <bound>, "at": <pointer>}.
//
// Within the bound (at it, too) passes; over it fails; not counted is
// inconclusive, saying why.
func JudgeResponseItems(measured, expected map[string]any) (Verdict, string, error) {
	bound, err := boundedNumber(expected["response_items_max"], "the bound", 1, MaxListItems)
	if err != nil {
		return "", "", err
	}
	at, _ := measured["at"].(string)
	if expectedAt, ok := expected["at"].(string); !ok || expectedAt != at {
		return "", "", shapeError("the reading's at is not the budget's")
	}
	where := at
	if where == "" {
		where = "the top level"
	}
	if reason, ok := measured["not_counted"].(string); ok {
		if _, counted := measured["items"]; counted {
			return "", "", shapeError("a reading both counted and not")
		}
		format, known := notCountedReasons[reason]
		if !known {
			return "", "", shapeError("not_counted %q is not a known reason", reason)
		}
		switch reason {
		case NotCountedStatus:
			status, err := boundedNumber(measured["status"], "status", 100, 599)
			if err != nil {
				return "", "", err
			}
			return VerdictInconclusive, fmt.Sprintf(format, fmt.Sprint(status)), nil
		case NotCountedNoArray:
			return VerdictInconclusive, fmt.Sprintf(format, where), nil
		case NotCountedTooLarge:
			return VerdictInconclusive, fmt.Sprintf(format, "1 MiB"), nil
		}
		return VerdictInconclusive, format, nil
	}
	items, err := boundedNumber(measured["items"], "items", 0, math.MaxInt32)
	if err != nil {
		return "", "", err
	}
	if items > bound {
		return VerdictFail, fmt.Sprintf(
			"the list at %s holds %d items, over its bound of %d", where, items, bound), nil
	}
	return VerdictPass, "", nil
}

// --- the spec's lists ---------------------------------------------------
//
// ResponseList is the rule both OpenAPI readers apply to one operation
// (Phase 38 part 2, decision 2), held to shared/tests/list_conformance.json
// with shared/culprit_model/lists.py's response_list:
//
//   - the response is the operation's first 2xx in sorted order ("200",
//     "201", ..., "2XX"); a `$ref` to it is resolved;
//   - its schema is, in OpenAPI 3, that of its first JSON media type in
//     sorted order (application/json, or a type ending +json, parameters
//     ignored), and in Swagger 2 its own `schema`;
//   - `$ref`s are resolved within the document only ("#/..."), at most
//     maxRefHops deep; any other `$ref` is not followed, and nothing is
//     emitted;
//   - a schema of `type: array` is the list; an object (`type: object`, or
//     no type, with `properties`) with exactly one property of `type:
//     array` is an envelope, and that property is the list;
//   - the list's maxItems, when it is a whole number from 0 to 2^31-1, is
//     its bound; otherwise the bound is null (unbounded).
//
// Anything else — two array properties, no 2xx, no JSON, a type list, an
// allOf — emits nothing: such a route is not listed (docs/LIMITS.md).
// The bool is whether a list was found; the *int is its bound or nil.

const maxRefHops = 16

// ResponseList finds an operation's list, per the rule above.
func ResponseList(document, operation map[string]any) (*int, bool) {
	responses, _ := operation["responses"].(map[string]any)
	codes := make([]string, 0, len(responses))
	for code := range responses {
		if is2xx(code) {
			codes = append(codes, code)
		}
	}
	if len(codes) == 0 {
		return nil, false
	}
	sort.Strings(codes)
	response, ok := resolveRef(document, responses[codes[0]])
	if !ok {
		return nil, false
	}
	var schema any
	if content, isOpenAPI3 := response["content"].(map[string]any); isOpenAPI3 {
		types := make([]string, 0, len(content))
		for mediaType := range content {
			if isJSONMediaType(mediaType) {
				types = append(types, mediaType)
			}
		}
		if len(types) == 0 {
			return nil, false
		}
		sort.Strings(types)
		media, _ := content[types[0]].(map[string]any)
		schema = media["schema"]
	} else {
		schema = response["schema"]
	}
	resolved, ok := resolveRef(document, schema)
	if !ok {
		return nil, false
	}
	if resolved["type"] == "array" {
		return maxItemsOf(resolved), true
	}
	properties, hasProperties := resolved["properties"].(map[string]any)
	if kind, typed := resolved["type"]; !hasProperties || (typed && kind != "object") {
		return nil, false
	}
	var list map[string]any
	for _, property := range properties {
		candidate, ok := resolveRef(document, property)
		if !ok || candidate["type"] != "array" {
			continue
		}
		if list != nil {
			return nil, false
		}
		list = candidate
	}
	if list == nil {
		return nil, false
	}
	return maxItemsOf(list), true
}

func is2xx(code string) bool {
	if code == "2XX" || code == "2xx" {
		return true
	}
	return len(code) == 3 && code[0] == '2' && code[1] >= '0' && code[1] <= '9' &&
		code[2] >= '0' && code[2] <= '9'
}

func isJSONMediaType(mediaType string) bool {
	base, _, _ := strings.Cut(strings.ToLower(mediaType), ";")
	base = strings.TrimSpace(base)
	return base == "application/json" || strings.HasSuffix(base, "+json")
}

// resolveRef follows local `$ref`s to a mapping, at most maxRefHops.
func resolveRef(document map[string]any, node any) (map[string]any, bool) {
	for hop := 0; hop <= maxRefHops; hop++ {
		mapping, ok := node.(map[string]any)
		if !ok {
			return nil, false
		}
		ref, isRef := mapping["$ref"]
		if !isRef {
			return mapping, true
		}
		pointer, ok := ref.(string)
		if !ok || !strings.HasPrefix(pointer, "#/") {
			return nil, false
		}
		node = any(document)
		for _, token := range PointerTokens(pointer[1:]) {
			container, ok := node.(map[string]any)
			if !ok {
				return nil, false
			}
			if node, ok = container[token]; !ok {
				return nil, false
			}
		}
	}
	return nil, false
}

// maxItemsOf is a list schema's bound: maxItems when it is a whole number
// from 0 to 2^31-1, else nil.
func maxItemsOf(schema map[string]any) *int {
	var bound int
	switch value := schema["maxItems"].(type) {
	case int:
		bound = value
	case int64:
		if value > math.MaxInt32 {
			return nil
		}
		bound = int(value)
	case uint64:
		if value > math.MaxInt32 {
			return nil
		}
		bound = int(value)
	case float64:
		if value != math.Trunc(value) || value > math.MaxInt32 || value < 0 {
			return nil
		}
		bound = int(value)
	default:
		return nil
	}
	if bound < 0 || bound > math.MaxInt32 {
		return nil
	}
	return &bound
}

// ResponseListValue is a response_list fact's value.
func ResponseListValue(bound *int) map[string]any {
	if bound == nil {
		return map[string]any{"max_items": nil}
	}
	return map[string]any{"max_items": *bound}
}

// validateList holds a probe.http.response_items reading to its own count
// and bound (Phase 38 part 2), as shared/culprit_model/readings.py does.
func (r Reading) validateList() error {
	if r.ProbeID != ResponseItemsProbeID || r.Verdict == VerdictRefused {
		return nil
	}
	_, counted := r.Measured["items"]
	_, notCounted := r.Measured["not_counted"]
	if !counted && !notCounted {
		if r.Verdict != VerdictInconclusive {
			return fmt.Errorf("a %s list reading must carry the count it was judged on", r.Verdict)
		}
		return nil
	}
	verdict, _, err := JudgeResponseItems(r.Measured, r.Expected)
	if err != nil {
		return fmt.Errorf("a list reading's measurement is not the rule's input: %w", err)
	}
	if verdict != r.Verdict {
		return fmt.Errorf("a list reading says %s, but its own count and bound give %s", r.Verdict, verdict)
	}
	return nil
}
