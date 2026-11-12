package probe

import (
	"context"
	"go/ast"
	"go/parser"
	"go/token"
	"io"
	"net/http"
	"net/url"
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
		// The names net/http is imported under in this file. httptest
		// builds requests of its own; outside a test it has no business here.
		httpNames := map[string]bool{}
		for _, spec := range file.Imports {
			path, _ := strconv.Unquote(spec.Path.Value)
			// reflect and unsafe can write a request's method, or a client's
			// transport, where no syntax shows it (the re-audit of the
			// Phase 36 part 2 fixes).
			if path == "net/http/httptest" || path == "reflect" || path == "unsafe" {
				position := fset.Position(spec.Pos())
				found = append(found, filepath.Base(position.Filename)+":"+strconv.Itoa(position.Line)+" "+path)
			}
			if path != "net/http" {
				continue
			}
			// A dot import names nothing the checks below can see.
			if spec.Name != nil && spec.Name.Name == "." {
				position := fset.Position(spec.Pos())
				found = append(found, filepath.Base(position.Filename)+":"+strconv.Itoa(position.Line)+" import . net/http")
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
			// The guard's own RoundTrip is the one place a request is handed
			// to a transport.
			inGuard := false
			if function, ok := declaration.(*ast.FuncDecl); ok && function.Recv != nil && function.Name.Name == "RoundTrip" {
				if len(function.Recv.List) == 1 {
					if ident, ok := function.Recv.List[0].Type.(*ast.Ident); ok && ident.Name == "methodGuard" {
						inGuard = true
					}
				}
			}
			// The uses of http.Client that are allowed: the type of a guarded
			// literal, and a named field holding a pointer to one. Any other —
			// `var c http.Client`, new(http.Client), an embedded client, a
			// conversion — is a client with no guard under it.
			allowedClient := map[ast.Node]bool{}
			ast.Inspect(declaration, func(node ast.Node) bool {
				switch typed := node.(type) {
				case *ast.CompositeLit:
					if name, ok := isHTTP(typed.Type, nil); ok && name == "Client" && guarded(typed) {
						allowedClient[typed.Type] = true
					}
				case *ast.Field:
					if star, ok := typed.Type.(*ast.StarExpr); ok && len(typed.Names) > 0 {
						allowedClient[star.X] = true
					}
				}
				return true
			})
			// http.Request is used only behind a pointer, outside any
			// composite literal: a request value, or a literal of one —
			// typed, or with its type left out inside a slice or map of
			// them — is a request built without the constructor.
			allowedRequest := map[ast.Node]bool{}
			ast.Inspect(declaration, func(node ast.Node) bool {
				if star, ok := node.(*ast.StarExpr); ok {
					allowedRequest[star.X] = true
				}
				return true
			})
			mentionsRequest := func(expr ast.Expr) bool {
				mentions := false
				ast.Inspect(expr, func(node ast.Node) bool {
					if name, ok := isHTTP(asExpr(node), nil); ok && name == "Request" {
						mentions = true
					}
					return true
				})
				return mentions
			}
			ast.Inspect(declaration, func(node ast.Node) bool {
				where := func(what string) {
					position := fset.Position(node.Pos())
					found = append(found, filepath.Base(position.Filename)+":"+strconv.Itoa(position.Line)+" "+what)
				}
				switch typed := node.(type) {
				case *ast.SelectorExpr:
					// Any reference, not only a call: `var build =
					// http.NewRequest` is a constructor too (Phase 36 part 2
					// audit). http.DefaultClient has no methodGuard under it.
					if name, ok := isHTTP(typed, constructorsOfNetHTTP); ok {
						where("http." + name)
					} else if name, ok := isHTTP(typed, nil); ok && name == "DefaultClient" {
						where("http.DefaultClient")
					} else if ok && name == "Client" && !allowedClient[typed] {
						where("http.Client outside a guarded literal")
					} else if ok && name == "Request" && !allowedRequest[typed] {
						where("http.Request not behind a pointer")
					}
					// A transport's RoundTrip, called or taken as a value,
					// skips the guard; only the guard itself may use it.
					if typed.Sel.Name == "RoundTrip" && !inGuard {
						where(".RoundTrip")
					}
				case *ast.UnaryExpr:
					// &r.Method and &c.Transport write through a pointer.
					if selector, ok := typed.X.(*ast.SelectorExpr); ok && typed.Op == token.AND &&
						(selector.Sel.Name == "Method" || selector.Sel.Name == "Transport") {
						where("&." + selector.Sel.Name)
					}
				case *ast.CallExpr:
					if selector, ok := typed.Fun.(*ast.SelectorExpr); ok && sendingMethods[selector.Sel.Name] {
						where("." + selector.Sel.Name + "()")
					}

					if ident, ok := typed.Fun.(*ast.Ident); ok && ident.Name == "new" && len(typed.Args) == 1 {
						if name, ok := isHTTP(typed.Args[0], nil); ok && name == "Request" {
							where("new(http.Request)")
						}
					}
				case *ast.TypeSpec:
					// A type made from http.Request — an alias or a defined
					// type — is a way to write a literal the check below
					// cannot see by name.
					if name, ok := isHTTP(typed.Type, nil); ok && name == "Request" {
						where("type " + typed.Name.Name + " from http.Request")
					}
				case *ast.CompositeLit:
					if typed.Type != nil && mentionsRequest(typed.Type) {
						where("a literal of http.Request")
					}
					// Every client this package builds sends through the
					// guard that checks the method again as a request leaves.
					if name, ok := isHTTP(typed.Type, nil); ok && name == "Client" && !guarded(typed) {
						where("http.Client without methodGuard")
					}
				case *ast.AssignStmt:
					for _, left := range typed.Lhs {
						if selector, ok := left.(*ast.SelectorExpr); ok && selector.Sel.Name == "Method" {
							where(".Method =")
						}
						// Replacing a client's transport takes the guard away.
						if selector, ok := left.(*ast.SelectorExpr); ok && selector.Sel.Name == "Transport" {
							where(".Transport =")
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

// asExpr is node as an expression, or nil.
func asExpr(node ast.Node) ast.Expr {
	expr, _ := node.(ast.Expr)
	return expr
}

// guarded reports whether an http.Client literal's Transport is a
// methodGuard literal.
func guarded(client *ast.CompositeLit) bool {
	for _, element := range client.Elts {
		field, ok := element.(*ast.KeyValueExpr)
		if !ok {
			continue
		}
		if key, ok := field.Key.(*ast.Ident); !ok || key.Name != "Transport" {
			continue
		}
		value := field.Value
		if unary, ok := value.(*ast.UnaryExpr); ok {
			value = unary.X
		}
		literal, ok := value.(*ast.CompositeLit)
		if !ok {
			return false
		}
		ident, ok := literal.Type.(*ast.Ident)
		return ok && ident.Name == "methodGuard"
	}
	return false
}

// TestTheGuardRefusesAWriteAsItLeaves: a request built by any route at all
// is refused by the transport under every client before anything is
// dialled.
func TestTheGuardRefusesAWriteAsItLeaves(t *testing.T) {
	dialled := false
	guard := methodGuard{next: roundTripFunc(func(*http.Request) (*http.Response, error) {
		dialled = true
		return nil, nil
	})}
	for _, method := range []string{http.MethodPost, http.MethodPut, http.MethodDelete, http.MethodHead, "PATCH"} {
		request := &http.Request{Method: method, URL: &url.URL{Scheme: "http", Host: "example.invalid", Path: "/"}}
		if _, err := guard.RoundTrip(request); err == nil {
			t.Errorf("the guard let a %s request through", method)
		}
	}
	withBody := &http.Request{Method: http.MethodGet, URL: &url.URL{Scheme: "http", Host: "example.invalid"},
		Body: io.NopCloser(strings.NewReader("x"))}
	if _, err := guard.RoundTrip(withBody); err == nil {
		t.Error("the guard let a GET with a body through")
	}
	if dialled {
		t.Fatal("a refused request reached the transport")
	}
	if _, err := guard.RoundTrip(&http.Request{Method: http.MethodGet, URL: &url.URL{Scheme: "http", Host: "x"}}); err != nil || !dialled {
		t.Fatalf("a plain GET did not pass the guard: %v", err)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) { return f(request) }

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
		// The Phase 36 part 2 audit's three, and a client with no guard.
		"a type alias": "type aliasRequest = http.Request\n\n" +
			`func smuggle() *http.Request { return &aliasRequest{Method: "POST"} }`,
		"a defined type": "type ownRequest http.Request\n\n" +
			`func smuggle() *http.Request { return (*http.Request)(&ownRequest{Method: "POST"}) }`,
		"a constructor value": "var zzBuild = http.NewRequest\n\n" +
			`func smuggle() (*http.Request, error) { return zzBuild("DELETE", "http://x", nil) }`,
		"httptest":            `func smuggle() *http.Request { return httptest.NewRequest("POST", "http://x", nil) }`,
		"an unguarded client": `func smuggle() *http.Client { return &http.Client{Transport: http.DefaultTransport} }`,
		"the default client":  `func smuggle() *http.Client { return http.DefaultClient }`,
		// The re-audit of the fixes: around the guard, not the constructor.
		"a pointer to the method": `func smuggle(ctx context.Context) {
	r, _ := newProbeRequest(ctx, http.MethodGet, "http://x")
	m := &r.Method
	*m = "DELETE"
}`,
		"a direct RoundTrip": `func smuggle(ctx context.Context) {
	r, _ := newProbeRequest(ctx, http.MethodGet, "http://x")
	_, _ = http.DefaultTransport.RoundTrip(r)
}`,
		"a zero-value client":  `func smuggle() { var c http.Client; _ = c }`,
		"new(http.Client)":     `func smuggle() *http.Client { return new(http.Client) }`,
		"an embedded client":   "type wrapped struct{ http.Client }\n\nfunc smuggle() wrapped { return wrapped{} }",
		"a replaced transport": `func smuggle(c *RealHTTPClient) { c.client.Transport = http.DefaultTransport }`,
		"reflect":              `func smuggle(r *http.Request) { reflect.ValueOf(r).Elem().FieldByName("Method").SetString("PUT") }`,
		// The focused re-audit: a DELETE got out with the scan green.
		"a type-omitted literal": `func smuggle() []*http.Request { return []*http.Request{{Method: "DELETE"}} }`,
		"a map of requests":      `func smuggle() map[string]*http.Request { return map[string]*http.Request{"a": {Method: "PUT"}} }`,
		"a request value":        `func smuggle() { var r http.Request; _ = r }`,
		"a RoundTrip value": `func smuggle(ctx context.Context) {
	rt := http.DefaultTransport.RoundTrip
	r, _ := newProbeRequest(ctx, http.MethodGet, "http://x")
	_, _ = rt(r)
}`,
		"dot import":                 `func smuggle() { _, _ = Post("http://x", "text/plain", nil) }`,
		"a pointer to the transport": `func smuggle(c *RealHTTPClient) { p := &c.client.Transport; *p = http.DefaultTransport }`,
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
			if name == "dot import" {
				imports = "import . \"net/http\"\n\n"
			}
			if name == "reflect" {
				imports = "import (\n\t\"net/http\"\n\t\"reflect\"\n)\n\n"
			}
			if name == "httptest" {
				imports = "import (\n\t\"net/http\"\n\t\"net/http/httptest\"\n)\n\n"
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
