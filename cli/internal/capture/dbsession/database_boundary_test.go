package dbsession

import (
	"context"
	"errors"
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"
)

// The database boundary (Phase 37 part 1): one file opens connections, it
// sends only templates, and every session is read-only and bounded at the
// server. These tests hold the first two without a database; the third is
// TestASessionIsReadOnlyAtTheServer, against a real Postgres.

// countingSession is a querier that counts what reaches it.
type countingSession struct{ sent []string }

func (s *countingSession) Query(_ context.Context, sql string, _ ...any) (pgx.Rows, error) {
	s.sent = append(s.sent, sql)
	return nil, errors.New("counted, not run")
}

// TestOnlyTemplatesReachTheDriver: an arbitrary statement and an EXPLAIN
// ANALYZE are refused before they leave; each template reaches the driver,
// once.
func TestOnlyTemplatesReachTheDriver(t *testing.T) {
	session := &countingSession{}
	for _, refused := range []statement{
		"SELECT * FROM users",
		"EXPLAIN ANALYZE SELECT 1",
		"EXPLAIN (ANALYZE) SELECT 1",
		"DELETE FROM orders",
		"SET default_transaction_read_only = off",
		"SELECT pg_stat_statements_reset()",
		columnsStatement + "; DROP TABLE users",
		" " + alembicExistsStatement,
		"",
	} {
		if _, err := send(context.Background(), session, refused); !errors.Is(err, ErrNotATemplate) {
			t.Errorf("%q was not refused: %v", refused, err)
		}
	}
	if len(session.sent) != 0 {
		t.Fatalf("%d refused statements reached the driver: %q", len(session.sent), session.sent)
	}
	all := []statement{columnsStatement, alembicExistsStatement, alembicVersionStatement, leadingColumnsStatement}
	for _, template := range all {
		_, _ = send(context.Background(), session, template)
	}
	if len(session.sent) != len(all) {
		t.Fatalf("%d of %d templates reached the driver", len(session.sent), len(all))
	}
}

// pgxImporters lists, as module-relative paths, every non-test Go file
// under root that imports pgx or a package under it.
func pgxImporters(t *testing.T, root string) []string {
	t.Helper()
	var found []string
	fset := token.NewFileSet()
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() && strings.HasPrefix(entry.Name(), ".") && path != root {
			return filepath.SkipDir
		}
		if entry.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		file, err := parser.ParseFile(fset, path, nil, parser.ImportsOnly)
		if err != nil {
			return err
		}
		for _, spec := range file.Imports {
			imported, _ := strconv.Unquote(spec.Path.Value)
			if strings.HasPrefix(imported, "github.com/jackc/pgx") || strings.HasPrefix(imported, "github.com/jackc/pgconn") {
				relative, _ := filepath.Rel(root, path)
				found = append(found, filepath.ToSlash(relative))
				break
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	sort.Strings(found)
	return found
}

// TestOnlyThisFileImportsPgx: across the whole module, database.go is the
// one non-test file that can open a database connection.
func TestOnlyThisFileImportsPgx(t *testing.T) {
	root, err := filepath.Abs(filepath.Join("..", "..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	found := pgxImporters(t, root)
	if len(found) != 1 || found[0] != "internal/capture/dbsession/session.go" {
		t.Fatalf("pgx is imported by %v; only internal/capture/dbsession/session.go may", found)
	}
}

// TestASecondPgxImporterIsFound is the allowlist's red state.
func TestASecondPgxImporterIsFound(t *testing.T) {
	root := t.TempDir()
	for path, source := range map[string]string{
		"internal/capture/database.go": "package capture\n\nimport \"github.com/jackc/pgx/v5\"\n\nvar _ pgx.Rows\n",
		"internal/probe/smuggled.go":   "package probe\n\nimport \"github.com/jackc/pgx/v5/pgconn\"\n\nvar _ pgconn.PgError\n",
	} {
		target := filepath.Join(root, filepath.FromSlash(path))
		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(target, []byte(source), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	found := pgxImporters(t, root)
	if len(found) != 2 || found[1] != "internal/probe/smuggled.go" {
		t.Fatalf("a second pgx importer was not found: %v", found)
	}
}

// driverCallsOutsideSend lists, in a Go file, every call of a session's
// sending methods anywhere but inside send. database.go is the one file
// that holds a session at all, so this is a property of that file, not a
// denylist over a package.
func driverCallsOutsideSend(t *testing.T, path string) []string {
	t.Helper()
	sending := map[string]bool{
		"Query": true, "QueryRow": true, "Exec": true, "SendBatch": true, "CopyFrom": true,
		"Prepare": true, "Begin": true, "BeginTx": true, "PgConn": true, "QueryFunc": true,
	}
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, path, nil, 0)
	if err != nil {
		t.Fatal(err)
	}
	var found []string
	for _, declaration := range file.Decls {
		if function, ok := declaration.(*ast.FuncDecl); ok && function.Recv == nil && function.Name.Name == "send" {
			continue
		}
		ast.Inspect(declaration, func(node ast.Node) bool {
			if selector, ok := node.(*ast.SelectorExpr); ok && sending[selector.Sel.Name] {
				found = append(found, fset.Position(node.Pos()).String()+" ."+selector.Sel.Name)
			}
			return true
		})
	}
	return found
}

func TestOnlySendTalksToTheDriver(t *testing.T) {
	if found := driverCallsOutsideSend(t, "session.go"); len(found) > 0 {
		t.Fatalf("a statement reaches the driver other than through send: %v", found)
	}
}

// TestAStatementSentAroundSendIsFound is that rule's red state.
func TestAStatementSentAroundSendIsFound(t *testing.T) {
	source, err := os.ReadFile("session.go")
	if err != nil {
		t.Fatal(err)
	}
	for name, code := range map[string]string{
		"a direct query": "func smuggle(ctx context.Context, conn *pgx.Conn) { _, _ = conn.Query(ctx, \"DELETE FROM t\") }",
		"exec":           "func smuggle(ctx context.Context, conn *pgx.Conn) { _, _ = conn.Exec(ctx, \"DROP TABLE t\") }",
		"a method value": "func smuggle(conn *pgx.Conn) { run := conn.Exec; _ = run }",
		"the raw conn":   "func smuggle(conn *pgx.Conn) { _ = conn.PgConn() }",
	} {
		t.Run(name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "session.go")
			if err := os.WriteFile(path, append(append([]byte{}, source...), []byte("\n"+code+"\n")...), 0o644); err != nil {
				t.Fatal(err)
			}
			if found := driverCallsOutsideSend(t, path); len(found) == 0 {
				t.Fatalf("a statement sent around send (%s) was not found", name)
			}
		})
	}
}
