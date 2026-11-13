package dbsession

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

// Statements and plans against a real Postgres 16 with pg_stat_statements
// preloaded (Phase 37 part 2). Gated on CULPRIT_DOCKER_TESTS=1, as the
// read-only session test is.
//
// The traffic runs between the window's two snapshots (the Wait hook), as
// another role than the reader's, in the reader's database and in another:
//   - a SELECT on products holding a secret-looking constant;
//   - a CREATE ROLE ... PASSWORD '...', which pg_stat_statements keeps as
//     written;
//   - a SELECT in another database.
// The window finds the first, normalised, with its plan; the others leave
// nothing in any reading.

const (
	secretConstant = "hunter2-constant-not-a-category"
	secretPassword = "sup3r-s3cret-role-password"
)

func postgresWithStatements(t *testing.T) (container, address string) {
	t.Helper()
	out, err := exec.Command("docker", "run", "-d", "--rm", "-e", "POSTGRES_PASSWORD=stats-test",
		"-p", "127.0.0.1::5432", "postgres:16-alpine",
		"postgres", "-c", "shared_preload_libraries=pg_stat_statements").CombinedOutput()
	if err != nil {
		t.Fatalf("docker run: %v\n%s", err, out)
	}
	container = strings.TrimSpace(string(out))
	t.Cleanup(func() { _ = exec.Command("docker", "rm", "-f", container).Run() })
	deadline := time.Now().Add(90 * time.Second)
	for exec.Command("docker", "exec", container, "psql", "-U", "postgres", "-c", "SELECT 1").Run() != nil {
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

func psql(t *testing.T, container, user, database, sql string) {
	t.Helper()
	cmd := exec.Command("docker", "exec", "-e", "PGPASSWORD=app-pass", container,
		"psql", "-v", "ON_ERROR_STOP=1", "-q", "-h", "127.0.0.1", "-U", user, "-d", database, "-c", sql)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("psql %s: %v\n%s", sql, err, out)
	}
}

func TestStatementsAndPlansAgainstARealPostgres(t *testing.T) {
	if os.Getenv("CULPRIT_DOCKER_TESTS") != "1" {
		t.Skip("NOT RUN: set CULPRIT_DOCKER_TESTS=1 to run the statistics test (needs Docker)")
	}
	container, address := postgresWithStatements(t)
	psql(t, container, "postgres", "postgres", "CREATE DATABASE shop")
	psql(t, container, "postgres", "postgres", "CREATE DATABASE other")
	psql(t, container, "postgres", "shop", `
		CREATE EXTENSION pg_stat_statements;
		CREATE TABLE products (id serial PRIMARY KEY, category text NOT NULL, name text NOT NULL);
		INSERT INTO products (category, name)
		  SELECT 'category-' || (i % 200), 'product ' || i FROM generate_series(1, 50000) i;
		ANALYZE products;
		CREATE ROLE app LOGIN PASSWORD 'app-pass';
		GRANT SELECT ON products TO app;
		GRANT CONNECT ON DATABASE other TO app;
		CREATE ROLE reader LOGIN PASSWORD 'reader-pass' IN ROLE pg_read_all_stats;
		GRANT SELECT ON products TO reader;`)
	dsn := "postgresql://reader:reader-pass@" + address + "/shop?sslmode=disable"

	traffic := func(ctx context.Context, _ time.Duration) error {
		for i := 0; i < 5; i++ {
			psql(t, container, "app", "shop",
				"SELECT id, name FROM products WHERE category = '"+secretConstant+"'")
		}
		psql(t, container, "postgres", "shop", "CREATE ROLE leaked LOGIN PASSWORD '"+secretPassword+"'")
		psql(t, container, "app", "other", "SELECT 4242 AS other_database_marker")
		return nil
	}
	reader := StatsReader{Span: time.Second, Wait: traffic}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	window, err := reader.Window(ctx, dsn, true)
	for attempt := 0; err != nil && attempt < 20; attempt++ {
		time.Sleep(time.Second)
		window, err = reader.Window(ctx, dsn, true)
	}
	if err != nil {
		t.Fatalf("Window: %v", err)
	}
	if window.Unavailable != "" || window.Reset {
		t.Fatalf("the window was not measured: unavailable %q, reset %v", window.Unavailable, window.Reset)
	}

	var products *StatementStats
	for index, statement := range window.Statements {
		everything := statement.Text + statement.PlanJSON
		for _, secret := range []string{secretConstant, secretPassword, "PASSWORD", "other_database_marker", "pg_stat_statements"} {
			if strings.Contains(everything, secret) {
				t.Errorf("queryid %d's reading holds %q", statement.QueryID, secret)
			}
		}
		if strings.Contains(statement.Text, "FROM products WHERE category = $1") {
			products = &window.Statements[index]
		}
	}
	if products == nil {
		t.Fatalf("the products statement was not in the window: %+v", window.Statements)
	}
	if products.Calls != 5 || products.TotalMicros <= 0 {
		t.Errorf("the products statement: %d calls, %d µs; want 5 calls and some time", products.Calls, products.TotalMicros)
	}
	if !strings.Contains(products.PlanJSON, `"Seq Scan"`) || !strings.Contains(products.PlanJSON, `"products"`) {
		t.Errorf("the generic plan is not a sequential scan of products: %s", products.PlanJSON)
	}
	if columns := window.TableColumns["public.products"]; len(columns) != 3 {
		t.Errorf("products' columns were read as %v", columns)
	}

	psql(t, container, "postgres", "shop", "CREATE INDEX products_category ON products (category)")
	plan, err := StatsReader{}.Plan(ctx, dsn, products.QueryID)
	if err != nil || plan.Unavailable != "" {
		t.Fatalf("Plan: %v %q", err, plan.Unavailable)
	}
	if !strings.Contains(plan.PlanJSON, "products_category") {
		t.Errorf("with an index on category the plan does not use it: %s", plan.PlanJSON)
	}
	if strings.Contains(plan.PlanJSON, secretConstant) {
		t.Error("the plan holds the constant")
	}
}

// readOnlyWitness wraps a real session and, before and after every message
// sendPlan sends, asks the server whether the transaction is read-only.
type readOnlyWitness struct {
	t    *testing.T
	conn *pgx.Conn
	sent []string
}

func (w *readOnlyWitness) check(when string) {
	w.t.Helper()
	var value string
	if err := w.conn.QueryRow(context.Background(), "SHOW transaction_read_only").Scan(&value); err != nil {
		w.t.Fatalf("SHOW transaction_read_only %s: %v", when, err)
	}
	if value != "on" {
		w.t.Errorf("the session was not read-only %s: transaction_read_only = %q", when, value)
	}
}

func (w *readOnlyWitness) Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error) {
	w.check("before " + sql)
	w.sent = append(w.sent, sql)
	rows, err := w.conn.Query(ctx, sql, args...)
	return rows, err
}

func (w *readOnlyWitness) Prepare(ctx context.Context, name, sql string) (*pgconn.StatementDescription, error) {
	w.check("before PARSE")
	w.sent = append(w.sent, "PARSE "+name+": "+sql)
	description, err := w.conn.Prepare(ctx, name, sql)
	w.check("after PARSE")
	return description, err
}

func (w *readOnlyWitness) Deallocate(ctx context.Context, name string) error {
	w.sent = append(w.sent, "DEALLOCATE "+name)
	err := w.conn.Deallocate(ctx, name)
	w.check("after DEALLOCATE")
	return err
}

// TestTheGenericPlanAgainstARealPostgres holds the three properties of the
// generic plan the architecture session kept on 2026-11-13: a prepared
// statement explained under plan_cache_mode = force_generic_plan, on the
// extended protocol, with nothing executed.
//  1. The session is read-only before, between and after every message.
//  2. ANALYZE is never sent, and the statement is not executed: its calls in
//     pg_stat_statements do not move.
//  3. A second statement appended to the text is refused by the server's
//     Parse itself, with sendPlan's own guard bypassed.
func TestTheGenericPlanAgainstARealPostgres(t *testing.T) {
	if os.Getenv("CULPRIT_DOCKER_TESTS") != "1" {
		t.Skip("NOT RUN: set CULPRIT_DOCKER_TESTS=1 to run the generic plan test (needs Docker)")
	}
	container, address := postgresWithStatements(t)
	psql(t, container, "postgres", "postgres", "CREATE DATABASE shop")
	psql(t, container, "postgres", "shop", `
		CREATE EXTENSION pg_stat_statements;
		CREATE TABLE products (id serial PRIMARY KEY, category text NOT NULL, name text NOT NULL);
		INSERT INTO products (category, name)
		  SELECT 'category-' || (i % 200), 'product ' || i FROM generate_series(1, 5000) i;
		ANALYZE products;
		CREATE ROLE reader LOGIN PASSWORD 'reader-pass' IN ROLE pg_read_all_stats;
		GRANT SELECT ON products TO reader;`)
	dsn := "postgresql://reader:reader-pass@" + address + "/shop?sslmode=disable"
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	var conn *pgx.Conn
	var err error
	for attempt := 0; attempt < 20; attempt++ {
		if conn, err = openSession(ctx, dsn); err == nil {
			break
		}
		time.Sleep(time.Second)
	}
	if err != nil {
		t.Fatalf("openSession: %v", err)
	}
	defer conn.Close(context.Background())

	const text = "SELECT id, name FROM products WHERE category = $1"
	calls := func() int64 {
		var n int64
		if err := conn.QueryRow(ctx,
			"SELECT coalesce(sum(calls), 0)::bigint FROM pg_stat_statements WHERE query = $1", text).Scan(&n); err != nil {
			t.Fatalf("reading calls: %v", err)
		}
		return n
	}
	before := calls()

	witness := &readOnlyWitness{t: t, conn: conn}
	planned, err := planFromRow(text)
	if err != nil {
		t.Fatal(err)
	}
	plan, err := sendPlan(ctx, witness, planned)
	if err != nil {
		t.Fatalf("sendPlan: %v", err)
	}
	if !strings.Contains(plan, `"products"`) || !strings.Contains(plan, "$1") {
		t.Errorf("not a generic plan of products filtering on $1: %s", plan)
	}
	for _, sent := range witness.sent {
		if strings.Contains(strings.ToUpper(sent), "ANALYZE") {
			t.Errorf("ANALYZE was sent: %q", sent)
		}
	}
	if after := calls(); after != before {
		t.Errorf("the planned statement was executed: calls %d before, %d after", before, after)
	}

	// The guard in sendPlan refuses ';' before anything is sent. Bypass it
	// and the server's Parse refuses the second statement on its own.
	_, err = conn.Prepare(ctx, "culprit_plan_appended",
		"SELECT id FROM products WHERE category = $1; DELETE FROM products")
	var pgErr *pgconn.PgError
	if !errors.As(err, &pgErr) || pgErr.Code != "42601" {
		t.Fatalf("an appended statement was not refused at Parse: %v", err)
	}
	var rows int64
	if err := conn.QueryRow(ctx, "SELECT count(*) FROM products").Scan(&rows); err != nil || rows != 5000 {
		t.Fatalf("products holds %d rows (%v), want 5000", rows, err)
	}
}
