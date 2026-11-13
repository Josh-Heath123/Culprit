package dbsession

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgconn"
)

// The boundary's third layer, against a real Postgres (Phase 37 part 1):
// every session openSession opens is read-only and bounded at the server.
// A write sent through a deliberately weakened path — straight to the
// connection, around send and its templates — is refused by Postgres
// itself, as read-only, and the statement timeout is set.
//
// Gated on CULPRIT_DOCKER_TESTS=1, as the Compose end-to-end tests are;
// CI's `cli` job sets it.

// postgresForTest runs a throwaway Postgres and returns a superuser DSN.
func postgresForTest(t *testing.T) string {
	t.Helper()
	out, err := exec.Command("docker", "run", "-d", "--rm", "-e", "POSTGRES_PASSWORD=boundary-test",
		"-p", "127.0.0.1::5432", "postgres:16-alpine").CombinedOutput()
	if err != nil {
		t.Fatalf("docker run: %v\n%s", err, out)
	}
	container := strings.TrimSpace(string(out))
	t.Cleanup(func() { _ = exec.Command("docker", "rm", "-f", container).Run() })
	// Ready over TCP, not the socket: see postgresImageWithStatements.
	deadline := time.Now().Add(90 * time.Second)
	for exec.Command("docker", "exec", container, "pg_isready", "-h", "127.0.0.1", "-U", "postgres").Run() != nil {
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
	return "postgresql://postgres:boundary-test@" + address + "/postgres?sslmode=disable"
}

func TestASessionIsReadOnlyAtTheServer(t *testing.T) {
	if os.Getenv("CULPRIT_DOCKER_TESTS") != "1" {
		t.Skip("NOT RUN: set CULPRIT_DOCKER_TESTS=1 to run the read-only session test (needs Docker)")
	}
	dsn := postgresForTest(t)
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
	defer cancel()
	var conn interface {
		Exec(context.Context, string, ...any) (pgconn.CommandTag, error)
	}
	session, err := openSession(ctx, dsn)
	for attempt := 0; err != nil && attempt < 30; attempt++ {
		time.Sleep(time.Second)
		session, err = openSession(ctx, dsn)
	}
	if err != nil {
		t.Fatalf("openSession: %v", err)
	}
	defer session.Close(context.Background())
	conn = session

	// The weakened path: straight to the connection, no template.
	for _, write := range []string{
		"CREATE TABLE written_by_culprit (a int)",
		"CREATE ROLE written_by_culprit",
	} {
		_, err := conn.Exec(ctx, write)
		var pgErr *pgconn.PgError
		if !errors.As(err, &pgErr) || pgErr.Code != "25006" {
			t.Errorf("%q through the weakened path: %v, want Postgres to refuse it as read-only (25006)", write, err)
		}
	}

	settings := map[string]string{}
	for _, name := range []string{"default_transaction_read_only", "statement_timeout", "application_name"} {
		var value string
		if err := session.QueryRow(ctx, "SHOW "+name).Scan(&value); err != nil {
			t.Fatalf("SHOW %s: %v", name, err)
		}
		settings[name] = value
	}
	if settings["default_transaction_read_only"] != "on" || settings["statement_timeout"] != "10s" ||
		settings["application_name"] != "culprit-capture" {
		t.Fatalf("the session's settings are %v, want read-only, a 10s statement timeout and culprit-capture", settings)
	}

	// And the templates themselves run, read-only, on a real catalogue.
	schema, err := PostgresReader{}.Read(ctx, dsn)
	if err != nil {
		t.Fatalf("Read on a real database: %v", err)
	}
	if schema.HasAlembic {
		t.Fatalf("an empty database reported an alembic_version table")
	}
}
