package guardedhttp

import (
	"context"
	"go/ast"
	"go/parser"
	"go/token"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/boundarytest"
)

// What holds GET-only (Q26, and Q27's package isolation, ruled 2026-11-12):
// this package, with one non-test file, is the only place a request is
// built or sent; every client it builds has methodGuard under it; and its
// exported surface names no net/http or net type, so nothing outside can
// unwrap a client, a transport or a request. Code in internal/probe that
// tries is a type error (internal/probe's TestTheAuditsAttackNoLongerTypeChecks).

// TestThisPackageHasOneFile: a second non-test file would be a file that
// reaches every unexported field here.
func TestThisPackageHasOneFile(t *testing.T) {
	files, err := boundarytest.NonTestFiles(".")
	if err != nil || len(files) != 1 || files[0] != "client.go" {
		t.Fatalf("guardedhttp's non-test files are %v (%v); it must be client.go alone", files, err)
	}
}

// TestASecondFileIsFound is that rule's red state.
func TestASecondFileIsFound(t *testing.T) {
	root := t.TempDir()
	for _, name := range []string{"client.go", "zz_second.go"} {
		if err := os.WriteFile(filepath.Join(root, name), []byte("package guardedhttp\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if files, _ := boundarytest.NonTestFiles(root); len(files) == 1 {
		t.Fatal("a second non-test file was not found")
	}
}

// forbidden are the packages whose types the exported surface may not name.
var forbidden = []string{"net/http", "net", "github.com/jackc"}

// TestTheExportedSurfaceNamesNoNetworkType, by go/types over the real
// types: no exported function, method, field or type here holds a client,
// a transport, a request or a connection a caller could unwrap.
func TestTheExportedSurfaceNamesNoNetworkType(t *testing.T) {
	found, err := boundarytest.ExportedTypesFrom(".", forbidden)
	if err != nil {
		t.Fatal(err)
	}
	if len(found) > 0 {
		t.Fatalf("the exported surface names a network type, which a caller could unwrap: %v", found)
	}
}

// TestAnExportedNetworkTypeIsFound is that rule's red state: a copy of
// client.go with one export more, each way.
func TestAnExportedNetworkTypeIsFound(t *testing.T) {
	source, err := os.ReadFile("client.go")
	if err != nil {
		t.Fatal(err)
	}
	for name, code := range map[string]string{
		"a function returning the client":  "func Client(c *RealHTTPClient) *http.Client { return c.client }",
		"a method returning the transport": "func (c *RealHTTPClient) Transport() http.RoundTripper { return c.client.Transport }",
		"an exported field":                "type Exposed struct{ Client *http.Client }",
		"an alias":                         "type Request = http.Request",
		"a connection":                     "func Dial() (net.Conn, error) { return nil, nil }",
	} {
		t.Run(name, func(t *testing.T) {
			root := t.TempDir()
			text := string(source)
			if strings.Contains(code, "net.Conn") {
				text = strings.Replace(text, "import (\n", "import (\n\t\"net\"\n", 1)
			}
			if err := os.WriteFile(filepath.Join(root, "client.go"), []byte(text+"\n"+code+"\n"), 0o644); err != nil {
				t.Fatal(err)
			}
			found, err := boundarytest.ExportedTypesFrom(root, forbidden)
			if err != nil {
				t.Fatal(err)
			}
			if len(found) == 0 {
				t.Fatalf("an exported network type (%s) was not found", name)
			}
		})
	}
}

// clientsBuiltElsewhere lists, in the given files, every client made other
// than by newGuardedClient: an http.Client literal, new(http.Client), a
// client value (a variable, a field or an embedding not behind a pointer),
// http.DefaultClient, or a transport replaced or written through a pointer.
// The two files are short and the only ones that can name a client at all,
// which is what makes this a property rather than a denylist of syntax.
func clientsBuiltElsewhere(t *testing.T, paths ...string) []string {
	t.Helper()
	fset := token.NewFileSet()
	var found []string
	for _, path := range paths {
		file, err := parser.ParseFile(fset, path, nil, 0)
		if err != nil {
			t.Fatal(err)
		}
		// net/http under its own name only: an alias would hide every
		// check below from a reader of these two files (invariant audit).
		for _, spec := range file.Imports {
			imported, _ := strconv.Unquote(spec.Path.Value)
			if imported == "net/http" && spec.Name != nil && spec.Name.Name != "http" {
				position := fset.Position(spec.Pos())
				found = append(found, filepath.Base(position.Filename)+":"+strconv.Itoa(position.Line)+
					" net/http imported as "+spec.Name.Name)
			}
		}
		isHTTP := func(expr ast.Expr, name string) bool {
			selector, ok := expr.(*ast.SelectorExpr)
			if !ok || selector.Sel.Name != name {
				return false
			}
			ident, ok := selector.X.(*ast.Ident)
			return ok && ident.Name == "http"
		}
		for _, declaration := range file.Decls {
			inConstructor, inGuard := false, false
			if function, ok := declaration.(*ast.FuncDecl); ok && function.Recv == nil &&
				function.Name.Name == "newGuardedClient" {
				inConstructor = true
			}
			if function, ok := declaration.(*ast.FuncDecl); ok && function.Recv != nil &&
				function.Name.Name == "RoundTrip" && len(function.Recv.List) == 1 {
				if ident, ok := function.Recv.List[0].Type.(*ast.Ident); ok && ident.Name == "methodGuard" {
					inGuard = true
				}
			}
			behindPointer := map[ast.Node]bool{}
			ast.Inspect(declaration, func(node ast.Node) bool {
				if star, ok := node.(*ast.StarExpr); ok {
					behindPointer[star.X] = true
				}
				return true
			})
			ast.Inspect(declaration, func(node ast.Node) bool {
				where := func(what string) {
					position := fset.Position(node.Pos())
					found = append(found, filepath.Base(position.Filename)+":"+strconv.Itoa(position.Line)+" "+what)
				}
				switch typed := node.(type) {
				case *ast.CompositeLit:
					if isHTTP(typed.Type, "Client") && !inConstructor {
						where("an http.Client literal")
					}
				case *ast.CallExpr:
					if ident, ok := typed.Fun.(*ast.Ident); ok && ident.Name == "new" && len(typed.Args) == 1 &&
						isHTTP(typed.Args[0], "Client") {
						where("new(http.Client)")
					}
				case *ast.SelectorExpr:
					if isHTTP(typed, "DefaultClient") {
						where("http.DefaultClient")
					}
					if isHTTP(typed, "Client") && !behindPointer[typed] && !inConstructor {
						where("an http.Client value")
					}
					// A transport's RoundTrip, called or stored, sends around
					// the guard; only the guard itself may use it.
					if typed.Sel.Name == "RoundTrip" && !inGuard {
						where("a RoundTrip outside the guard")
					}
				case *ast.AssignStmt:
					for _, left := range typed.Lhs {
						if selector, ok := left.(*ast.SelectorExpr); ok && selector.Sel.Name == "Transport" {
							where("a replaced transport")
						}
					}
				case *ast.UnaryExpr:
					if selector, ok := typed.X.(*ast.SelectorExpr); ok && typed.Op == token.AND &&
						selector.Sel.Name == "Transport" {
						where("a pointer to a transport")
					}
				}
				return true
			})
		}
	}
	sort.Strings(found)
	return found
}

func TestEveryClientComesFromTheGuardedConstructor(t *testing.T) {
	if found := clientsBuiltElsewhere(t, "client.go"); len(found) > 0 {
		t.Fatalf("a client is built other than by newGuardedClient, so without methodGuard: %v", found)
	}
}

// TestAClientBuiltAnotherWayIsFound is the constructor rule's red state: a
// copy of client.go with one more client in it, each way.
func TestAClientBuiltAnotherWayIsFound(t *testing.T) {
	source, err := os.ReadFile("client.go")
	if err != nil {
		t.Fatal(err)
	}
	for name, code := range map[string]string{
		"a literal":            "func smuggle() *http.Client { return &http.Client{} }",
		"new":                  "func smuggle() *http.Client { return new(http.Client) }",
		"a value":              "func smuggle() { var c http.Client; _ = c }",
		"the default client":   "func smuggle() *http.Client { return http.DefaultClient }",
		"an embedding":         "type wrapped struct{ http.Client }",
		"a replaced transport": "func smuggle(c *RealHTTPClient) { c.client.Transport = http.DefaultTransport }",
		"a transport through a pointer": "func smuggle(c *RealHTTPClient) {\n" +
			"\tp := &c.client.Transport\n\t*p = http.DefaultTransport\n}",
		"a direct RoundTrip": "func smuggle(r *http.Request) { _, _ = http.DefaultTransport.RoundTrip(r) }",
		"a stored RoundTrip": "func smuggle() { send := http.DefaultTransport.RoundTrip; _ = send }",
	} {
		t.Run(name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "client.go")
			if err := os.WriteFile(path, append(append([]byte{}, source...), []byte("\n"+code+"\n")...), 0o644); err != nil {
				t.Fatal(err)
			}
			if found := clientsBuiltElsewhere(t, path); len(found) == 0 {
				t.Fatalf("a client built another way (%s) was not found", name)
			}
		})
	}
}

// TestTheGuardedConstructorInstallsTheGuard: what the constructor builds
// sends through methodGuard, over whatever transport it was given.
func TestTheGuardedConstructorInstallsTheGuard(t *testing.T) {
	client := newGuardedClient(http.DefaultTransport, 0, nil)
	guard, ok := client.Transport.(methodGuard)
	if !ok || guard.next != http.DefaultTransport {
		t.Fatalf("newGuardedClient's transport is %T, want methodGuard over the one given", client.Transport)
	}
	if real, ok := NewRealHTTPClient(0).client.Transport.(methodGuard); !ok || real.next == nil {
		t.Fatal("NewRealHTTPClient's client has no methodGuard")
	}
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

// TestARequestChangedAfterItWasBuiltIsRefusedAsItLeaves: the third audit's
// DELETE, through the real client against a real server, counted there.
// newProbeRequest checked a GET; the method changed afterwards; the guard
// under the client refuses it, and nothing arrives.
func TestARequestChangedAfterItWasBuiltIsRefusedAsItLeaves(t *testing.T) {
	var arrived atomic.Int64
	server := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { arrived.Add(1) }))
	defer server.Close()
	client := NewRealHTTPClient(0)
	for _, change := range []func(*http.Request){
		func(r *http.Request) { r.Method = http.MethodDelete },
		func(r *http.Request) { m := &r.Method; *m = http.MethodPut },
		func(r *http.Request) { r.Body = io.NopCloser(strings.NewReader("x")) },
	} {
		request, err := newProbeRequest(context.Background(), http.MethodGet, server.URL)
		if err != nil {
			t.Fatal(err)
		}
		change(request)
		if response, err := client.client.Do(request); err == nil {
			_ = response.Body.Close()
			t.Errorf("a %s request (body %v) left the client", request.Method, request.Body != nil)
		}
	}
	if got := arrived.Load(); got != 0 {
		t.Fatalf("%d requests reached the server", got)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) { return f(request) }

// TestTheOnePlaceRefusesEveryMethodButGetAndOptions: newProbeRequest
// refuses a write before the request exists.
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

// TestAnAliasedNetHTTPIsFound: in client.go, net/http is imported
// under its own name, so the client checks can see it (invariant audit,
// Phase 37 part 1).
func TestAnAliasedNetHTTPIsFound(t *testing.T) {
	path := filepath.Join(t.TempDir(), "client.go")
	source := "package guardedhttp\n\nimport web \"net/http\"\n\nfunc smuggle() *web.Client { return &web.Client{} }\n"
	if err := os.WriteFile(path, []byte(source), 0o644); err != nil {
		t.Fatal(err)
	}
	if found := clientsBuiltElsewhere(t, path); len(found) == 0 {
		t.Fatal("net/http imported under another name was not found")
	}
}
