package probe

import (
	"go/ast"
	"go/parser"
	"go/token"
	"go/types"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

// Only BuiltIn registers a probe (Q25, ruled 2026-11-12).
//
// `culprit mcp` binds the address inputs it knows by name, and
// TestEveryCatalogueInputIsClassified holds every catalogue probe's inputs
// to that list. Both hold only while every probe an agent can run is a
// catalogue probe, which is true while nothing but BuiltIn calls
// Catalogue.Register. This test makes that a property of the source, not
// of the reader's memory: it type-checks every non-test package under cli/
// and finds every call of (*Catalogue).Register by its type, so a method of
// the same name on another type (transport.Client's) is not confused for
// it, and an aliased or chained call is not missed.

// modulePath is cli/go.mod's module.
const modulePath = "github.com/josh-heath123/culprit/cli"

// moduleImporter type-checks this module's own packages from source and
// stands an empty package in for everything else. A call's receiver type
// is all this test needs, and Catalogue is this module's; type-checking
// cobra, pgx and the rest from source took two minutes for nothing.
type moduleImporter struct {
	fset  *token.FileSet
	root  string
	cache map[string]*types.Package
}

func (m *moduleImporter) Import(path string) (*types.Package, error) {
	return m.ImportFrom(path, "", 0)
}

func (m *moduleImporter) ImportFrom(path, _ string, _ types.ImportMode) (*types.Package, error) {
	if cached, ok := m.cache[path]; ok {
		return cached, nil
	}
	if !strings.HasPrefix(path, modulePath+"/") {
		stub := types.NewPackage(path, filepath.Base(path))
		stub.MarkComplete()
		m.cache[path] = stub
		return stub, nil
	}
	directory := filepath.Join(m.root, filepath.FromSlash(strings.TrimPrefix(path, modulePath+"/")))
	pkg, _, _, err := m.check(path, directory)
	return pkg, err
}

// check parses and type-checks one directory's non-test files.
func (m *moduleImporter) check(path, directory string) (*types.Package, []*ast.File, *types.Info, error) {
	entries, err := os.ReadDir(directory)
	if err != nil {
		return nil, nil, nil, err
	}
	var files []*ast.File
	for _, entry := range entries {
		name := entry.Name()
		if !strings.HasSuffix(name, ".go") || strings.HasSuffix(name, "_test.go") {
			continue
		}
		file, err := parser.ParseFile(m.fset, filepath.Join(directory, name), nil, 0)
		if err != nil {
			return nil, nil, nil, err
		}
		files = append(files, file)
	}
	info := &types.Info{Selections: map[*ast.SelectorExpr]*types.Selection{}}
	config := types.Config{Importer: m, Error: func(error) {}}
	pkg, _ := config.Check(path, m.fset, files, info)
	m.cache[path] = pkg
	return pkg, files, info, nil
}

// registrationsOutsideBuiltIn returns "file: function" for every call of
// (*probe.Catalogue).Register under root that is not inside probe.BuiltIn.
func registrationsOutsideBuiltIn(t *testing.T, root string) []string {
	t.Helper()
	directories := map[string]bool{}
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		// testdata is scanned too: the go tool builds a package there into
		// the binary if anything imports it (Phase 36 re-audit).
		if entry.IsDir() && strings.HasPrefix(entry.Name(), ".") && path != root {
			return filepath.SkipDir
		}
		if !entry.IsDir() && strings.HasSuffix(path, ".go") && !strings.HasSuffix(path, "_test.go") {
			directories[filepath.Dir(path)] = true
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}

	fset := token.NewFileSet()
	imports := &moduleImporter{fset: fset, root: root, cache: map[string]*types.Package{}}
	var found []string
	for directory := range directories {
		relative, err := filepath.Rel(root, directory)
		if err != nil {
			t.Fatal(err)
		}
		path := modulePath
		if relative != "." {
			path += "/" + filepath.ToSlash(relative)
		}
		// Checked afresh, not from the import cache, because the cache
		// keeps no Selections.
		pkg, files, info, err := imports.check(path, directory)
		if err != nil || pkg == nil {
			t.Fatalf("could not type-check %s: %v", directory, err)
		}
		for _, file := range files {
			// Every declaration, not only function bodies: a package-level
			// initializer can register as well as a function can (Phase 36
			// phase audit).
			for _, declaration := range file.Decls {
				where, inBuiltIn := "package level", false
				if function, ok := declaration.(*ast.FuncDecl); ok {
					where = function.Name.Name
					inBuiltIn = function.Recv == nil && function.Name.Name == "BuiltIn" &&
						pkg.Path() == modulePath+"/internal/probe"
				}
				ast.Inspect(declaration, func(node ast.Node) bool {
					selector, ok := node.(*ast.SelectorExpr)
					if !ok || selector.Sel.Name != "Register" {
						return true
					}
					selection := info.Selections[selector]
					if selection == nil || !registersAProbe(selection.Obj()) {
						return true
					}
					if !inBuiltIn {
						position := fset.Position(selector.Pos())
						relative, _ := filepath.Rel(root, position.Filename)
						found = append(found, filepath.ToSlash(relative)+": "+where)
					}
					return true
				})
			}
		}
	}
	sort.Strings(found)
	return found
}

// registersAProbe reports whether a method could register a probe:
// Catalogue's own Register, or any Register that takes a probe.Probe — an
// interface method a Catalogue satisfies is a way to call it that names no
// Catalogue (Phase 36 phase audit).
func registersAProbe(object types.Object) bool {
	if isCatalogueRegister(object) {
		return true
	}
	signature, ok := object.Type().(*types.Signature)
	if !ok {
		return false
	}
	for index := 0; index < signature.Params().Len(); index++ {
		if named, ok := signature.Params().At(index).Type().(*types.Named); ok &&
			named.Obj().Name() == "Probe" && named.Obj().Pkg() != nil &&
			strings.HasSuffix(named.Obj().Pkg().Path(), "internal/probe") {
			return true
		}
	}
	return false
}

// isCatalogueRegister reports whether a method object is Catalogue's
// Register, by its receiver's type name and package.
func isCatalogueRegister(object types.Object) bool {
	method, ok := object.(*types.Func)
	if !ok {
		return false
	}
	signature, ok := method.Type().(*types.Signature)
	if !ok || signature.Recv() == nil {
		return false
	}
	receiver := signature.Recv().Type()
	if pointer, isPointer := receiver.(*types.Pointer); isPointer {
		receiver = pointer.Elem()
	}
	named, ok := receiver.(*types.Named)
	return ok && named.Obj().Name() == "Catalogue" && named.Obj().Pkg() != nil &&
		strings.HasSuffix(named.Obj().Pkg().Path(), "internal/probe")
}

func TestOnlyBuiltInRegistersAProbe(t *testing.T) {
	root, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	if found := registrationsOutsideBuiltIn(t, root); len(found) > 0 {
		t.Fatalf("Catalogue.Register is called outside probe.BuiltIn: %v. culprit mcp binds only "+
			"the address inputs it knows; a probe registered anywhere else is one whose inputs "+
			"nobody classified (Q25).", found)
	}
}

// TestARegistrationElsewhereIsFound is the red state: a copy of the
// module's sources with one extra registration, in another package, is
// caught. A copy, not the real tree: `go test ./...` runs packages in
// parallel, and a stray package there would be seen by other tests.
func TestARegistrationElsewhereIsFound(t *testing.T) {
	source, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	err = filepath.WalkDir(filepath.Join(source, "internal"), func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() && entry.Name() == "testdata" {
			return filepath.SkipDir
		}
		if entry.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		relative, _ := filepath.Rel(source, path)
		target := filepath.Join(root, relative)
		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return err
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		return os.WriteFile(target, data, 0o644)
	})
	if err != nil {
		t.Fatal(err)
	}
	if found := registrationsOutsideBuiltIn(t, root); len(found) > 0 {
		t.Fatalf("the copy already has registrations outside BuiltIn: %v", found)
	}
	stray := filepath.Join(root, "internal", "stray")
	if err := os.MkdirAll(stray, 0o755); err != nil {
		t.Fatal(err)
	}
	code := "package stray\n\nimport \"github.com/josh-heath123/culprit/cli/internal/probe\"\n\n" +
		"// Smuggle registers a probe outside BuiltIn.\nfunc Smuggle(p probe.Probe) error {\n" +
		"\tcatalogue := probe.BuiltIn()\n\treturn catalogue.Register(p)\n}\n"
	if err := os.WriteFile(filepath.Join(stray, "stray.go"), []byte(code), 0o644); err != nil {
		t.Fatal(err)
	}
	// The two ways around the first version of this test: a package-level
	// initializer, and a call through an interface naming no Catalogue.
	evasions := "package stray\n\nimport \"github.com/josh-heath123/culprit/cli/internal/probe\"\n\n" +
		"var extra probe.Probe\n\n" +
		"// Cat registers at package level.\nvar Cat = func() *probe.Catalogue {\n" +
		"\tc := probe.BuiltIn()\n\t_ = c.Register(extra)\n\treturn c\n}()\n\n" +
		"type registrar interface{ Register(probe.Probe) error }\n\n" +
		"// Through registers through an interface.\nfunc Through(p probe.Probe) error {\n" +
		"\tvar r registrar = probe.BuiltIn()\n\treturn r.Register(p)\n}\n"
	if err := os.WriteFile(filepath.Join(stray, "evasions.go"), []byte(evasions), 0o644); err != nil {
		t.Fatal(err)
	}
	hidden := filepath.Join(stray, "testdata", "hid")
	if err := os.MkdirAll(hidden, 0o755); err != nil {
		t.Fatal(err)
	}
	inTestdata := "package hid\n\nimport \"github.com/josh-heath123/culprit/cli/internal/probe\"\n\n" +
		"var extra probe.Probe\n\n// Err registers from a testdata directory.\n" +
		"var Err = probe.BuiltIn().Register(extra)\n"
	if err := os.WriteFile(filepath.Join(hidden, "hid.go"), []byte(inTestdata), 0o644); err != nil {
		t.Fatal(err)
	}
	found := registrationsOutsideBuiltIn(t, root)
	want := []string{
		"internal/stray/evasions.go: Through",
		"internal/stray/evasions.go: package level",
		"internal/stray/stray.go: Smuggle",
		"internal/stray/testdata/hid/hid.go: package level",
	}
	if strings.Join(found, " | ") != strings.Join(want, " | ") {
		t.Fatalf("registrations outside BuiltIn found: %v, want %v", found, want)
	}
}
