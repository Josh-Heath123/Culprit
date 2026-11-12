package probe

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
)

// What holds GET-only (Q26, ruled 2026-11-12).
//
// Phase 36 part 2 held it with a syntactic scan of this package for every
// way to build or send a request around the method check. Three audits in
// a row found syntax it did not know, and the third got a DELETE out: the
// denylist pattern. It is retired. Two structural facts hold instead.
//
//  1. Only http.go and timing.go import net/http. No other file in the
//     package can name a client, a transport or a request constructor.
//     An allowlist, held as TestTheNetworkBoundaryIsAnAllowlist holds the
//     binary's: a third file that imports it is red.
//  2. Every client those two files build comes from newGuardedClient,
//     which installs methodGuard. The guard refuses anything but a bodiless
//     GET or OPTIONS as the request leaves, so a request whose method is
//     changed after it was built still leaves through it.
//
// This is a guard against ordinary code, not a proof against deliberate
// code (docs/LIMITS.md): raw bytes on a socket net.tcp.connect opened are
// outside it.

// netHTTPFiles are the only non-test files of this package that may
// import net/http or any package under it.
var netHTTPFiles = map[string]bool{"http.go": true, "timing.go": true}

// netHTTPImporters lists the non-test files in directory that import
// net/http or a package under it, as "file: path".
func netHTTPImporters(t *testing.T, directory string) []string {
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
		file, err := parser.ParseFile(fset, filepath.Join(directory, name), nil, parser.ImportsOnly)
		if err != nil {
			t.Fatal(err)
		}
		for _, spec := range file.Imports {
			path, _ := strconv.Unquote(spec.Path.Value)
			if path == "net/http" || strings.HasPrefix(path, "net/http/") {
				found = append(found, name+": "+path)
			}
		}
	}
	sort.Strings(found)
	return found
}

func TestOnlyTwoFilesImportNetHTTP(t *testing.T) {
	for _, importer := range netHTTPImporters(t, ".") {
		file, _, _ := strings.Cut(importer, ":")
		if !netHTTPFiles[file] {
			t.Errorf("%s imports net/http; only http.go and timing.go may, so that no other file can "+
				"name a client, a transport or a request constructor (Q26)", importer)
		}
	}
}

// copyPackage copies this package's non-test sources into a new directory.
func copyPackage(t *testing.T) string {
	t.Helper()
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
	return root
}

// TestAThirdFileImportingNetHTTPIsFound is the allowlist's red state.
func TestAThirdFileImportingNetHTTPIsFound(t *testing.T) {
	for name, imports := range map[string]string{
		"net/http":            `import "net/http"` + "\n\nvar _ http.Header\n",
		"aliased":             `import web "net/http"` + "\n\nvar _ web.Header\n",
		"a package under it":  `import "net/http/httputil"` + "\n\nvar _ = httputil.DumpRequest\n",
		"with other packages": "import (\n\t\"fmt\"\n\t\"net/http\"\n)\n\nvar _ = fmt.Sprint\nvar _ http.Header\n",
	} {
		t.Run(name, func(t *testing.T) {
			root := copyPackage(t)
			if err := os.WriteFile(filepath.Join(root, "smuggled.go"), []byte("package probe\n\n"+imports), 0o644); err != nil {
				t.Fatal(err)
			}
			found := false
			for _, importer := range netHTTPImporters(t, root) {
				found = found || strings.HasPrefix(importer, "smuggled.go:")
			}
			if !found {
				t.Fatalf("a third file importing net/http (%s) was not found", name)
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
		isHTTP := func(expr ast.Expr, name string) bool {
			selector, ok := expr.(*ast.SelectorExpr)
			if !ok || selector.Sel.Name != name {
				return false
			}
			ident, ok := selector.X.(*ast.Ident)
			return ok && ident.Name == "http"
		}
		for _, declaration := range file.Decls {
			inConstructor := false
			if function, ok := declaration.(*ast.FuncDecl); ok && function.Recv == nil &&
				function.Name.Name == "newGuardedClient" {
				inConstructor = true
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
	var paths []string
	for name := range netHTTPFiles {
		paths = append(paths, name)
	}
	if found := clientsBuiltElsewhere(t, paths...); len(found) > 0 {
		t.Fatalf("a client is built other than by newGuardedClient, so without methodGuard: %v", found)
	}
}

// TestAClientBuiltAnotherWayIsFound is the constructor rule's red state: a
// copy of timing.go with one more client in it, each way.
func TestAClientBuiltAnotherWayIsFound(t *testing.T) {
	source, err := os.ReadFile("timing.go")
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
	} {
		t.Run(name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "timing.go")
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
