package main

import (
	"fmt"
	"math"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The fault library's database fault (docs/PERFORMANCE_PLAN.md Phase 37,
// part 3, with Q33 and Q35): inventory-service's list route is slow for a
// category with no products, because no index leads `category`.
//
// The fault is planted in the database and in the tree the walk reads,
// because the walk reads INTENT from the source (Q33 (2)):
//   - at the fault, the database is at 0002 and the tree holds 0001-0002;
//   - the known fix is the commit that adds 0003, with the database
//     upgraded to it;
//   - the wrong fix is a migration indexing `category` alone, from the
//     library's own test data, in the tree and applied.
//
// All of it is harness: the database is moved by Alembic, as the demo's
// owner, inside inventory-service. Culprit creates and drops nothing.

// demoTree is which of inventory-service's migrations the walk's tree holds.
type demoTree int

const (
	treeHead         demoTree = iota // 0001-0003, the repository as it is
	treeFault                        // 0001-0002: the commit before 0003
	treeCategoryOnly                 // 0001-0002 and the category-only migration
)

const (
	demoHeadRevision     = "0003_products_category_sku"
	demoFaultRevision    = "0002_seed_products"
	categoryOnlyRevision = "0003_products_category"
	// The head's own migration file, absent from the tree at the fault.
	demoHeadMigration = "0003_index_products_category_sku.py"
	// The budgets the demo's culprit.yaml declares, which Q35's criteria
	// are stated against (Q37 moved them from 20 and 30 ms).
	productsStatementBudgetMs = 10.0
	productsRouteBudgetMs     = 25.0
	// The bundle's own copy of the migrations: where extraction reads them.
	bundleMigrations = "/tmp/walk/inventory_service/migrations/versions/"
)

var (
	demoService           = filepath.Join(repoRoot, "demo-services", "inventory_service")
	pythonExtractor       = filepath.Join(repoRoot, "extractors", "python", "culprit_extract_python")
	categoryOnlyMigration = filepath.Join(repoRoot, "demo-services", "faults", "0003_products_category.py")
)

// The demo manifest's extractor command, as committed, and as the walk's
// container runs it: the containers have the demo's Python, with
// culprit-shared installed, but no uv and no clone. Only the command
// changes (Q33 (3)).
const (
	committedExtractCommand = `command: ["uv", "run", "--project", "../../extractors/python", "culprit-extract-python", "--no-import"]`
	containerExtractCommand = `command: ["env", "PYTHONPATH=/tmp/walk/extractors", "python", "-P", "-m", "culprit_extract_python.cli", "--no-import"]`
)

// bundleTree copies what extraction reads into the walk bundle: the
// extractor's package and inventory-service's source at the head, both
// without caches.
func bundleTree(dir string) error {
	if err := copySource(pythonExtractor, filepath.Join(dir, "extractors", "culprit_extract_python")); err != nil {
		return err
	}
	return copySource(demoService, filepath.Join(dir, "inventory_service"))
}

// copySource copies a source directory's Python files and alembic.ini,
// recursively, skipping __pycache__.
func copySource(from, to string) error {
	return filepath.WalkDir(from, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		relative, _ := filepath.Rel(from, path)
		if entry.IsDir() {
			if entry.Name() == "__pycache__" {
				return filepath.SkipDir
			}
			return os.MkdirAll(filepath.Join(to, relative), 0o755)
		}
		if !strings.HasSuffix(path, ".py") && entry.Name() != "alembic.ini" {
			return nil
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		return os.WriteFile(filepath.Join(to, relative), raw, 0o644)
	})
}

// containerManifest is the demo's manifest with the extractor command the
// container can run; it refuses a manifest whose command has changed, so
// the two cannot drift apart unnoticed.
func containerManifest(text string) (string, error) {
	if strings.Count(text, committedExtractCommand) != 1 {
		return "", fmt.Errorf("the demo's culprit.yaml no longer holds the extractor command %s once", committedExtractCommand)
	}
	return strings.Replace(text, committedExtractCommand, containerExtractCommand, 1), nil
}

// copyBundle puts the walk bundle in a container, with the tree as the
// fault left it.
func (s *faultStack) copyBundle(container string) {
	s.t.Helper()
	s.docker(nil, "cp", s.walkIn, container+":/tmp/walk")
	switch s.tree {
	case treeFault:
		s.docker(nil, "exec", "-u", "0", container, "rm", bundleMigrations+demoHeadMigration)
	case treeCategoryOnly:
		s.docker(nil, "exec", "-u", "0", container, "rm", bundleMigrations+demoHeadMigration)
		s.docker(nil, "cp", categoryOnlyMigration, container+":"+bundleMigrations)
	}
	s.docker(nil, "exec", "-u", "0", container, "chmod", "-R", "a+rX", "/tmp/walk")
	s.docker(nil, "exec", "-u", "0", container, "chmod", "755", "/tmp/walk/culprit")
}

// alembic moves inventory-service's database, as its owner, from inside
// inventory-service: upgrade or downgrade to a revision.
func (s *faultStack) alembic(direction, revision string) {
	s.t.Helper()
	script := "import sys\nfrom alembic import command\nfrom alembic.config import Config\n" +
		"getattr(command, sys.argv[1])(Config('/app/inventory_service/alembic.ini'), sys.argv[2])"
	s.docker(nil, "exec", s.container("inventory-service"), "python", "-c", script, direction, revision)
}

// databaseRevision is the revision inventory-service's database is at.
func (s *faultStack) databaseRevision() string {
	s.t.Helper()
	return strings.TrimSpace(s.docker(nil, "exec", s.container("postgres"),
		"psql", "-U", "postgres", "-d", "inventory", "-Atc", "SELECT version_num FROM alembic_version"))
}

// restoreDatabase puts the database and the tree back at the head: the
// database fault's undo, and its known fix.
func (s *faultStack) restoreDatabase() {
	s.t.Helper()
	if s.databaseRevision() == categoryOnlyRevision {
		s.alembic("downgrade", "-1")
	}
	s.alembic("upgrade", demoHeadRevision)
	if got := s.databaseRevision(); got != demoHeadRevision {
		s.t.Fatalf("inventory-service's database is at %s after the fix, want %s", got, demoHeadRevision)
	}
	s.tree = treeHead
}

// listProducts sends a bare GET /products from inside inventory-service and
// returns the status.
func (s *faultStack) listProducts() int {
	s.t.Helper()
	script := "import urllib.request\nprint(urllib.request.urlopen('http://localhost:8002/products',timeout=15).status)"
	output := strings.TrimSpace(s.docker(nil, "exec", s.container("inventory-service"), "python", "-c", script))
	var status int
	if _, err := fmt.Sscanf(output, "%d", &status); err != nil {
		s.t.Fatalf("listing products printed %q", output)
	}
	return status
}

// checkRouteP95 holds the list route's p95, from the latency reading's own
// samples, to factor times its budget: ">=" at the fault, "<=" when fixed.
func (s *faultStack) checkRouteP95(reading model.Reading, op string, factor float64) {
	s.t.Helper()
	raw, _ := reading.Measured["samples_us"].([]any)
	var samples []float64
	for _, each := range raw {
		if value, ok := each.(float64); ok {
			samples = append(samples, value/1000)
		}
	}
	if len(samples) == 0 {
		s.t.Errorf("the latency reading holds no samples: %v", reading.Measured)
		return
	}
	sort.Float64s(samples)
	p95 := samples[int(math.Ceil(0.95*float64(len(samples))))-1]
	bound := factor * productsRouteBudgetMs
	s.t.Logf("GET /products p95 %.1f ms over %d samples (budget %.0f ms; want %s %.1f)",
		p95, len(samples), productsRouteBudgetMs, op, bound)
	if (op == ">=" && p95 < bound) || (op == "<=" && p95 > bound) {
		s.t.Errorf("GET /products p95 %.1f ms, want %s %.1f ms", p95, op, bound)
	}
}

// checkStatementMean holds the products statement's mean, in every
// statement reading given, to a bound in milliseconds.
func (s *faultStack) checkStatementMean(readings []model.Reading, op string, bound float64) {
	s.t.Helper()
	seen := 0
	for _, reading := range readings {
		if reading.ProbeID != model.StatementProbeID {
			continue
		}
		statements, _ := reading.Measured["statements"].([]any)
		for _, item := range statements {
			statement, _ := item.(map[string]any)
			if statement["budget_on"] != "public.products" {
				continue
			}
			calls, total := wholeNumber(statement["calls"]), wholeNumber(statement["total_us"])
			if calls == 0 {
				continue
			}
			seen++
			mean := total / calls / 1000
			s.t.Logf("the products statement: mean %.3f ms over %.0f calls in %s (want %s %.1f)",
				mean, calls, reading.ProbeID, op, bound)
			if (op == ">=" && mean < bound) || (op == ">" && mean <= bound) || (op == "<" && mean >= bound) {
				s.t.Errorf("the products statement's mean is %.3f ms in %s, want %s %.1f ms", mean, reading.ProbeID, op, bound)
			}
		}
	}
	if seen == 0 {
		s.t.Errorf("no statement reading timed the products statement")
	}
}

func wholeNumber(value any) float64 {
	number, _ := value.(float64)
	return number
}

// rerunReadings are every reading verification took, both runs of each.
func rerunReadings(verification model.Verification) []model.Reading {
	var readings []model.Reading
	for _, rerun := range verification.Reran {
		readings = append(readings, rerun.Runs[0], rerun.Runs[1])
	}
	return readings
}

// checkPlanFiltersOnSkuIndex: with an index on category alone, every plan
// reading still walks ix_products_sku and filters category row by row.
func (s *faultStack) checkPlanFiltersOnSkuIndex(readings []model.Reading) {
	s.t.Helper()
	plans := 0
	for _, reading := range readings {
		if reading.ProbeID != model.PlanProbeID {
			continue
		}
		plans++
		nodes, _ := reading.Measured["nodes"].([]any)
		found := false
		for _, item := range nodes {
			node, _ := item.(map[string]any)
			filtered, _ := node["filter_columns"].([]any)
			found = found || (node["index"] == "ix_products_sku" && slices.Contains(filtered, any("category")))
		}
		if !found {
			s.t.Errorf("a plan reading on %s does not filter category on ix_products_sku: %v", reading.Target, nodes)
		}
	}
	if plans == 0 {
		s.t.Errorf("verification took no plan reading")
	}
}

// investigationReadings are the readings an investigation recorded.
func investigationReadings(inv model.Investigation) []model.Reading {
	readings := make([]model.Reading, 0, len(inv.Readings))
	for _, recorded := range inv.Readings {
		readings = append(readings, recorded.Reading)
	}
	return readings
}
