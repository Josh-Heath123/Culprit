// Package boundarytest holds the structural checks behind Q27's package
// isolation (docs/PERFORMANCE_PLAN.md, end of Phase 37): that a boundary
// package has one non-test file, that its exported surface names no type
// from a network or driver package, and that code planted in another
// package cannot reach what the boundary keeps unexported. Used only by
// tests; it links no network package itself.
package boundarytest

import (
	"fmt"
	"go/ast"
	"go/importer"
	"go/parser"
	"go/token"
	"go/types"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"sync"
)

// NonTestFiles lists a directory's non-test Go files.
func NonTestFiles(directory string) ([]string, error) {
	entries, err := os.ReadDir(directory)
	if err != nil {
		return nil, err
	}
	var files []string
	for _, entry := range entries {
		name := entry.Name()
		if !entry.IsDir() && strings.HasSuffix(name, ".go") && !strings.HasSuffix(name, "_test.go") {
			files = append(files, name)
		}
	}
	sort.Strings(files)
	return files, nil
}

// ExportedTypesFrom type-checks the package in directory from source, with
// the real types of everything it imports, and lists every type from a
// package whose path starts with one of forbidden that its exported surface
// names: an exported function's or method's signature, an exported
// variable's or constant's type, an exported type and the exported fields
// and methods of every type reachable from those. A caller can hold any of
// these, so one that is a client, a transport or a connection is one a
// caller can unwrap.
func ExportedTypesFrom(directory string, forbidden []string) ([]string, error) {
	fset := token.NewFileSet()
	names, err := NonTestFiles(directory)
	if err != nil {
		return nil, err
	}
	var files []*ast.File
	for _, name := range names {
		file, err := parser.ParseFile(fset, filepath.Join(directory, name), nil, 0)
		if err != nil {
			return nil, err
		}
		files = append(files, file)
	}
	// The compiler's own export data, found by `go list -export` from the
	// test's own directory (inside the module, so pgx resolves), not a
	// source importer: the real types of net/http and pgx, in seconds
	// rather than minutes.
	config := types.Config{Importer: exportData(fset)}
	pkg, err := config.Check(files[0].Name.Name, fset, files, nil)
	if err != nil {
		return nil, fmt.Errorf("type-checking %s: %w", directory, err)
	}

	isForbidden := func(path string) bool {
		for _, prefix := range forbidden {
			if path == prefix || strings.HasPrefix(path, prefix+"/") {
				return true
			}
		}
		return false
	}
	found := map[string]bool{}
	seen := map[types.Type]bool{}
	var walk func(t types.Type, where string)
	walk = func(t types.Type, where string) {
		if t == nil || seen[t] {
			return
		}
		seen[t] = true
		switch typed := t.(type) {
		case *types.Alias:
			walk(types.Unalias(typed), where)
		case *types.Named:
			if object := typed.Obj(); object.Pkg() != nil && isForbidden(object.Pkg().Path()) {
				found[fmt.Sprintf("%s: %s.%s", where, object.Pkg().Path(), object.Name())] = true
				return
			}
			for index := 0; index < typed.NumMethods(); index++ {
				if method := typed.Method(index); method.Exported() {
					walk(method.Type(), where+"."+method.Name())
				}
			}
			walk(typed.Underlying(), where)
		case *types.Pointer:
			walk(typed.Elem(), where)
		case *types.Slice:
			walk(typed.Elem(), where)
		case *types.Array:
			walk(typed.Elem(), where)
		case *types.Map:
			walk(typed.Key(), where)
			walk(typed.Elem(), where)
		case *types.Chan:
			walk(typed.Elem(), where)
		case *types.Signature:
			for index := 0; index < typed.Params().Len(); index++ {
				walk(typed.Params().At(index).Type(), where)
			}
			for index := 0; index < typed.Results().Len(); index++ {
				walk(typed.Results().At(index).Type(), where)
			}
		case *types.Struct:
			for index := 0; index < typed.NumFields(); index++ {
				if field := typed.Field(index); field.Exported() || field.Embedded() {
					walk(field.Type(), where+"."+field.Name())
				}
			}
		case *types.Interface:
			for index := 0; index < typed.NumMethods(); index++ {
				walk(typed.Method(index).Type(), where+"."+typed.Method(index).Name())
			}
		}
	}
	scope := pkg.Scope()
	for _, name := range scope.Names() {
		object := scope.Lookup(name)
		if !object.Exported() {
			continue
		}
		walk(object.Type(), name)
		if named, ok := object.Type().(*types.Named); ok {
			// Methods on the pointer receiver too.
			methods := types.NewMethodSet(types.NewPointer(named))
			for index := 0; index < methods.Len(); index++ {
				if method := methods.At(index).Obj(); method.Exported() {
					walk(method.Type(), name+"."+method.Name())
				}
			}
		}
	}
	var list []string
	for entry := range found {
		list = append(list, entry)
	}
	sort.Strings(list)
	return list, nil
}

// moduleImporter type-checks this module's packages from source, so a
// planted file is checked against them as they are on disk, and takes
// everything else from the compiler's export data.
type moduleImporter struct {
	fset   *token.FileSet
	module string
	root   string
	cache  map[string]*types.Package
	others types.Importer
}

func (m *moduleImporter) Import(path string) (*types.Package, error) {
	return m.ImportFrom(path, "", 0)
}

func (m *moduleImporter) ImportFrom(path, _ string, _ types.ImportMode) (*types.Package, error) {
	if cached, ok := m.cache[path]; ok {
		return cached, nil
	}
	if !strings.HasPrefix(path, m.module+"/") {
		pkg, err := m.others.Import(path)
		if err == nil {
			m.cache[path] = pkg
		}
		return pkg, err
	}
	directory := filepath.Join(m.root, filepath.FromSlash(strings.TrimPrefix(path, m.module+"/")))
	pkg, _, err := m.check(path, directory, "", "")
	if err == nil {
		m.cache[path] = pkg
	}
	return pkg, err
}

// check type-checks one directory's non-test files, plus one planted file
// when given, and returns the errors that fall in the planted file.
func (m *moduleImporter) check(path, directory, plantedName, planted string) (*types.Package, []string, error) {
	names, err := NonTestFiles(directory)
	if err != nil {
		return nil, nil, err
	}
	var files []*ast.File
	for _, name := range names {
		file, err := parser.ParseFile(m.fset, filepath.Join(directory, name), nil, 0)
		if err != nil {
			return nil, nil, err
		}
		files = append(files, file)
	}
	if planted != "" {
		file, err := parser.ParseFile(m.fset, filepath.Join(directory, plantedName), planted, 0)
		if err != nil {
			return nil, nil, err
		}
		files = append(files, file)
	}
	var plantedErrors []string
	config := types.Config{Importer: m, Error: func(err error) {
		if typeErr, ok := err.(types.Error); ok &&
			filepath.Base(m.fset.Position(typeErr.Pos).Filename) == plantedName && plantedName != "" {
			plantedErrors = append(plantedErrors, typeErr.Msg)
		}
	}}
	pkg, _ := config.Check(path, m.fset, files, nil)
	return pkg, plantedErrors, nil
}

// exportData is the gc importer over export data `go list -export` names,
// run from the current directory, which a test runs in: its own package's
// directory, inside the module.
func exportData(fset *token.FileSet) types.Importer {
	return importer.ForCompiler(fset, "gc", func(path string) (io.ReadCloser, error) {
		exportMu.Lock()
		file, known := exportFiles[path]
		if !known {
			// One `go list -deps` fills the cache for everything below path.
			out, err := exec.Command("go", "list", "-export", "-deps", "-f", "{{.ImportPath}}={{.Export}}", path).Output()
			if err != nil {
				exportMu.Unlock()
				return nil, fmt.Errorf("go list -export %s: %w", path, err)
			}
			for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
				if imported, export, ok := strings.Cut(strings.TrimSpace(line), "="); ok {
					exportFiles[imported] = export
				}
			}
			file = exportFiles[path]
		}
		exportMu.Unlock()
		if file == "" {
			return nil, fmt.Errorf("no export data for %s", path)
		}
		return os.Open(file)
	})
}

// exportFiles caches `go list -export` answers for the test process.
var (
	exportMu    sync.Mutex
	exportFiles = map[string]string{}
)

// PlantedErrors type-checks the package at module-relative path rel, with
// one more file holding source, and returns the type errors in that file.
// root is the module's directory and module its path.
func PlantedErrors(root, module, rel, source string) ([]string, error) {
	m0fset := token.NewFileSet()
	m := &moduleImporter{fset: m0fset, module: module, root: root,
		cache: map[string]*types.Package{}, others: exportData(m0fset)}
	_, errs, err := m.check(module+"/"+rel, filepath.Join(root, filepath.FromSlash(rel)), "zz_planted.go", source)
	return errs, err
}
