package probe

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/capability"
	"github.com/josh-heath123/culprit/cli/internal/capture"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// probe.db.statements_per_request (Phase 39 part 1), against recorded
// statistics: the bracket is a fake with a fixed answer, the GET goes to a
// fake counter or, where what is kept matters, through the real guarded
// client to a local server whose items hold secret-looking strings.

const perItemTarget = "http:shop/GET /products"

// countingCounter counts the GETs that reach it.
type countingCounter struct {
	fakeHTTP
	count ItemCount
	err   error
	gets  atomic.Int64
}

func (c *countingCounter) CountItems(context.Context, string, []string) (ItemCount, error) {
	c.gets.Add(1)
	return c.count, c.err
}

func sentBracket(statements ...capture.StatementStats) capture.StatementBracket {
	return capture.StatementBracket{Sent: true, ServerVersion: 160004, Statements: statements}
}

func stat(queryID int64, calls int64, text string) capture.StatementStats {
	return capture.StatementStats{QueryID: queryID, Calls: calls, TotalMicros: calls * 100,
		Text: text, TextKept: text != ""}
}

// runPerItem runs the probe through a runner that holds every grant, with
// isolated the environment the runner is told culprit.yaml declares
// isolated.
func runPerItem(t *testing.T, isolated string, request Request, http HTTPClient, statements fakeStatements) model.Reading {
	t.Helper()
	if request.ProbeID == "" {
		request.ProbeID = model.StatementsPerRequestProbeID
	}
	if request.Target == "" {
		request.Target = perItemTarget
	}
	if request.Environment == "" {
		request.Environment = "lab"
	}
	if request.Inputs == nil {
		request.Inputs = map[string]any{"base_url": "http://shop.internal", "at": "/products"}
	}
	readings := NewRunner(Options{
		Ledger: grantEverything(t), IsolatedEnvironment: isolated,
		Deps: Deps{HTTP: http, Statements: statements, Now: fixedClock()},
	}).Run(context.Background(), []Request{request})
	if len(readings) != 1 {
		t.Fatalf("%d readings", len(readings))
	}
	if err := readings[0].Validate(); err != nil {
		t.Errorf("the reading does not validate: %v", err)
	}
	return readings[0]
}

func TestNotDeclaredIsolatedSendsNothing(t *testing.T) {
	counter := &countingCounter{count: ItemCount{Status: 200, Items: 5, Counted: true}}
	calls := 0
	reading := runPerItem(t, "", Request{}, counter,
		fakeStatements{bracket: sentBracket(stat(202, 5, "")), calls: &calls})
	if reading.Verdict != model.VerdictInconclusive || !strings.Contains(reading.Reason, "not declared isolated") {
		t.Errorf("%s: %s", reading.Verdict, reading.Reason)
	}
	if counter.gets.Load() != 0 || calls != 0 {
		t.Errorf("%d GET(s) and %d database call(s) were made", counter.gets.Load(), calls)
	}
}

// TestAnInputCannotSetIsolation: neither an input, nor a caller's own
// Request.Isolated, nor a runner told of another environment, sends anything.
func TestAnInputCannotSetIsolation(t *testing.T) {
	for name, c := range map[string]struct {
		isolated string
		request  Request
	}{
		"an isolated input": {"", Request{Inputs: map[string]any{
			"base_url": "http://shop.internal", "isolated": true}}},
		"the caller's own field": {"", Request{Isolated: true}},
		"both":                   {"", Request{Isolated: true, Inputs: map[string]any{"base_url": "http://shop.internal", "isolated": "true"}}},
		"another environment":    {"lab", Request{Environment: "production", Isolated: true}},
	} {
		counter := &countingCounter{count: ItemCount{Status: 200, Items: 5, Counted: true}}
		calls := 0
		reading := runPerItem(t, c.isolated, c.request, counter,
			fakeStatements{bracket: sentBracket(stat(202, 5, "")), calls: &calls})
		if reading.Verdict != model.VerdictInconclusive || !strings.Contains(reading.Reason, "not declared isolated") {
			t.Errorf("%s: %s: %s", name, reading.Verdict, reading.Reason)
		}
		if counter.gets.Load() != 0 || calls != 0 {
			t.Errorf("%s: %d GET(s) and %d database call(s)", name, counter.gets.Load(), calls)
		}
	}
}

func TestAgainstRecordedStatistics(t *testing.T) {
	five := ItemCount{Status: 200, Items: 5, Counted: true}
	for name, c := range map[string]struct {
		count     ItemCount
		bracket   capture.StatementBracket
		verdict   model.Verdict
		perItem   []string
		reason    string
		sent      bool
		measuring bool
	}{
		"one statement per item is named": {five, sentBracket(
			stat(101, 1, "SELECT id FROM products LIMIT $1"),
			stat(202, 5, "SELECT name FROM tags WHERE product_id = $1")),
			model.VerdictPass, []string{"202"}, "1 statement(s) ran at least once per item of 5: 202 (5 calls)", true, true},
		"loaded together, none is named": {five, sentBracket(
			stat(101, 1, "SELECT p.id, t.name FROM products p JOIN tags t ON t.product_id = p.id")),
			model.VerdictPass, []string{}, "no statement ran once per item", true, true},
		"fewer than two items": {ItemCount{Status: 200, Items: 1, Counted: true}, sentBracket(stat(202, 1, "")),
			model.VerdictInconclusive, []string{}, "fewer than 2", true, true},
		"a reset in the bracket": {five, capture.StatementBracket{Sent: true, Reset: true},
			model.VerdictInconclusive, nil, "reset", true, false},
		"calls in the quiet window": {five, capture.StatementBracket{QuietCalls: 7},
			model.VerdictInconclusive, nil, "7 call(s) by another client in the 2 s quiet window", false, false},
		"no list at the pointer": {ItemCount{Status: 200, NotCounted: model.NotCountedNoArray}, sentBracket(stat(202, 5, "")),
			model.VerdictInconclusive, nil, "no array at /products", true, false},
		"not 2xx": {ItemCount{Status: 503, NotCounted: model.NotCountedStatus}, sentBracket(),
			model.VerdictInconclusive, nil, "answered 503", true, false},
	} {
		counter := &countingCounter{count: c.count}
		var components []string
		reading := runPerItem(t, "lab", Request{}, counter,
			fakeStatements{bracket: c.bracket, database: "shop-db", components: &components})
		if reading.Verdict != c.verdict || !strings.Contains(reading.Reason, c.reason) {
			t.Errorf("%s: %s: %s", name, reading.Verdict, reading.Reason)
		}
		if got := counter.gets.Load(); (got == 1) != c.sent || got > 1 {
			t.Errorf("%s: %d GET(s)", name, got)
		}
		if strings.Join(components, ",") != "shop" {
			t.Errorf("%s: the bracket was asked about %v, not the route's component", name, components)
		}
		_, measuredStatements := reading.Measured["statements"]
		if measuredStatements != c.measuring {
			t.Errorf("%s: statements kept: %v", name, measuredStatements)
		}
		if c.perItem != nil {
			perItem, _ := reading.Measured["per_item"].([]string)
			if strings.Join(perItem, ",") != strings.Join(c.perItem, ",") {
				t.Errorf("%s: per_item %v, want %v", name, perItem, c.perItem)
			}
		}
		if reading.Measured["database"] != "shop-db" || reading.Measured["quiet_calls"] == nil {
			t.Errorf("%s: measured %v", name, reading.Measured)
		}
	}
}

func TestAGetThatFailsMeasuresNothing(t *testing.T) {
	counter := &countingCounter{err: errors.New("connection refused")}
	reading := runPerItem(t, "lab", Request{}, counter, fakeStatements{bracket: sentBracket(stat(202, 5, ""))})
	if reading.Verdict != model.VerdictInconclusive || !strings.Contains(reading.Reason, "did not complete") {
		t.Errorf("%s: %s", reading.Verdict, reading.Reason)
	}
	if _, kept := reading.Measured["statements"]; kept {
		t.Error("statements were kept from a bracket whose GET failed")
	}
}

// TestTheStatementsKeptAreCappedNamedFirst: more statements than a reading
// keeps; every one named is kept, ahead of the rest, and the rest counted.
func TestTheStatementsKeptAreCappedNamedFirst(t *testing.T) {
	var statements []capture.StatementStats
	for index := int64(0); index < 30; index++ {
		statements = append(statements, stat(1000+index, 1, ""))
	}
	statements = append(statements, stat(-9, 5, ""), stat(7, 6, ""))
	counter := &countingCounter{count: ItemCount{Status: 200, Items: 5, Counted: true}}
	reading := runPerItem(t, "lab", Request{}, counter, fakeStatements{bracket: sentBracket(statements...)})
	kept, _ := reading.Measured["statements"].([]any)
	if len(kept) != model.StatementReadingMax || reading.Measured["other_statements"] != 12 {
		t.Fatalf("kept %d, other %v", len(kept), reading.Measured["other_statements"])
	}
	perItem, _ := reading.Measured["per_item"].([]string)
	if strings.Join(perItem, ",") != "7,-9" {
		t.Errorf("per_item %v", perItem)
	}
}

// TestNoValueIsKept: the list's items, through the real guarded client, and
// the statements' texts hold secret-looking strings; the reading holds none
// of them, and its measured holds only the decided keys.
func TestNoValueIsKept(t *testing.T) {
	server, seen := listServer(t)
	reading := runPerItem(t, "lab", Request{Inputs: map[string]any{"base_url": server.URL, "at": "/products"}},
		NewRealHTTPClient(5*time.Second), fakeStatements{database: "shop-db", bracket: sentBracket(
			stat(202, 50, "SELECT name FROM tags WHERE secret = 'password=hunter2-SECRET'"),
			stat(101, 1, "postgresql://app:sk_live_SECRETKEY@db/shop"),
		)})
	if reading.Verdict != model.VerdictPass || reading.Measured["items"] != 50 {
		t.Fatalf("%s: %s %v", reading.Verdict, reading.Reason, reading.Measured)
	}
	encoded, err := json.Marshal(reading)
	if err != nil {
		t.Fatal(err)
	}
	for _, secret := range []string{"hunter2", "sk_live", "authorization_token", "private.example", "eyJ", "email", "SECRET"} {
		if strings.Contains(string(encoded), secret) {
			t.Errorf("the reading holds %q: %s", secret, encoded)
		}
	}
	for key := range reading.Measured {
		switch key {
		case "url", "method", "at", "database", "quiet_window_s", "quiet_calls", "status", "items",
			"statements", "other_statements", "statements_too_large", "per_item":
		default:
			t.Errorf("measured holds %q", key)
		}
	}
	for _, statement := range reading.Measured["statements"].([]any) {
		for key := range statement.(map[string]any) {
			if key != "queryid" && key != "calls" && key != "text" {
				t.Errorf("a statement holds %q", key)
			}
		}
	}
	if len(*seen) != 1 {
		t.Errorf("%d GET(s) were sent", len(*seen))
	}
}

func TestOnlyTheTargetRouteIsSent(t *testing.T) {
	server, seen := listServer(t)
	for name, request := range map[string]Request{
		"a query":         {Inputs: map[string]any{"url": server.URL + "/products?limit=1000"}},
		"another path":    {Inputs: map[string]any{"url": server.URL + "/everything"}},
		"userinfo":        {Inputs: map[string]any{"url": strings.Replace(server.URL, "http://", "http://u:p@", 1) + "/products"}},
		"a POST route":    {Target: "http:shop/POST /products", Inputs: map[string]any{"base_url": server.URL}},
		"not a route":     {Target: "component:shop", Inputs: map[string]any{"url": server.URL + "/products"}},
		"a bad pointer":   {Inputs: map[string]any{"base_url": server.URL, "at": "products"}},
		"a method of PUT": {Inputs: map[string]any{"base_url": server.URL, "method": "PUT"}},
	} {
		calls := 0
		reading := runPerItem(t, "lab", request, NewRealHTTPClient(5*time.Second),
			fakeStatements{bracket: sentBracket(), calls: &calls})
		if reading.Verdict != model.VerdictInconclusive || calls != 0 {
			t.Errorf("%s: %s (%s), %d database call(s)", name, reading.Verdict, reading.Reason, calls)
		}
	}
	if len(*seen) != 0 {
		t.Errorf("%d request(s) were sent", len(*seen))
	}
}

func TestTheDatabaseIsTheRoutesOneSQLEdge(t *testing.T) {
	for name, connections := range map[string]string{
		"none": "", "two": `
    connections:
      - {to: shop-db, kind: sql, criticality: on_request_path}
      - {to: audit-db, kind: sql, criticality: background}`,
	} {
		path := filepath.Join(t.TempDir(), "culprit.yaml")
		if err := os.WriteFile(path, []byte(`version: 1
components:
  - name: shop
    kind: service`+connections+`
  - name: shop-db
    kind: database
  - name: audit-db
    kind: database
environments:
  lab:
    adapter: process
    isolated: true
    components:
      shop:
        database: {dsn_env: SHOP_DSN}
`), 0o600); err != nil {
			t.Fatal(err)
		}
		manifest, err := extract.LoadManifest(path)
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		sources := &Sources{Environment: "lab", Spec: manifest.Environments["lab"], Manifest: manifest,
			LookupEnv: func(string) (string, bool) { return "postgresql://u:p@127.0.0.1:1/x", true }}
		called := false
		_, _, err = sources.Statements().Bracket(context.Background(), "shop", func(context.Context) error {
			called = true
			return nil
		})
		var unavailable *UnavailableError
		if !errors.As(err, &unavailable) || called {
			t.Errorf("%s: %v, sent %v", name, err, called)
		}
	}
}

func TestTheStatementsPerRequestProbeIsTheOneTheRuleNames(t *testing.T) {
	manifest := dbStatementsPerRequest{}.Manifest()
	if manifest.ID != model.StatementsPerRequestProbeID {
		t.Fatal("the probe is not model.StatementsPerRequestProbeID")
	}
	if manifest.ExpectedFrom != "" || manifest.Declares(model.VerdictFail) {
		t.Error("the probe is evidence: no expectation, and no fail to give")
	}
	want := []string{string(capability.DBStatsRead), string(capability.NetHTTPOutbound)}
	if strings.Join(manifest.Capabilities, ",") != strings.Join(want, ",") {
		t.Errorf("capabilities %v", manifest.Capabilities)
	}
}
