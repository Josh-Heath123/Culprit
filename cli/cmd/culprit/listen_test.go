package main

import (
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"path/filepath"
	"strings"
	"testing"
)

// TestNothingInTheBinaryListens (Phase 33 part 2): the agent connects out,
// to its control plane, and nothing in a user's network ever has to accept
// a connection from Culprit — so no code that ships in the binary may open
// a listener. Every non-test Go file under cli/ is parsed, and any call to
// a function named Listen... (net.Listen, net.ListenTCP, http.ListenAndServe,
// tls.Listen, net.ListenPacket, ...) or Serve on an http.Server fails the
// test, wherever it is.
//
// Tests are exempt: httptest servers stand in for a control plane there,
// and they are not in the binary.
func TestNothingInTheBinaryListens(t *testing.T) {
	root := filepath.Join("..", "..")
	files := 0
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() {
			switch entry.Name() {
			case "testdata", "bin", "dist", "node_modules", ".git":
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		files++
		parsed, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
		if err != nil {
			return err
		}
		ast.Inspect(parsed, func(node ast.Node) bool {
			call, ok := node.(*ast.CallExpr)
			if !ok {
				return true
			}
			var name string
			switch function := call.Fun.(type) {
			case *ast.SelectorExpr:
				name = function.Sel.Name
			case *ast.Ident:
				name = function.Name
			}
			if strings.HasPrefix(name, "Listen") || name == "Serve" || name == "ServeTLS" {
				t.Errorf("%s calls %s: nothing in the culprit binary may accept a connection", path, name)
			}
			return true
		})
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if files < 50 {
		t.Fatalf("parsed %d files; the walk is not covering cli/", files)
	}
}
