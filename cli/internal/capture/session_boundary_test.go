package capture

import (
	"go/parser"
	"go/token"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/boundarytest"
)

// The database session lives in internal/capture/dbsession (Q27, ruled
// 2026-11-12). This package imports no database driver, so the only
// statements it can send are what dbsession's exported surface sends — and
// what the Phase 37 part 1 audit did from a file here, taking the session's
// connection and sending it EXPLAIN ANALYZE, is now a type error.

func TestCaptureImportsNoDriver(t *testing.T) {
	names, err := boundarytest.NonTestFiles(".")
	if err != nil {
		t.Fatal(err)
	}
	fset := token.NewFileSet()
	for _, name := range names {
		file, err := parser.ParseFile(fset, name, nil, parser.ImportsOnly)
		if err != nil {
			t.Fatal(err)
		}
		for _, spec := range file.Imports {
			path, _ := strconv.Unquote(spec.Path.Value)
			if strings.HasPrefix(path, "github.com/jackc/") {
				t.Errorf("%s imports %s; every statement goes through dbsession (Q27)", name, path)
			}
		}
	}
}

const modulePath = "github.com/josh-heath123/culprit/cli"

// TestTheAuditsAttackNoLongerTypeChecks: the audit's file, planted here,
// does not compile; a file using only the exported reader does.
func TestTheAuditsAttackNoLongerTypeChecks(t *testing.T) {
	root, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	attack := `package capture

import "context"

func smuggle(ctx context.Context, dsn string) {
	conn, _ := openSession(ctx, dsn)
	_, _ = conn.Exec(ctx, "EXPLAIN ANALYZE DELETE FROM orders")
	_, _ = send(ctx, conn, statement("DELETE FROM accounts"))
}
`
	errs, err := boundarytest.PlantedErrors(root, modulePath, "internal/capture", attack)
	if err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(errs, "; ")
	for _, want := range []string{"openSession", "send"} {
		if !strings.Contains(joined, want) {
			t.Errorf("planting the audit's file: no type error about %s (errors: %v)", want, errs)
		}
	}
	allowed := `package capture

import "context"

func fine(ctx context.Context, dsn string) {
	_, _ = PostgresReader{}.Read(ctx, dsn)
}
`
	if errs, err := boundarytest.PlantedErrors(root, modulePath, "internal/capture", allowed); err != nil || len(errs) > 0 {
		t.Fatalf("a file using only the exported reader did not type-check: %v %v", errs, err)
	}
}
