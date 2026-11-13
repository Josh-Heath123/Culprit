package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/probe"
)

// Phase 37 part 2's criteria on the demo's own database (P8), in CI: the
// quickstart's setup and migrations seed it, pg_stat_statements is
// preloaded, and test traffic — not Culprit — runs the products route's
// query as inventory-service's own role.
//
//   - Without an index on category, the window finds that statement over
//     the demo's 20 ms budget on products, and its plan is a sequential scan
//     of products filtering category.
//   - With one (created here, in this test database), the plan is an index
//     scan and the window is within budget.
//   - A CREATE ROLE ... PASSWORD (as Culprit's own migrations run, in this
//     server's other database, and in this one), and a statement in another
//     database, appear in no reading — while the products statement's text
//     is kept.

const statementsE2EManifest = `version: 1
components:
  - name: inventory-service
    kind: service
    connections:
      - to: inventory-db
        kind: sql
        criticality: background
  - name: inventory-db
    kind: database
environments:
  local:
    adapter: process
    components:
      inventory-service:
        database: { dsn_env: CULPRIT_TEST_INVENTORY_STATS_DSN, name: inventory-db }
    grants:
      db.stats.read: true
      db.plan.read: true
budgets:
  - subject: "schema:inventory-db/public.products"
    predicate: query_mean_ms_max
    value: 20
    why: the demo's own budget on the list route's table
`

// migrationRoles numbers the roles trafficDuring creates.
var migrationRoles int64

const (
	migrationPassword = "culprit-migration-role-password-not-a-secret"
	productsQuery     = "SELECT sku, name, price_cents FROM products WHERE category = 'category-7' ORDER BY sku LIMIT 50"
)

func startPostgresWithStatements(t *testing.T) (container, address string) {
	t.Helper()
	out, err := exec.Command("docker", "run", "-d", "--rm", "-e", "POSTGRES_PASSWORD=index-test",
		"-e", "POSTGRES_DB=shop", "-p", "127.0.0.1::5432", "postgres:16-alpine",
		"postgres", "-c", "shared_preload_libraries=pg_stat_statements").CombinedOutput()
	if err != nil {
		t.Fatalf("docker run: %v\n%s", err, out)
	}
	container = strings.TrimSpace(string(out))
	t.Cleanup(func() { _ = exec.Command("docker", "rm", "-f", container).Run() })
	// Ready over TCP, not the socket: the image's first-boot server listens
	// on the socket only and is then restarted, so a socket check can pass
	// before the server the test connects to is up.
	deadline := time.Now().Add(90 * time.Second)
	for exec.Command("docker", "exec", container, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-d", "shop").Run() != nil {
		if time.Now().After(deadline) {
			t.Fatal("the test Postgres did not become ready")
		}
		time.Sleep(time.Second)
	}
	port, err := exec.Command("docker", "port", container, "5432/tcp").Output()
	if err != nil {
		t.Fatalf("docker port: %v", err)
	}
	return container, strings.TrimSpace(strings.Split(string(port), "\n")[0])
}

// runSQL runs SQL in the container as a role, through psql — the owner,
// or the application, never culprit.
func runSQL(t *testing.T, container, user, password, database, sql string) error {
	t.Helper()
	out, err := exec.Command("docker", "exec", "-e", "PGPASSWORD="+password, container, "psql",
		"-v", "ON_ERROR_STOP=1", "-q", "-h", "127.0.0.1", "-U", user, "-d", database, "-c", sql).CombinedOutput()
	if err != nil {
		t.Logf("psql as %s in %s: %v\n%s", user, database, err, out)
	}
	return err
}

// trafficDuring runs, until stop is closed and inside the window:
//   - the products query as inventory-service's role;
//   - a statement in the other database;
//   - CREATE ROLE ... PASSWORD, as Culprit's migrations create their roles,
//     in this database and in the other, once per window (one each: more would
//     crowd the fast products statement out of the 20 a reading keeps).
//
// The role statements must fall inside the window: run before it, their
// calls do not move and the window drops them unread, so a check on them
// would hold even with no text filter (phase-auditor, 2026-11-13).
func trafficDuring(t *testing.T, container string, stop <-chan struct{}) *sync.WaitGroup {
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		batch := strings.Repeat(productsQuery+";", 5)
		rolesMade := false
		for {
			select {
			case <-stop:
				return
			default:
			}
			_ = runSQL(t, container, "inventory", "inventory-test", "inventory", batch)
			_ = runSQL(t, container, "postgres", "index-test", "shop", "SELECT 4242 AS other_database_marker")
			for _, database := range []string{"shop", "inventory"} {
				if rolesMade {
					break
				}
				n := atomic.AddInt64(&migrationRoles, 1)
				_ = runSQL(t, container, "postgres", "index-test", database,
					fmt.Sprintf("CREATE ROLE migration_role_%d LOGIN PASSWORD '%s'", n, migrationPassword))
			}
			rolesMade = true
		}
	}()
	return &wg
}

func TestTheStatementProbesOnTheDemoDatabase(t *testing.T) {
	if os.Getenv("CULPRIT_DOCKER_TESTS") != "1" {
		t.Skip("NOT RUN: set CULPRIT_DOCKER_TESTS=1 to run the statement probes on the demo's database (needs Docker, uv)")
	}
	container, address := startPostgresWithStatements(t)
	host, port, _ := strings.Cut(address, ":")
	inventory := "postgresql://inventory:inventory-test@" + address + "/inventory?sslmode=disable"
	setup := exec.Command("uv", "run", "--project", ".", "python", "-m", "inventory_service.setup_db")
	setup.Dir = filepath.Join(repoRoot, "demo-services")
	setup.Env = append(os.Environ(),
		"INVENTORY_ADMIN_HOST="+host, "INVENTORY_ADMIN_PORT="+port, "INVENTORY_ADMIN_USER=postgres",
		"INVENTORY_ADMIN_PASSWORD=index-test", "INVENTORY_ADMIN_DB=shop", "INVENTORY_DATABASE_URL="+inventory)
	if out, err := setup.CombinedOutput(); err != nil {
		t.Fatalf("the demo's database setup: %v\n%s", err, out)
	}
	// The reading role: pg_read_all_stats, and SELECT on what it plans.
	if err := runSQL(t, container, "postgres", "index-test", "inventory", `
		CREATE ROLE culprit_reader LOGIN PASSWORD 'reader-test' IN ROLE pg_read_all_stats;
		GRANT SELECT ON products TO culprit_reader;`); err != nil {
		t.Fatal(err)
	}
	t.Setenv("CULPRIT_TEST_INVENTORY_STATS_DSN",
		"postgresql://culprit_reader:reader-test@"+address+"/inventory?sslmode=disable")
	manifest := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(manifest, []byte(statementsE2EManifest), 0o600); err != nil {
		t.Fatal(err)
	}

	window := func(name string) model.Reading {
		t.Helper()
		stop := make(chan struct{})
		traffic := trafficDuring(t, container, stop)
		readings, _, err := runProbe(context.Background(), probeInput{
			ManifestPath: manifest, Environment: "local", Target: "component:inventory-db",
			ProbeIDs: []string{model.StatementProbeID}, AgentID: "test", NoPlugins: true,
			Timeout: 30 * time.Second,
		})
		close(stop)
		traffic.Wait()
		if err != nil || len(readings) != 1 {
			t.Fatalf("%s: %v %+v", name, err, readings)
		}
		return readings[0]
	}
	plan := func(queryID string) model.Reading {
		t.Helper()
		readings, _, err := runProbe(context.Background(), probeInput{
			ManifestPath: manifest, Environment: "local", Target: "component:inventory-db",
			ProbeIDs: []string{model.PlanProbeID}, Inputs: map[string]any{"queryid": queryID},
			AgentID: "test", NoPlugins: true, Timeout: 30 * time.Second,
		})
		if err != nil || len(readings) != 1 {
			t.Fatalf("plan: %v %+v", err, readings)
		}
		return readings[0]
	}
	noSecret := func(reading model.Reading) string {
		t.Helper()
		raw, _ := json.Marshal(reading)
		for _, secret := range []string{migrationPassword, "PASSWORD", "other_database_marker", "category-7"} {
			if strings.Contains(string(raw), secret) {
				t.Errorf("a %s reading holds %q", reading.ProbeID, secret)
			}
		}
		return string(raw)
	}
	products := func(reading model.Reading) map[string]any {
		t.Helper()
		raw := noSecret(reading)
		statements, _ := reading.Measured["statements"].([]any)
		for _, item := range statements {
			statement, _ := item.(map[string]any)
			if text, _ := statement["text"].(string); strings.Contains(text, "FROM products WHERE category = $1") {
				return statement
			}
		}
		t.Fatalf("the products statement is not in the reading: %s", raw)
		return nil
	}
	nodes := func(reading model.Reading) string {
		raw, _ := json.Marshal(reading.Measured["nodes"])
		return string(raw)
	}

	before := window("without an index")
	statement := products(before)
	// The CREATE ROLE ... PASSWORD statements ran inside the window, so the
	// reading lists them, by queryid and timings, with their text not kept:
	// the check on the password above is not vacuous.
	unkept := 0
	statements, _ := before.Measured["statements"].([]any)
	for _, item := range statements {
		if entry, _ := item.(map[string]any); entry["text"] == probe.TextNotKept {
			unkept++
		}
	}
	if unkept == 0 {
		t.Fatalf("no statement in the window was listed without its text; the role statements were not read: %s", noSecret(before))
	}
	measured := func(label string, s map[string]any) {
		number := func(value any) float64 {
			switch v := value.(type) {
			case int:
				return float64(v)
			case int64:
				return float64(v)
			case float64:
				return v
			}
			t.Fatalf("not a number in the reading: %#v", value)
			return 0
		}
		calls, total := number(s["calls"]), number(s["total_us"])
		mean := 0.0
		if calls > 0 {
			mean = total / calls / 1000
		}
		t.Logf("MEASURED %s: %.0f calls, %.0f µs in the window, mean %.3f ms against the 20 ms budget", label, calls, total, mean)
	}
	measured("without an index on category", statement)
	if before.Verdict != model.VerdictFail || statement["budget_on"] != "public.products" {
		t.Fatalf("without an index: %s (%s), budget on %v; want the products statement over the table's 20 ms",
			before.Verdict, before.Reason, statement["budget_on"])
	}
	// Without an index on category, products is read row by row with
	// category filtered: Postgres 16 walks the sku index (the route orders by
	// sku, with a LIMIT) rather than scanning the heap in sequence, and
	// either way no index on category is used. (The criterion said "a
	// sequential scan"; this is what Postgres plans for the demo's query —
	// recorded in the run report.)
	seq := plan(statement["queryid"].(string))
	if seq.Verdict != model.VerdictPass ||
		!strings.Contains(nodes(seq), `"filter_columns":["category"]`) ||
		!strings.Contains(nodes(seq), `"relation":"public.products"`) ||
		strings.Contains(nodes(seq), "category\"") && strings.Contains(nodes(seq), "ix_products_category") {
		t.Fatalf("the plan without an index does not read products filtering category: %s %s", seq.Reason, nodes(seq))
	}
	t.Logf("the plan without an index on category: %s", nodes(seq))
	noSecret(seq)

	// An index on category alone, measured and logged, not asserted: it does
	// not bring the route's query within budget (the route orders by sku with
	// a LIMIT), which the architecture session noted for part 3 on
	// 2026-11-13. The run report records both times.
	if err := runSQL(t, container, "postgres", "index-test", "inventory",
		"CREATE INDEX ix_products_category_only ON products (category); ANALYZE products"); err != nil {
		t.Fatal(err)
	}
	categoryOnly := window("with an index on category alone")
	measured("with an index on category alone", products(categoryOnly))
	t.Logf("verdict with an index on category alone: %s", categoryOnly.Verdict)
	if err := runSQL(t, container, "postgres", "index-test", "inventory",
		"DROP INDEX ix_products_category_only; CREATE INDEX ix_products_category ON products (category, sku); ANALYZE products"); err != nil {
		t.Fatal(err)
	}
	after := window("with an index")
	statement = products(after)
	measured("with the index on (category, sku)", statement)
	if after.Verdict != model.VerdictPass {
		t.Fatalf("with an index on category: %s (%s); want within the 20 ms budget", after.Verdict, after.Reason)
	}
	indexed := plan(statement["queryid"].(string))
	if !strings.Contains(nodes(indexed), "ix_products_category") {
		t.Fatalf("the plan with an index does not use it: %s", nodes(indexed))
	}
	t.Logf("the plan with an index on category: %s", nodes(indexed))
	noSecret(indexed)
}
