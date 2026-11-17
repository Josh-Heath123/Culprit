package model

import (
	"testing"
)

// Phase 38 part 2: the spec's lists and the probe's judgement, held to
// shared/tests/list_conformance.json, which culprit_model.lists records
// (shared/tests/test_lists.py). The two OpenAPI readers apply one rule.

type listFixture struct {
	ResponseList []struct {
		Name     string         `json:"name"`
		Document map[string]any `json:"document"`
		Path     string         `json:"path"`
		Method   string         `json:"method"`
		Expect   struct {
			List     bool `json:"list"`
			MaxItems *int `json:"max_items"`
		} `json:"expect"`
	} `json:"response_list"`
	Judge []struct {
		Name     string         `json:"name"`
		Measured map[string]any `json:"measured"`
		Expected map[string]any `json:"expected"`
		Expect   struct {
			Verdict string `json:"verdict"`
			Reason  string `json:"reason"`
			Error   bool   `json:"error"`
		} `json:"expect"`
	} `json:"judge"`
}

func TestResponseListMatchesTheConformanceFixture(t *testing.T) {
	fixture := readFixture[listFixture](t, "list_conformance.json")
	if len(fixture.ResponseList) < 900 {
		t.Fatalf("only %d response_list cases", len(fixture.ResponseList))
	}
	lists := 0
	for _, c := range fixture.ResponseList {
		paths, _ := c.Document["paths"].(map[string]any)
		item, _ := paths[c.Path].(map[string]any)
		operation, _ := item[c.Method].(map[string]any)
		bound, found := ResponseList(c.Document, operation)
		if found {
			lists++
		}
		same := found == c.Expect.List &&
			((bound == nil && c.Expect.MaxItems == nil) ||
				(bound != nil && c.Expect.MaxItems != nil && *bound == *c.Expect.MaxItems))
		if !same {
			got := "null"
			if bound != nil {
				got = itoa(*bound)
			}
			t.Errorf("%s: Go says list=%v max_items=%s, Python recorded %+v", c.Name, found, got, c.Expect)
		}
	}
	if lists == 0 {
		t.Error("no case is a list")
	}
}

func TestJudgeResponseItemsMatchesTheConformanceFixture(t *testing.T) {
	fixture := readFixture[listFixture](t, "list_conformance.json")
	if len(fixture.Judge) == 0 {
		t.Fatal("no judge cases")
	}
	for _, c := range fixture.Judge {
		verdict, reason, err := JudgeResponseItems(c.Measured, c.Expected)
		switch {
		case c.Expect.Error:
			if err == nil {
				t.Errorf("%s: Go judged %s (%s), Python refused the reading", c.Name, verdict, reason)
			}
		case err != nil:
			t.Errorf("%s: Go refused the reading (%v), Python judged %s", c.Name, err, c.Expect.Verdict)
		case string(verdict) != c.Expect.Verdict || reason != c.Expect.Reason:
			t.Errorf("%s: Go %s %q, Python %s %q", c.Name, verdict, reason, c.Expect.Verdict, c.Expect.Reason)
		}
	}
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	negative := n < 0
	if negative {
		n = -n
	}
	var digits []byte
	for n > 0 {
		digits = append([]byte{byte('0' + n%10)}, digits...)
		n /= 10
	}
	if negative {
		return "-" + string(digits)
	}
	return string(digits)
}
