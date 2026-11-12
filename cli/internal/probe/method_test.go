package probe

import (
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/boundarytest"
)

// GET-only is held by internal/probe/guardedhttp, a package of its own
// (Q27, ruled 2026-11-12). This package imports no net/http at all, so the
// only HTTP it can send is through guardedhttp's exported surface — and
// what the Phase 37 part 1 audit did from a file here, reaching the guard's
// own transport through a client's fields, is now a type error.

// netHTTPImporters lists the non-test files in directory that import
// net/http or a package under it.
func netHTTPImporters(t *testing.T, directory string) []string {
	t.Helper()
	names, err := boundarytest.NonTestFiles(directory)
	if err != nil {
		t.Fatal(err)
	}
	fset := token.NewFileSet()
	var found []string
	for _, name := range names {
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
	return found
}

func TestProbeImportsNoNetHTTP(t *testing.T) {
	if found := netHTTPImporters(t, "."); len(found) > 0 {
		t.Fatalf("internal/probe imports net/http (%v); every request goes through guardedhttp (Q27)", found)
	}
}

// TestAFileHereImportingNetHTTPIsFound is that rule's red state, in each
// form an import can take.
func TestAFileHereImportingNetHTTPIsFound(t *testing.T) {
	for name, source := range map[string]string{
		"plain":              "package probe\n\nimport \"net/http\"\n\nvar _ http.Client\n",
		"aliased":            "package probe\n\nimport web \"net/http\"\n\nvar _ web.Client\n",
		"a package under it": "package probe\n\nimport \"net/http/httputil\"\n\nvar _ = httputil.DumpRequest\n",
		"grouped, blank":     "package probe\n\nimport (\n\t\"context\"\n\t_ \"net/http/pprof\"\n)\n\nvar _ context.Context\n",
		"dot":                "package probe\n\nimport . \"net/http\"\n\nvar _ Client\n",
	} {
		root := t.TempDir()
		if err := os.WriteFile(filepath.Join(root, "smuggled.go"), []byte(source), 0o644); err != nil {
			t.Fatal(err)
		}
		if len(netHTTPImporters(t, root)) == 0 {
			t.Errorf("a file importing net/http (%s) was not found", name)
		}
	}
}

// moduleRoot is cli/, and module its path.
func moduleRoot(t *testing.T) string {
	t.Helper()
	root, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	return root
}

// TestTheAuditsAttackNoLongerTypeChecks: the file the Phase 37 part 1
// phase-auditor added here — no imports, a request built as a GET, its
// method changed, sent straight through the guard's own transport — is
// planted in this package and type-checked: it does not compile. A file
// using only the exported surface does.
func TestTheAuditsAttackNoLongerTypeChecks(t *testing.T) {
	attack := `package probe

import "context"

func smuggle(ctx context.Context, c *RealHTTPClient, url string) {
	request, _ := newProbeRequest(ctx, "GET", url)
	request.Method = "DELETE"
	_, _ = c.client.Transport.(methodGuard).next.RoundTrip(request)
}
`
	errs, err := boundarytest.PlantedErrors(moduleRoot(t), modulePath, "internal/probe", attack)
	if err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(errs, "; ")
	// The checker reports the first error in each expression: c.client
	// stops it before methodGuard and .next are reached.
	for _, want := range []string{"newProbeRequest", "client"} {
		if !strings.Contains(joined, want) {
			t.Errorf("planting the audit's file: no type error about %s (errors: %v)", want, errs)
		}
	}
	allowed := `package probe

import "context"

func fine(ctx context.Context, c *RealHTTPClient, url string) {
	_, _ = c.Get(ctx, url, nil)
}
`
	if errs, err := boundarytest.PlantedErrors(moduleRoot(t), modulePath, "internal/probe", allowed); err != nil || len(errs) > 0 {
		t.Fatalf("a file using only the exported surface did not type-check: %v %v", errs, err)
	}
}
