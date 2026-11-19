// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package probe

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// probe.http.response_items against a fake server (Phase 38 part 2's
// criteria): through the real guarded client, so what is sent, what is
// read and what is kept are the binary's own.

// secretItem is an item whose keys and values look like credentials: none
// of them may reach a reading.
func secretItem(index int) map[string]any {
	return map[string]any{
		"sk_live_SECRETKEY":   fmt.Sprintf("password=hunter2-%d", index),
		"authorization_token": "Bearer eyJhbGciOiJIUzI1NiJ9.SECRET.PAYLOAD",
		"email":               fmt.Sprintf("customer-%d@private.example", index),
	}
}

func listServer(t *testing.T) (*httptest.Server, *[]http.Header) {
	t.Helper()
	var seen []http.Header
	items := func(n int) []any {
		out := make([]any, n)
		for index := range out {
			out[index] = secretItem(index)
		}
		return out
	}
	write := func(w http.ResponseWriter, value any) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(value)
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/products", func(w http.ResponseWriter, r *http.Request) {
		write(w, map[string]any{"products": items(50), "category": "SECRET-CATEGORY"})
	})
	mux.HandleFunc("/everything", func(w http.ResponseWriter, r *http.Request) {
		write(w, items(51))
	})
	mux.HandleFunc("/page", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte("<html>SECRET-HTML</html>"))
	})
	mux.HandleFunc("/single", func(w http.ResponseWriter, r *http.Request) {
		write(w, map[string]any{"product": secretItem(0)})
	})
	mux.HandleFunc("/gone", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
		write(w, items(3))
	})
	mux.HandleFunc("/moved", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "/everything", http.StatusFound)
	})
	mux.HandleFunc("/huge", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte("[" + strings.Repeat(`"SECRET-PADDING",`, 80_000) + `"end"]`))
	})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = append(seen, r.Header.Clone())
		if r.Method != http.MethodGet || r.URL.RawQuery != "" {
			t.Errorf("the probe sent %s %s", r.Method, r.URL)
		}
		mux.ServeHTTP(w, r)
	}))
	t.Cleanup(server.Close)
	return server, &seen
}

func countAt(t *testing.T, server *httptest.Server, path string, bound int, at string) Outcome {
	t.Helper()
	fact := declaredAs("http:shop/GET "+path, "response_items_max", model.ListBudgetValue(bound, at))
	return httpResponseItems{}.Run(context.Background(), Request{
		ProbeID: "probe.http.response_items", Target: "http:shop/GET " + path, Environment: "staging",
		Inputs:      map[string]any{"base_url": server.URL},
		Expectation: fact,
	}, Deps{HTTP: NewRealHTTPClient(5 * time.Second), Now: fixedClock()})
}

func TestAListOverItsBoundFailsAndWithinItPasses(t *testing.T) {
	server, _ := listServer(t)
	for _, c := range []struct {
		name, path, at string
		bound          int
		want           model.Verdict
		items          int
	}{
		{"an envelope at its bound", "/products", "/products", 50, model.VerdictPass, 50},
		{"an envelope one under", "/products", "/products", 49, model.VerdictFail, 50},
		{"a top-level list over", "/everything", "", 50, model.VerdictFail, 51},
		{"a top-level list within", "/everything", "", 100, model.VerdictPass, 51},
	} {
		outcome := countAt(t, server, c.path, c.bound, c.at)
		if outcome.Verdict != c.want || outcome.Measured["items"] != c.items {
			t.Errorf("%s: %s %v (%s)", c.name, outcome.Verdict, outcome.Measured, outcome.Reason)
		}
		if c.want == model.VerdictFail && !strings.Contains(outcome.Reason, fmt.Sprintf("holds %d items", c.items)) {
			t.Errorf("%s: the reason does not say how many: %q", c.name, outcome.Reason)
		}
	}
}

func TestAListThatCannotBeCountedIsInconclusiveSayingWhy(t *testing.T) {
	server, _ := listServer(t)
	for _, c := range []struct{ name, path, at, why string }{
		{"not JSON", "/page", "", "not JSON"},
		{"no array at the pointer", "/single", "/products", "no array at /products"},
		{"an object at the top", "/single", "", "no array at the top level"},
		{"not 2xx", "/gone", "", "answered 404, not 2xx"},
		{"a redirect, not followed", "/moved", "", "answered 302, not 2xx"},
		{"larger than the read cap", "/huge", "", "larger than the 1 MiB"},
	} {
		outcome := countAt(t, server, c.path, 50, c.at)
		if outcome.Verdict != model.VerdictInconclusive || !strings.Contains(outcome.Reason, c.why) {
			t.Errorf("%s: %s (%s), want inconclusive saying %q", c.name, outcome.Verdict, outcome.Reason, c.why)
		}
		if _, counted := outcome.Measured["items"]; counted {
			t.Errorf("%s: counted %v", c.name, outcome.Measured)
		}
	}
}

// TestNoItemKeyOrValueIsKept: the reading holds a count, the route and
// why — never anything from inside the body, and the probe sends no header.
func TestNoItemKeyOrValueIsKept(t *testing.T) {
	server, seen := listServer(t)
	for _, path := range []string{"/products", "/everything", "/page", "/single", "/gone", "/huge"} {
		outcome := countAt(t, server, path, 50, map[bool]string{true: "/products", false: ""}[path == "/products" || path == "/single"])
		encoded, err := json.Marshal(outcome)
		if err != nil {
			t.Fatal(err)
		}
		for _, secret := range []string{"SECRET", "hunter2", "sk_live", "authorization_token", "private.example", "eyJ", "email", "category"} {
			if strings.Contains(string(encoded), secret) {
				t.Errorf("%s: the outcome holds %q: %s", path, secret, encoded)
			}
		}
		for key := range outcome.Measured {
			switch key {
			case "url", "method", "at", "status", "items", "not_counted":
			default:
				t.Errorf("%s: measured holds %q", path, key)
			}
		}
	}
	for _, header := range *seen {
		for name := range header {
			switch name {
			case "User-Agent", "Accept-Encoding":
			default:
				t.Errorf("the probe sent a %s header", name)
			}
		}
	}
}

func TestAListBudgetIsCountedOnlyOnItsOwnRoute(t *testing.T) {
	server, seen := listServer(t)
	fact := declaredAs("http:shop/GET /products", "response_items_max", model.ListBudgetValue(50, "/products"))
	for _, url := range []string{
		server.URL + "/products?limit=1000",
		server.URL + "/everything",
		strings.Replace(server.URL, "http://", "http://user:secret@", 1) + "/products",
	} {
		outcome := httpResponseItems{}.Run(context.Background(), Request{
			ProbeID: "probe.http.response_items", Target: "http:shop/GET /products", Environment: "staging",
			Inputs: map[string]any{"url": url}, Expectation: fact,
		}, Deps{HTTP: NewRealHTTPClient(5 * time.Second), Now: fixedClock()})
		if outcome.Verdict != model.VerdictInconclusive || !strings.Contains(outcome.Reason, "nothing was sent") {
			t.Errorf("%s: %s (%s)", url, outcome.Verdict, outcome.Reason)
		}
	}
	if len(*seen) != 0 {
		t.Errorf("%d request(s) were sent", len(*seen))
	}
}

func TestTheListProbeIsTheOneTheRuleNames(t *testing.T) {
	if (httpResponseItems{}).Manifest().ID != model.ResponseItemsProbeID {
		t.Fatal("probe.http.response_items is not model.ResponseItemsProbeID")
	}
}

func TestAPointerIsCountedThroughItsTokens(t *testing.T) {
	counter := &fakeCounter{count: ItemCount{Status: 200, Items: 1, Counted: true}}
	fact := declaredAs("http:shop/GET /products", "response_items_max", model.ListBudgetValue(5, "/data/a~1b/0"))
	outcome := httpResponseItems{}.Run(context.Background(), Request{
		ProbeID: "probe.http.response_items", Target: "http:shop/GET /products", Environment: "staging",
		Inputs: map[string]any{"base_url": "http://shop.internal"}, Expectation: fact,
	}, Deps{HTTP: counter, Now: fixedClock()})
	if outcome.Verdict != model.VerdictPass || strings.Join(counter.tokens, "|") != "data|a/b|0" {
		t.Errorf("%s, tokens %q", outcome.Verdict, counter.tokens)
	}
}
