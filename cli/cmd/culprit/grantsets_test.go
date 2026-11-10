package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/agent"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/probe"
)

// The minimum grant set for each investigation class (Phase 33 part 3).
//
// docs/PERMISSIONS.md documents, for each class of investigation, the
// smallest set of grants with which an agent can complete one. This test
// reads those sets from that file — so what is documented is what is run —
// and, for each class, has a real agent walk a fault of that class with
// exactly the documented grants (the diagnosis must be complete), then
// with each grant removed in turn (the diagnosis must be partial, and must
// name the grant it lacked).
//
// The probes, the walk, the capability gate and the agent are all real.
// Only the world is not: the network, the HTTP answers and the database are
// fakes that hold one fault each, so every class runs here, on every
// platform, with no Docker.

// classWorld is one fault, written down.
type classWorld struct {
	refused map[string]bool // "host:port" a TCP connection to is refused
	status  map[string]int  // URL -> HTTP status; anything unlisted answers 200
	dbDown  map[string]bool // databases that refuse a connection
}

func (w *classWorld) Resolve(context.Context, string) ([]string, error) {
	return []string{"192.0.2.10"}, nil
}

func (w *classWorld) Dial(_ context.Context, host string, port int) error {
	if w.refused[fmt.Sprintf("%s:%d", host, port)] {
		return errors.New("connect: connection refused")
	}
	return nil
}

func (w *classWorld) InspectTLS(context.Context, string, int, time.Time) (probe.TLSStatus, error) {
	return "", errors.New("no TLS in this world")
}

func (w *classWorld) answer(url string) (probe.HTTPResponse, error) {
	status, listed := w.status[url]
	if !listed {
		status = 200
	}
	return probe.HTTPResponse{Status: status, ContentType: "application/json", BodyKind: "object"}, nil
}

func (w *classWorld) Get(_ context.Context, url string, _ map[string]string) (probe.HTTPResponse, error) {
	return w.answer(url)
}

func (w *classWorld) Options(_ context.Context, url string, _ map[string]string) (probe.HTTPResponse, error) {
	return w.answer(url)
}

func (w *classWorld) Connect(_ context.Context, database string) error {
	if w.dbDown[database] {
		return errors.New("connection refused")
	}
	return nil
}

func (w *classWorld) Columns(context.Context, string, string, string) ([]probe.TableColumn, error) {
	return nil, nil
}

// investigationClass is one row of the documented table, with the fault
// that exercises it.
type investigationClass struct {
	name     string // as docs/PERMISSIONS.md names it
	manifest string // the system model
	world    classWorld
	env      map[string]string // the vantage process's environment
	symptom  string
	root     string // the subject a complete diagnosis must root at
}

// unsignedJWT is a token whose claims token_shape can read. Its signature
// is never checked by the probe — it inspects the shape, not the trust.
func unsignedJWT(audience string) string {
	encode := func(v any) string {
		raw, _ := json.Marshal(v)
		return base64.RawURLEncoding.EncodeToString(raw)
	}
	return encode(map[string]any{"alg": "HS256", "typ": "JWT"}) + "." +
		encode(map[string]any{"aud": audience, "iss": "test", "exp": time.Now().Add(time.Hour).Unix()}) +
		".c2lnbmF0dXJl"
}

const classModelHead = `version: 1
components:
  - name: shop
    kind: service
    connections:
      - to: %s
        kind: %s
        criticality: on_request_path
  - name: %s
    kind: %s
`

func classes() []investigationClass {
	shopHealth := "http://shop.internal:8000/health"
	return []investigationClass{
		{
			name: "reachability",
			manifest: fmt.Sprintf(classModelHead, "stock", "http", "stock", "service") + `environments:
  production:
    adapter: process
    components:
      shop: {}
    endpoints:
      shop: { host: shop.internal, port: 8000, health_path: /health }
      stock: { host: stock.internal, port: 8100, health_path: /health }
`,
			// shop cannot open a connection to stock; stock itself is fine.
			world: classWorld{
				refused: map[string]bool{"stock.internal:8100": true},
				status:  map[string]int{shopHealth: 503},
			},
			symptom: "shop",
			root:    "connection:shop->stock",
		},
		{
			name: "schema",
			manifest: fmt.Sprintf(classModelHead, "orders-db", "sql", "orders-db", "database") + `environments:
  production:
    adapter: process
    components:
      shop: {}
    endpoints:
      shop: { host: shop.internal, port: 8000, health_path: /health }
`,
			// shop's database refuses it.
			world: classWorld{
				dbDown: map[string]bool{"orders-db": true},
				status: map[string]int{shopHealth: 503},
			},
			symptom: "shop",
			root:    "connection:shop->orders-db",
		},
		{
			name: "auth and audience",
			manifest: fmt.Sprintf(classModelHead, "stock", "http", "stock", "service") + `invariants:
  - subject: "auth:shop->stock/audience"
    predicate: audience
    value: stock
    why: stock accepts only tokens minted for it
environments:
  production:
    adapter: process
    components:
      shop:
        tokens:
          stock: STOCK_TOKEN
    endpoints:
      shop: { host: shop.internal, port: 8000, health_path: /health }
      stock: { host: stock.internal, port: 8100, health_path: /health }
`,
			// shop presents a token minted for the wrong audience; stock
			// refuses it, so shop fails. Every connection is open.
			world:   classWorld{status: map[string]int{shopHealth: 502}},
			env:     map[string]string{"STOCK_TOKEN": unsignedJWT("inventory")},
			symptom: "shop",
			root:    "auth:shop->stock/audience",
		},
		{
			name: "configuration",
			manifest: `version: 1
components:
  - name: shop
    kind: service
invariants:
  - subject: "config:shop/PAYMENT_KEY"
    predicate: required
    value: true
    why: shop cannot take a payment without it
environments:
  production:
    adapter: process
    components:
      shop: {}
    endpoints:
      shop: { host: shop.internal, port: 8000, health_path: /health }
`,
			// PAYMENT_KEY is not set where shop runs.
			world:   classWorld{status: map[string]int{shopHealth: 500}},
			symptom: "shop",
			root:    "config:shop/PAYMENT_KEY",
		},
	}
}

// walkWith has a real agent walk the class's fault holding exactly grants.
func walkWith(t *testing.T, class investigationClass, grants string) model.Investigation {
	t.Helper()
	for name, value := range class.env {
		t.Setenv(name, value)
	}
	// The configuration class's key must be absent, whatever the machine
	// running the test has set.
	t.Setenv("PAYMENT_KEY", "")
	os.Unsetenv("PAYMENT_KEY")

	world := newAgentWorld(t, class.manifest, "")
	fault := class.world
	world.agent.Executor = &agentExecutor{timeout: 2 * time.Second, wire: func(time.Duration) wire {
		return wire{Network: &fault, HTTP: &fault, Database: &fault}
	}}
	world.configure(grants)

	id := fmt.Sprintf("walk-%d", time.Now().UnixNano())
	world.submit(agent.Task{ID: id, Environment: "production", Kind: agent.TaskDiagnose,
		Diagnose: &agent.DiagnoseTask{Symptom: class.symptom, From: "shop"}})
	world.drain()
	result := world.result(id)
	if result.Investigation == nil {
		t.Fatalf("no investigation: %s %q", result.Outcome, result.Reason)
	}
	return *result.Investigation
}

// documentedGrantSets reads the table under "The minimum grants for each
// kind of investigation" in docs/PERMISSIONS.md: class name -> grants.
func documentedGrantSets(t *testing.T) map[string][]string {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(repoRoot, "docs", "PERMISSIONS.md"))
	if err != nil {
		t.Fatal(err)
	}
	text := strings.ReplaceAll(string(raw), "\r\n", "\n")
	const heading = "## The minimum grants for each kind of investigation"
	start := strings.Index(text, heading)
	if start < 0 {
		t.Fatalf("docs/PERMISSIONS.md has no section %q", heading)
	}
	section := text[start+len(heading):]
	if end := strings.Index(section, "\n## "); end >= 0 {
		section = section[:end]
	}
	sets := map[string][]string{}
	for _, line := range strings.Split(section, "\n") {
		cells := strings.Split(line, "|")
		if len(cells) < 4 {
			continue
		}
		class := strings.TrimSpace(cells[1])
		if class == "" || class == "Investigation class" || strings.HasPrefix(class, "---") {
			continue
		}
		var grants []string
		for index, part := range strings.Split(cells[2], "`") {
			// Odd pieces are the ones inside backticks.
			if index%2 == 1 {
				grants = append(grants, strings.TrimSpace(part))
			}
		}
		sets[class] = grants
	}
	return sets
}

// grantsNamed is a configuration's grants, from bare names. The one per-item
// grant any class uses is the caller's token, by its variable.
func grantsNamed(names []string) string {
	var lines []string
	for _, name := range names {
		value := "true"
		if name == "config.inspect.values" {
			value = "[shop/STOCK_TOKEN]"
		}
		lines = append(lines, fmt.Sprintf("      %s: %s\n", name, value))
	}
	return strings.Join(lines, "")
}

func TestEachInvestigationClassCompletesWithExactlyItsDocumentedGrants(t *testing.T) {
	documented := documentedGrantSets(t)
	byName := map[string]investigationClass{}
	for _, class := range classes() {
		byName[class.name] = class
	}
	var disagree []string
	for name := range byName {
		if _, ok := documented[name]; !ok {
			disagree = append(disagree, name+" (has a fault here, but is not documented)")
		}
	}
	for name := range documented {
		if _, ok := byName[name]; !ok {
			disagree = append(disagree, name+" (documented, but this test has no fault for it)")
		}
	}
	sort.Strings(disagree)
	if len(disagree) > 0 {
		t.Fatalf("docs/PERMISSIONS.md and this test disagree about the classes: %v", disagree)
	}

	for name, grants := range documented {
		class := byName[name]
		t.Run(name, func(t *testing.T) {
			if len(grants) == 0 {
				t.Fatal("the documented set is empty")
			}
			inv := walkWith(t, class, grantsNamed(grants))
			if d := inv.Diagnosis; d == nil || !d.Complete || d.RootSubject != class.root {
				t.Fatalf("with exactly %v: diagnosis %+v, want complete at %s", grants, d, class.root)
			}
			for _, drop := range grants {
				var rest []string
				for _, grant := range grants {
					if grant != drop {
						rest = append(rest, grant)
					}
				}
				d := walkWith(t, class, grantsNamed(rest)).Diagnosis
				if d == nil || d.Complete {
					t.Errorf("without %s: the diagnosis is still complete, so %s is not in the minimum set", drop, drop)
					continue
				}
				if !strings.Contains(d.Statement, drop) {
					t.Errorf("without %s: partial, but the statement does not name it: %q", drop, d.Statement)
				}
			}
		})
	}
}
