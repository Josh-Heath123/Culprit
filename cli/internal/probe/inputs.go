package probe

import "encoding/json"

// Reading a probe's inputs.
//
// Inputs arrive as map[string]any, because they come from YAML or JSON
// and a probe's input schema is data. These helpers exist so that a
// missing or wrong-typed input becomes `inconclusive` with a reason
// rather than a panic or, worse, a zero value silently treated as an
// answer — a port that defaulted to 0 would produce a confident `fail`
// about a connection nobody asked about.

func stringInput(inputs map[string]any, key string) (string, bool) {
	raw, ok := inputs[key]
	if !ok {
		return "", false
	}
	value, ok := raw.(string)
	if !ok || value == "" {
		return "", false
	}
	return value, true
}

// intInput accepts the several shapes a number takes on the way through
// YAML and JSON: an int from Go, a float64 from encoding/json, and a
// json.Number when the decoder was asked to preserve precision.
func intInput(inputs map[string]any, key string) (int, bool) {
	raw, ok := inputs[key]
	if !ok {
		return 0, false
	}
	switch value := raw.(type) {
	case int:
		return value, true
	case int64:
		return int(value), true
	case float64:
		if value != float64(int(value)) {
			return 0, false
		}
		return int(value), true
	case json.Number:
		parsed, err := value.Int64()
		if err != nil {
			return 0, false
		}
		return int(parsed), true
	default:
		return 0, false
	}
}

func stringsInput(inputs map[string]any, key string) ([]string, bool) {
	raw, ok := inputs[key]
	if !ok {
		return nil, false
	}
	switch value := raw.(type) {
	case []string:
		return value, true
	case []any:
		result := make([]string, 0, len(value))
		for _, item := range value {
			text, ok := item.(string)
			if !ok {
				return nil, false
			}
			result = append(result, text)
		}
		return result, true
	default:
		return nil, false
	}
}
