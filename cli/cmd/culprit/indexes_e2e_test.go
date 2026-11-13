package main

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/capture"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Phase 37 part 1: index facts, declared and live, through the real
// commands against a real Postgres. The migration reader (the real Python
// extractor) declares items.id (the primary key) and items.sku (an index)
// as leading an index; capture reads which columns lead one in the live
// catalogue; the generic comparator compares them, with no special case.
//
//   - built as the migration declares: no leads_index finding;
//   - the index dropped by hand: declared but missing (sku);
//   - an index created by hand: live but undeclared (category).
//
// Gated on CULPRIT_DOCKER_TESTS=1, as TestEnvironmentDiffAgainstRealContainers
// is; CI's `cli` job sets it.

const indexesDir = "../../testdata/fixtures/indexed-shop"

// startPostgres runs a throwaway Postgres and returns a superuser DSN and a
// function that runs SQL in it as that superuser, through psql in the
// container — the owner changing the schema by hand, never culprit.
func startPostgres(t *testing.T) (string, func(sql string)) {
	t.Helper()
	out, err := exec.Command("docker", "run", "-d", "--rm", "-e", "POSTGRES_PASSWORD=index-test",
		"-e", "POSTGRES_DB=shop", "-p", "127.0.0.1::5432", "postgres:16-alpine").CombinedOutput()
	if err != nil {
		t.Fatalf("docker run: %v\n%s", err, out)
	}
	container := strings.TrimSpace(string(out))
	t.Cleanup(func() { _ = exec.Command("docker", "rm", "-f", container).Run() })
	psql := func(sql string) {
		t.Helper()
		if out, err := exec.Command("docker", "exec", container, "psql", "-v", "ON_ERROR_STOP=1",
			"-U", "postgres", "-d", "shop", "-c", sql).CombinedOutput(); err != nil {
			t.Fatalf("psql %q: %v\n%s", sql, err, out)
		}
	}
	deadline := time.Now().Add(90 * time.Second)
	for {
		// Over TCP, not the socket: the image's first-boot server listens on
		// the socket only and is then restarted.
		if err := exec.Command("docker", "exec", container, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-d", "shop").Run(); err == nil {
			if exec.Command("docker", "exec", container, "psql", "-h", "127.0.0.1", "-U", "postgres", "-d", "shop", "-c", "SELECT 1").Run() == nil {
				break
			}
		}
		if time.Now().After(deadline) {
			t.Fatal("the test Postgres did not become ready")
		}
		time.Sleep(time.Second)
	}
	port, err := exec.Command("docker", "port", container, "5432/tcp").Output()
	if err != nil {
		t.Fatalf("docker port: %v", err)
	}
	address := strings.TrimSpace(strings.Split(string(port), "\n")[0])
	return "postgresql://postgres:index-test@" + address + "/shop?sslmode=disable", psql
}

// leadsIndexFindings runs `culprit diff live again` and returns its
// leads_index findings in the live environment, as "subject".
func leadsIndexFindings(t *testing.T) []string {
	t.Helper()
	stdout, err := run(t, "diff", "live", "again", "-f", filepath.Join(indexesDir, "culprit.yaml"), "--format", "json")
	var findings *findingsError
	if err != nil && !errors.As(err, &findings) {
		t.Fatalf("culprit diff: %v\n%s", err, stdout)
	}
	var report struct {
		Divergences []struct {
			Kind      string `json:"kind"`
			Subject   string `json:"subject"`
			Predicate string `json:"predicate"`
			Right     struct {
				Environment string `json:"environment"`
			} `json:"right"`
		} `json:"divergences"`
	}
	if err := json.Unmarshal([]byte(stdout), &report); err != nil {
		t.Fatalf("the report is not JSON: %v\n%s", err, stdout)
	}
	var found []string
	for _, divergence := range report.Divergences {
		if divergence.Predicate == "leads_index" && divergence.Right.Environment == "live" {
			if divergence.Kind != "intent_vs_configured" {
				t.Errorf("%s: kind %s, want intent_vs_configured", divergence.Subject, divergence.Kind)
			}
			found = append(found, divergence.Subject)
		}
	}
	return found
}

func TestIndexesDeclaredAndLive(t *testing.T) {
	if os.Getenv("CULPRIT_DOCKER_TESTS") != "1" {
		t.Skip("NOT RUN: set CULPRIT_DOCKER_TESTS=1 to run the index end-to-end test (needs Docker, uv)")
	}
	for _, tool := range []string{"docker", "uv"} {
		if _, err := exec.LookPath(tool); err != nil {
			t.Fatalf("CULPRIT_DOCKER_TESTS=1 but %s is not on PATH", tool)
		}
	}
	dsn, psql := startPostgres(t)
	t.Setenv("CULPRIT_INDEX_DB_URL", dsn)
	t.Setenv("CULPRIT_INDEX_DB_URL_AGAIN", dsn)

	// The schema the migration declares, built by its owner by hand.
	psql(`CREATE TABLE items (id SERIAL PRIMARY KEY, sku VARCHAR(64) NOT NULL, category VARCHAR(64) NOT NULL);
		CREATE INDEX ix_items_sku ON items (sku);
		CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
		INSERT INTO alembic_version VALUES ('0001_create_items');`)
	if found := leadsIndexFindings(t); len(found) != 0 {
		t.Fatalf("the database as the migration declares it: leads_index findings %v, want none", found)
	}

	psql(`DROP INDEX ix_items_sku`)
	if found := leadsIndexFindings(t); strings.Join(found, ",") != "schema:shop-db/public.items.sku" {
		t.Fatalf("an index dropped by hand: %v, want it reported as declared but missing on items.sku", found)
	}

	psql(`CREATE INDEX ix_items_sku ON items (sku); CREATE INDEX ix_items_category ON items (category)`)
	if found := leadsIndexFindings(t); strings.Join(found, ",") != "schema:shop-db/public.items.category" {
		t.Fatalf("an index created by hand: %v, want it reported as live but undeclared on items.category", found)
	}
}

// TestTheDemoDatabase: inventory-service's own database (Phase 37 part 1,
// P8), set up as the quickstart sets it up — the demo's setup script, as
// the server's superuser, then the demo's own migrations as the database's
// owner — and read by capture: the seeded table's index facts are the ones
// its migrations declare (extractors/python's TestTheDemoMigrations...
// holds the declared side). Run twice: the setup is idempotent.
func TestTheDemoDatabase(t *testing.T) {
	if os.Getenv("CULPRIT_DOCKER_TESTS") != "1" {
		t.Skip("NOT RUN: set CULPRIT_DOCKER_TESTS=1 to run the demo database test (needs Docker, uv)")
	}
	dsn, _ := startPostgres(t)
	address := strings.TrimSuffix(strings.TrimPrefix(dsn, "postgresql://postgres:index-test@"), "/shop?sslmode=disable")
	host, port, _ := strings.Cut(address, ":")
	inventory := "postgresql://inventory:inventory-test@" + address + "/inventory?sslmode=disable"
	for run := 0; run < 2; run++ {
		setup := exec.Command("uv", "run", "--project", ".", "python", "-m", "inventory_service.setup_db")
		setup.Dir = filepath.Join(repoRoot, "demo-services")
		setup.Env = append(os.Environ(),
			"INVENTORY_ADMIN_HOST="+host, "INVENTORY_ADMIN_PORT="+port, "INVENTORY_ADMIN_USER=postgres",
			"INVENTORY_ADMIN_PASSWORD=index-test", "INVENTORY_ADMIN_DB=shop", "INVENTORY_DATABASE_URL="+inventory)
		if out, err := setup.CombinedOutput(); err != nil {
			t.Fatalf("the demo's database setup (run %d): %v\n%s", run+1, err, out)
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
	defer cancel()
	schema, err := capture.PostgresReader{}.Read(ctx, inventory)
	if err != nil {
		t.Fatalf("capture's read of the demo's database: %v", err)
	}
	var products *capture.TableShape
	for index := range schema.Tables {
		if schema.Tables[index].Namespace == "public" && schema.Tables[index].Table == "products" {
			products = &schema.Tables[index]
		}
	}
	if products == nil {
		t.Fatalf("no products table in the demo's database: %+v", schema.Tables)
	}
	var leading []string
	for column := range products.Leading {
		leading = append(leading, column)
	}
	sort.Strings(leading)
	if strings.Join(leading, ",") != "category,id,sku" {
		t.Fatalf("the columns leading an index on products are %v; the migrations declare id, sku and (0003) category", leading)
	}
	if strings.Join(schema.MigrationHeads, ",") != "0003_products_category_sku" {
		t.Fatalf("the demo's database is at %v, want its head 0003_products_category_sku", schema.MigrationHeads)
	}
}

// setUpDemoDatabase runs the demo's own setup, as the quickstart does, on a
// throwaway Postgres, and returns a reader's DSN for the inventory database:
// a login role with no grant at all, which is all reading the catalogue
// needs (the migration version, behind SELECT on alembic_version, is not).
func setUpDemoDatabase(t *testing.T) string {
	t.Helper()
	dsn, psql := startPostgres(t)
	address := strings.TrimSuffix(strings.TrimPrefix(dsn, "postgresql://postgres:index-test@"), "/shop?sslmode=disable")
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
	psql("CREATE ROLE schema_reader LOGIN PASSWORD 'reader-test'")
	return strings.Replace(inventory, "inventory:inventory-test@", "schema_reader:reader-test@", 1)
}

// TestTheDemoSchemaIsOnOneDatabase is Q34 on the demo: three readers of
// inventory-service's schema put it on one database, the one it connects to
// by its one sql edge (inventory-db) —
//   - the migrations, read by the Python extractor through the demo's own
//     extract: section (`culprit intent`, plugins on);
//   - the live database, read by capture (`culprit env capture
//     local-inventory`);
//   - the statement budget on products, as the demo declares it.
//
// Before Q34 the first was on inventory-service-db and joined neither.
func TestTheDemoSchemaIsOnOneDatabase(t *testing.T) {
	if os.Getenv("CULPRIT_DOCKER_TESTS") != "1" {
		t.Skip("NOT RUN: set CULPRIT_DOCKER_TESTS=1 to run the demo schema test (needs Docker, uv)")
	}
	manifestPath := filepath.Join(repoRoot, "demo-services", "culprit.yaml")
	t.Setenv("CULPRIT_INVENTORY_DSN", setUpDemoDatabase(t))
	category := model.MustBuildSubject(model.KindSchema, model.Parts{
		"database": "inventory-db", "namespace": "public", "table": "products", "column": "category"})

	leadsIndex := func(facts []model.Fact, plane model.Plane) map[string]any {
		found := map[string]any{}
		for _, fact := range facts {
			if fact.Plane == plane && fact.Predicate == model.PredicateLeadsIndex {
				found[fact.Subject] = fact.Value
			}
		}
		return found
	}

	stdout, err := run(t, "intent", "-f", manifestPath, "--format", "json")
	if err != nil {
		t.Fatalf("culprit intent on the demo: %v\n%s", err, stdout)
	}
	var intent model.CaptureBundle
	if err := json.Unmarshal([]byte(stdout), &intent); err != nil {
		t.Fatalf("culprit intent printed no bundle: %v", err)
	}
	declared := leadsIndex(intent.Facts, model.PlaneIntent)
	if declared[category] != true {
		t.Errorf("the migrations: no leads_index true on %s (0003 declares (category, sku)); found %v", category, declared)
	}

	envelope := filepath.Join(t.TempDir(), "live.json")
	if out, err := run(t, "env", "capture", "local-inventory", "-f", manifestPath, "-o", envelope); err != nil {
		t.Fatalf("culprit env capture local-inventory: %v\n%s", err, out)
	}
	live, err := capture.ReadEnvelope(envelope)
	if err != nil {
		t.Fatal(err)
	}
	configured := leadsIndex(live.Bundle.Facts, model.PlaneConfigured)
	if configured[category] != true {
		t.Errorf("the live database: no leads_index true on %s; found %v", category, configured)
	}

	manifest, err := extract.LoadManifest(manifestPath)
	if err != nil {
		t.Fatal(err)
	}
	budgeted := ""
	for _, budget := range manifest.Budgets {
		if model.StatementBudgetPredicates[budget.Predicate] {
			budgeted = budget.Subject
		}
	}
	_, parts, err := model.ParseSubject(budgeted)
	if err != nil || parts["database"] != "inventory-db" {
		t.Errorf("the statement budget is on %q, not on inventory-db", budgeted)
	}

	// The same subjects on both sides, not only the one checked above.
	for subject := range declared {
		if _, ok := configured[subject]; !ok {
			t.Errorf("%s is declared by the migrations and absent from the live capture", subject)
		}
	}
}
