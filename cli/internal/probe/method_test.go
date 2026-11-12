package probe

import (
	"context"
	"go/ast"
	"go/parser"
	"go/token"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"testing"
)

// Every request is built in one place (Phase 36 part 2).
//
// The HTTP client's method allowlist — GET or OPTIONS, never a body — holds
// only if no request can be built around it. Part 1's TimeGet built its own
// request with http.NewRequestWithContext, outside do()'s check: a constant
// GET, but nothing but the reader's memory kept it one. newProbeRequest is
// now the one constructor, and this test makes that a property of the
// source: in this package's non-test files, nothing else may
//
//   - call net/http's request constructors or its package-level senders
//     (NewRequest, NewRequestWithContext, ReadRequest, Get, Head, Post,
//     PostForm);
//   - write a literal http.Request, or new(http.Request);
//   - assign a request's Method;
//   - call a Head, Post or PostForm method — http.Client's build their own
//     request with a method other than GET.
//
// Clone and WithContext copy a request whose method was already checked;
// changing it afterwards is the Method assignment above.

// constructorsOfNetHTTP are net/http's functions that build or send a
// request of their own.
var constructorsOfNetHTTP = map[string]bool{
	"NewRequest": true, "NewRequestWithContext": true, "ReadRequest": true,
	"Get": true, "Head": true, "Post": true, "PostForm": true,
}

// sendingMethods are the http.Client methods that send a method other than
// GET. No method of this package has these names.
var sendingMethods = map[string]bool{"Head": true, "Post": true, "PostForm": true}

// requestsBuiltElsewhere lists, as file:line, every place in directory's
// non-test Go files that builds or sends a request other than inside
// newProbeRequest.
func requestsBuiltElsewhere(t *testing.T, directory string) []string {
	t.Helper()
	entries, err := os.ReadDir(directory)
	if err != nil {
		t.Fatal(err)
	}
	fset := token.NewFileSet()
	var found []string
	for _, entry := range entries {
		name := entry.Name()
		if entry.IsDir() || !strings.HasSuffix(name, ".go") || strings.HasSuffix(name, "_test.go") {
			continue
		}
		file, err := parser.ParseFile(fset, filepath.Join(directory, name), nil, 0)
		if err != nil {
			t.Fatal(err)
		}
		// The names net/http is imported under in this file.
		httpNames := map[string]bool{}
		for _, spec := range file.Imports {
			path, _ := strconv.Unquote(spec.Path.Value)
			if path != "net/http" {
				continue
			}
			if spec.Name != nil {
				httpNames[spec.Name.Name] = true
			} else {
				httpNames["http"] = true
			}
		}
		isHTTP := func(expr ast.Expr, names map[string]bool) (string, bool) {
			selector, ok := expr.(*ast.SelectorExpr)
			if !ok {
				return "", false
			}
			ident, ok := selector.X.(*ast.Ident)
			if !ok || !httpNames[ident.Name] {
				return "", false
			}
			return selector.Sel.Name, names == nil || names[selector.Sel.Name]
		}
		for _, declaration := range file.Decls {
			if function, ok := declaration.(*ast.FuncDecl); ok && function.Recv == nil &&
				function.Name.Name == "newProbeRequest" {
				continue // the one place
			}
			ast.Inspect(declaration, func(node ast.Node) bool {
				where := func(what string) {
					position := fset.Position(node.Pos())
					found = append(found, filepath.Base(position.Filename)+":"+strconv.Itoa(position.Line)+" "+what)
				}
				switch typed := node.(type) {
				case *ast.CallExpr:
					if name, ok := isHTTP(typed.Fun, constructorsOfNetHTTP); ok {
						where("http." + name)
					} else if selector, ok := typed.Fun.(*ast.SelectorExpr); ok && sendingMethods[selector.Sel.Name] {
						where("." + selector.Sel.Name + "()")
					}
					if ident, ok := typed.Fun.(*ast.Ident); ok && ident.Name == "new" && len(typed.Args) == 1 {
						if name, ok := isHTTP(typed.Args[0], nil); ok && name == "Request" {
							where("new(http.Request)")
						}
					}
				case *ast.CompositeLit:
					if name, ok := isHTTP(typed.Type, nil); ok && name == "Request" {
						where("http.Request{}")
					}
				case *ast.AssignStmt:
					for _, left := range typed.Lhs {
						if selector, ok := left.(*ast.SelectorExpr); ok && selector.Sel.Name == "Method" {
							where(".Method =")
						}
					}
				}
				return true
			})
		}
	}
	sort.Strings(found)
	return found
}

func TestEveryRequestIsBuiltInOnePlace(t *testing.T) {
	if found := requestsBuiltElsewhere(t, "."); len(found) > 0 {
		t.Fatalf("a request is built outside newProbeRequest, around its method check: %v", found)
	}
}

// TestARequestBuiltAroundTheCheckIsFound is the red state: a copy of this
// package's sources, with one more file building a request each way the
// scan names, is caught once per way.
func TestARequestBuiltAroundTheCheckIsFound(t *testing.T) {
	ways := map[string]string{
		"constructor": `func smuggle(ctx context.Context) (*http.Request, error) {
	return http.NewRequestWithContext(ctx, http.MethodPost, "http://x", nil)
}`,
		"aliased": `func smuggle() (*web.Request, error) { return web.NewRequest("DELETE", "http://x", nil) }`,
		"literal": `func smuggle() *http.Request { return &http.Request{Method: "POST"} }`,
		"new":     `func smuggle() *http.Request { return new(http.Request) }`,
		"mutated": `func smuggle(ctx context.Context) (*http.Request, error) {
	request, err := newProbeRequest(ctx, http.MethodGet, "http://x")
	if err == nil {
		request.Method = http.MethodPut
	}
	return request, err
}`,
		"client":  `func smuggle(client *http.Client) { _, _ = client.Post("http://x", "text/plain", nil) }`,
		"package": `func smuggle() { _, _ = http.Post("http://x", "text/plain", nil) }`,
	}
	for name, code := range ways {
		t.Run(name, func(t *testing.T) {
			root := t.TempDir()
			entries, err := os.ReadDir(".")
			if err != nil {
				t.Fatal(err)
			}
			for _, entry := range entries {
				if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".go") || strings.HasSuffix(entry.Name(), "_test.go") {
					continue
				}
				data, err := os.ReadFile(entry.Name())
				if err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(root, entry.Name()), data, 0o644); err != nil {
					t.Fatal(err)
				}
			}
			if found := requestsBuiltElsewhere(t, root); len(found) > 0 {
				t.Fatalf("the copy already builds requests elsewhere: %v", found)
			}
			imports := "import (\n\t\"context\"\n\t\"net/http\"\n)\n\nvar _ context.Context\n\n"
			if name == "aliased" {
				imports = "import web \"net/http\"\n\n"
			}
			source := "package probe\n\n" + imports + code + "\n"
			if err := os.WriteFile(filepath.Join(root, "smuggled.go"), []byte(source), 0o644); err != nil {
				t.Fatal(err)
			}
			found := requestsBuiltElsewhere(t, root)
			if len(found) == 0 || !strings.HasPrefix(found[0], "smuggled.go:") {
				t.Fatalf("a request built around the check (%s) was not found: %v", name, found)
			}
		})
	}
}

// TestTheOnePlaceRefusesEveryMethodButGetAndOptions: what the scan sends
// every request through refuses a write before it exists.
func TestTheOnePlaceRefusesEveryMethodButGetAndOptions(t *testing.T) {
	for _, method := range []string{http.MethodPost, http.MethodPut, http.MethodPatch, http.MethodDelete,
		http.MethodHead, http.MethodConnect, http.MethodTrace, "get", "BREW"} {
		if request, err := newProbeRequest(context.Background(), method, "http://example.invalid/"); err == nil || request != nil {
			t.Errorf("newProbeRequest built a %s request", method)
		}
	}
	for _, method := range []string{http.MethodGet, http.MethodOptions} {
		request, err := newProbeRequest(context.Background(), method, "http://example.invalid/")
		if err != nil || request.Method != method || request.Body != nil {
			t.Errorf("newProbeRequest(%s) = %v, %v", method, request, err)
		}
	}
}
