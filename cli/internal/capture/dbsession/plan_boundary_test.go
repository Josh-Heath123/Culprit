package dbsession

import (
	"context"
	"errors"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Part 2's boundary (PERFORMANCE_PLAN.md, Phase 37 part 2): the one text
// that is not a template is a SELECT or WITH read back from
// pg_stat_statements, in a plannedStatement only planFromRow makes, sent by
// sendPlan as a prepared statement explained under plan_cache_mode =
// force_generic_plan, through the extended protocol (ruled 2026-11-13). Everything else is refused before it leaves, and counted.

// TestOnlyAPlannableTextReachesThePlanner: an arbitrary statement, EXPLAIN
// ANALYZE, a reset, a second statement appended to a planned one and a
// leading comment are refused before the driver; a SELECT reaches it once,
// wrapped in the generic plan and bound to NULLs.
func TestOnlyAPlannableTextReachesThePlanner(t *testing.T) {
	session := &countingSession{}
	for _, text := range []string{
		"DELETE FROM orders WHERE id = $1",
		"EXPLAIN ANALYZE SELECT 1",
		"SELECT 1; DELETE FROM orders",
		"SELECT * FROM products WHERE category = $1; DROP TABLE products",
		"/* hint */ SELECT 1",
		" SELECT 1",
		"CREATE ROLE x PASSWORD $1",
		"",
	} {
		if planned, err := planFromRow(text); err == nil {
			_, _ = sendPlan(context.Background(), session, planned)
			t.Errorf("%q became a planned statement", text)
		}
		// And sendPlan refuses it even when a plannedStatement is made
		// around planFromRow, inside this package.
		if _, err := sendPlan(context.Background(), session, plannedStatement{text: text}); !errors.Is(err, ErrNotPlannable) {
			t.Errorf("sendPlan did not refuse %q: %v", text, err)
		}
	}
	if len(session.sent) != 0 {
		t.Fatalf("%d refused texts reached the driver: %q", len(session.sent), session.sent)
	}
	planned, err := planFromRow("SELECT id FROM products WHERE category = $1 LIMIT $2")
	if err != nil {
		t.Fatal(err)
	}
	_, _ = sendPlan(context.Background(), session, planned)
	want := []string{
		"PARSE culprit_plan: SELECT id FROM products WHERE category = $1 LIMIT $2",
		"EXPLAIN (FORMAT JSON) EXECUTE culprit_plan(NULL, NULL)",
		"DEALLOCATE culprit_plan",
	}
	if strings.Join(session.sent, "\n") != strings.Join(want, "\n") {
		t.Fatalf("the planner was sent %q, want %q", session.sent, want)
	}
	for _, args := range session.args {
		if len(args) != 0 {
			t.Fatalf("a plan message carried arguments %v: the text is parsed, never bound", args)
		}
	}
}

// TestTheStatisticsTemplatesReadOnlyThisDatabase: Q29 (3) and (2) — every
// statistics read is filtered to the connected database and away from
// Culprit's own role, and text leaves the server only for the six
// statements Postgres normalises.
func TestTheStatisticsTemplatesReadOnlyThisDatabase(t *testing.T) {
	for name, template := range map[string]statement{
		"snapshot": statsSnapshotStatement, "plan row": planRowStatement,
	} {
		for _, want := range []string{
			"s.dbid = (SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database())",
			"s.userid <> (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = current_user)",
		} {
			if !strings.Contains(string(template), want) {
				t.Errorf("the %s template does not filter %q", name, want)
			}
		}
	}
	if !strings.Contains(string(statsSnapshotStatement), `'^(select|with|insert|update|delete|merge)\M'`) {
		t.Error("the snapshot keeps text other than the six statements Postgres normalises")
	}
	if !strings.Contains(string(planRowStatement), `'^(select|with)\M'`) {
		t.Error("the plan row reads text other than a SELECT or WITH")
	}
}

// plannedOutsideConstructor lists composite literals of plannedStatement
// outside planFromRow in a Go file.
func plannedOutsideConstructor(t *testing.T, path string) []string {
	t.Helper()
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, path, nil, 0)
	if err != nil {
		t.Fatal(err)
	}
	var found []string
	for _, declaration := range file.Decls {
		if function, ok := declaration.(*ast.FuncDecl); ok && function.Name.Name == "planFromRow" {
			continue
		}
		ast.Inspect(declaration, func(node ast.Node) bool {
			if literal, ok := node.(*ast.CompositeLit); ok {
				if ident, ok := literal.Type.(*ast.Ident); ok && ident.Name == "plannedStatement" {
					found = append(found, fset.Position(node.Pos()).String())
				}
			}
			return true
		})
	}
	return found
}

func TestOnlyPlanFromRowMakesAPlannedStatement(t *testing.T) {
	if found := plannedOutsideConstructor(t, "session.go"); len(found) > 0 {
		t.Fatalf("a plannedStatement is made outside planFromRow: %v", found)
	}
}

// TestAPlannedStatementMadeElsewhereIsFound is that rule's red state.
func TestAPlannedStatementMadeElsewhereIsFound(t *testing.T) {
	source, err := os.ReadFile("session.go")
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "session.go")
	code := "\nfunc smuggle() plannedStatement { return plannedStatement{text: \"SELECT 1\"} }\n"
	if err := os.WriteFile(path, append(source, []byte(code)...), 0o644); err != nil {
		t.Fatal(err)
	}
	if len(plannedOutsideConstructor(t, path)) == 0 {
		t.Fatal("a plannedStatement made outside planFromRow was not found")
	}
}
