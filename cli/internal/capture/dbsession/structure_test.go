package dbsession

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/boundarytest"
)

// The session's structure (Q27, ruled 2026-11-12): one non-test file, an
// exported surface that names nothing a caller could send a statement
// through, and a template set that is a closed switch.

func TestThisPackageHasOneFile(t *testing.T) {
	files, err := boundarytest.NonTestFiles(".")
	if err != nil || len(files) != 1 || files[0] != "session.go" {
		t.Fatalf("dbsession's non-test files are %v (%v); it must be session.go alone", files, err)
	}
}

// TestASecondFileIsFound is that rule's red state.
func TestASecondFileIsFound(t *testing.T) {
	root := t.TempDir()
	for _, name := range []string{"session.go", "zz_second.go"} {
		if err := os.WriteFile(filepath.Join(root, name), []byte("package dbsession\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if files, _ := boundarytest.NonTestFiles(root); len(files) == 1 {
		t.Fatal("a second non-test file was not found")
	}
}

// forbidden are the packages whose types the exported surface may not name.
var forbidden = []string{"github.com/jackc", "net"}

func TestTheExportedSurfaceNamesNoDriverType(t *testing.T) {
	found, err := boundarytest.ExportedTypesFrom(".", forbidden)
	if err != nil {
		t.Fatal(err)
	}
	if len(found) > 0 {
		t.Fatalf("the exported surface names a driver or network type a caller could send through: %v", found)
	}
}

// TestAnExportedDriverTypeIsFound is that rule's red state.
func TestAnExportedDriverTypeIsFound(t *testing.T) {
	source, err := os.ReadFile("session.go")
	if err != nil {
		t.Fatal(err)
	}
	for name, code := range map[string]string{
		"the connection":     "func Open(ctx context.Context, dsn string) (*pgx.Conn, error) { return openSession(ctx, dsn) }",
		"a method":           "func (r PostgresReader) Conn() *pgx.Conn { return nil }",
		"an exported field":  "type Exposed struct{ Conn *pgx.Conn }",
		"the driver's error": "type Failure = pgconn.PgError",
	} {
		t.Run(name, func(t *testing.T) {
			root := t.TempDir()
			if err := os.WriteFile(filepath.Join(root, "session.go"), []byte(string(source)+"\n"+code+"\n"), 0o644); err != nil {
				t.Fatal(err)
			}
			found, err := boundarytest.ExportedTypesFrom(root, forbidden)
			if err != nil {
				t.Fatal(err)
			}
			if len(found) == 0 {
				t.Fatalf("an exported driver type (%s) was not found", name)
			}
		})
	}
}

// templateSet reads session.go: the statement constants declared, the
// cases isTemplate's switch accepts, and whether any map keyed by
// statement exists (a set another file could once extend at run time).
func templateSet(t *testing.T, path string) (constants, cases []string, maps int) {
	t.Helper()
	file, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
	if err != nil {
		t.Fatal(err)
	}
	ast.Inspect(file, func(node ast.Node) bool {
		switch typed := node.(type) {
		case *ast.ValueSpec:
			if ident, ok := typed.Type.(*ast.Ident); ok && ident.Name == "statement" {
				for _, name := range typed.Names {
					constants = append(constants, name.Name)
				}
			}
		case *ast.MapType:
			if ident, ok := typed.Key.(*ast.Ident); ok && ident.Name == "statement" {
				maps++
			}
		case *ast.FuncDecl:
			if typed.Name.Name != "isTemplate" {
				return true
			}
			ast.Inspect(typed.Body, func(inner ast.Node) bool {
				if clause, ok := inner.(*ast.CaseClause); ok {
					for _, expression := range clause.List {
						if ident, ok := expression.(*ast.Ident); ok {
							cases = append(cases, ident.Name)
						}
					}
				}
				return true
			})
			return false
		}
		return true
	})
	sort.Strings(constants)
	sort.Strings(cases)
	return constants, cases, maps
}

// TestTheTemplateSetIsTheConstants (the re-audit of 25db425): isTemplate
// accepts exactly the statement constants, and no map keyed by statement
// exists — the set cannot be widened at run time, nor a constant added
// without the switch saying so.
func TestTheTemplateSetIsTheConstants(t *testing.T) {
	constants, cases, maps := templateSet(t, "session.go")
	if maps != 0 || len(constants) == 0 || strings.Join(constants, ",") != strings.Join(cases, ",") {
		t.Fatalf("statement constants %v, isTemplate's cases %v, maps keyed by statement %d", constants, cases, maps)
	}
}

// TestATemplateSetThatDriftsIsFound is that rule's red state.
func TestATemplateSetThatDriftsIsFound(t *testing.T) {
	source, err := os.ReadFile("session.go")
	if err != nil {
		t.Fatal(err)
	}
	for name, code := range map[string]string{
		"a constant the switch does not list": "const extraStatement statement = `SELECT 1`",
		"a map of statements":                 "var templates = map[statement]bool{}",
	} {
		path := filepath.Join(t.TempDir(), "session.go")
		if err := os.WriteFile(path, []byte(string(source)+"\n"+code+"\n"), 0o644); err != nil {
			t.Fatal(err)
		}
		constants, cases, maps := templateSet(t, path)
		if maps == 0 && strings.Join(constants, ",") == strings.Join(cases, ",") {
			t.Errorf("%s was not found", name)
		}
	}
}
