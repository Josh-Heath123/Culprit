package probe

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/capability"
	"github.com/josh-heath123/culprit/cli/internal/capture"
	"github.com/josh-heath123/culprit/cli/internal/extract"
)

// The data sources are thin, but each is a place a grant could be
// skipped or a value could leak, so each is tested against a fake behind
// the real capture interfaces.

type fakeRunner struct {
	output []byte
	err    error
	calls  int
}

func (f *fakeRunner) Run(context.Context, []string) ([]byte, error) {
	f.calls++
	return f.output, f.err
}

type fakeReader struct {
	schema capture.Schema
	err    error
	dsns   []string
}

func (f *fakeReader) Read(_ context.Context, dsn string) (capture.Schema, error) {
	f.dsns = append(f.dsns, dsn)
	return f.schema, f.err
}

func grantsOf(t *testing.T, raw map[string]capability.Raw) capability.Grants {
	t.Helper()
	grants, err := capability.Parse(raw)
	if err != nil {
		t.Fatalf("grants: %v", err)
	}
	return grants
}

func TestTheConfigSourceAnswersPresenceThroughTheAdapter(t *testing.T) {
	sources := &Sources{
		Environment: "local",
		Spec: extract.EnvironmentSpec{
			Adapter:    extract.AdapterProcess,
			Components: map[string]extract.EnvironmentComponent{"orders": {}},
		},
		Ledger:  capability.NewLedger(grantsOf(t, nil)),
		Environ: func() []string { return []string{"JWT_SECRET_KEY=not-for-a-reading"} },
	}
	config := sources.Config()

	for key, want := range map[string]bool{"JWT_SECRET_KEY": true, "MISSING_KEY": false} {
		present, err := config.Present(context.Background(), "orders", key)
		if err != nil || present != want {
			t.Errorf("%s: present=%v err=%v, want %v", key, present, err, want)
		}
	}

	_, err := config.Present(context.Background(), "payments", "JWT_SECRET_KEY")
	var unavailable *UnavailableError
	if !errors.As(err, &unavailable) {
		t.Errorf("a component the environment does not declare: err = %v, want UnavailableError", err)
	}
}

func TestThePackageSourceRunsOnlyAnAllowlistedCommand(t *testing.T) {
	spec := extract.EnvironmentSpec{
		Adapter: extract.AdapterProcess,
		Exec:    map[string][]string{"pip-freeze": {"pip", "freeze"}},
		Components: map[string]extract.EnvironmentComponent{
			"orders": {Packages: "pip-freeze"},
		},
	}

	// Granted: the command runs once, however many packages are asked about.
	runner := &fakeRunner{output: []byte("Stripe==7.1.0\nfastapi==0.115.4\n")}
	sources := &Sources{
		Environment: "local", Spec: spec, Runner: runner,
		Grants: grantsOf(t, map[string]capability.Raw{
			"process.exec.allowlist": {Items: []string{"pip-freeze"}},
		}),
	}
	sources.Ledger = capability.NewLedger(sources.Grants)
	packages := sources.Packages()
	version, found, err := packages.Version(context.Background(), "orders", "stripe")
	if err != nil || !found || version != "7.1.0" {
		t.Errorf("stripe: %q found=%v err=%v", version, found, err)
	}
	if _, _, err := packages.Version(context.Background(), "orders", "fastapi"); err != nil {
		t.Errorf("fastapi: %v", err)
	}
	if runner.calls != 1 {
		t.Errorf("the packages command ran %d times, want 1", runner.calls)
	}

	// Not granted: refused, recorded, and nothing was run.
	runner = &fakeRunner{output: []byte("stripe==7.1.0\n")}
	ungranted := &Sources{Environment: "local", Spec: spec, Runner: runner, Grants: grantsOf(t, nil)}
	ungranted.Ledger = capability.NewLedger(ungranted.Grants)
	_, _, err = ungranted.Packages().Version(context.Background(), "orders", "stripe")
	var refused *RefusedError
	if !errors.As(err, &refused) {
		t.Fatalf("err = %v, want RefusedError", err)
	}
	if runner.calls != 0 {
		t.Error("an ungranted command was run")
	}
	if len(ungranted.Ledger.Refusals()) == 0 {
		t.Error("the refusal was not recorded on the ledger, so no report would show it")
	}
}

func TestTheDatabaseSourceReadsTheDSNByNameAndReturnsOnlyColumns(t *testing.T) {
	const dsn = "postgresql://reader:hunter2@db.internal/orders"
	reader := &fakeReader{schema: capture.Schema{Tables: []capture.TableShape{
		{Namespace: "public", Table: "orders", Columns: map[string]bool{"id": false, "total_cents": true}},
	}}}
	environment := map[string]string{"ORDERS_DSN": dsn}
	sources := &Sources{
		Environment: "local",
		Spec: extract.EnvironmentSpec{Components: map[string]extract.EnvironmentComponent{
			"orders": {Database: &extract.DatabaseSpec{DSNEnv: "ORDERS_DSN", Name: "orders-db"}},
		}},
		Reader: reader,
		LookupEnv: func(name string) (string, bool) {
			value, ok := environment[name]
			return value, ok
		},
	}
	database := sources.Database()

	// By database name and by component name, the same database.
	for _, name := range []string{"orders-db", "orders"} {
		columns, err := database.Columns(context.Background(), name, "public", "orders")
		if err != nil || len(columns) != 2 || columns[0].Name != "id" {
			t.Errorf("%s: columns=%v err=%v", name, columns, err)
		}
	}
	if len(reader.dsns) == 0 || reader.dsns[0] != dsn {
		t.Fatalf("the reader was not handed the DSN culprit.yaml names: %v", reader.dsns)
	}
	missing, err := database.Columns(context.Background(), "orders-db", "public", "nope")
	if err != nil || len(missing) != 0 {
		t.Errorf("a table that does not exist: columns=%v err=%v, want empty", missing, err)
	}

	var unavailable *UnavailableError
	if err := database.Connect(context.Background(), "payments-db"); !errors.As(err, &unavailable) {
		t.Errorf("an undeclared database: err = %v, want UnavailableError", err)
	}
	delete(environment, "ORDERS_DSN")
	// A new inspector, so nothing cached from the reads above.
	if err := sources.Database().Connect(context.Background(), "orders-db"); !errors.As(err, &unavailable) ||
		unavailable.Reason == "" {
		t.Errorf("an unset dsn_env: err = %v, want UnavailableError naming the variable", err)
	}
}

// TestASourceNeverRendersAnErrorItDoesNotRecognise: Runner and Reader are
// injectable, so a future implementation could return free text — a
// driver message quoting its DSN, a command's stderr. The sources render
// errors under capture's closure, which turns anything that is not one of
// its closed kinds into a fixed phrase.
func TestASourceNeverRendersAnErrorItDoesNotRecognise(t *testing.T) {
	const leak = "dial postgresql://reader:hunter2@db.internal/orders: refused"
	sources := &Sources{
		Environment: "local",
		Spec: extract.EnvironmentSpec{
			Exec: map[string][]string{"pip-freeze": {"pip", "freeze"}},
			Components: map[string]extract.EnvironmentComponent{"orders": {
				Packages: "pip-freeze",
				Database: &extract.DatabaseSpec{DSNEnv: "ORDERS_DSN"},
			}},
		},
		Grants: grantsOf(t, map[string]capability.Raw{
			"process.exec.allowlist": {Items: []string{"pip-freeze"}},
		}),
		Runner:    &fakeRunner{err: errors.New(leak)},
		Reader:    &fakeReader{err: errors.New(leak)},
		LookupEnv: func(string) (string, bool) { return "postgresql://reader:hunter2@db.internal/orders", true },
	}
	sources.Ledger = capability.NewLedger(sources.Grants)

	_, _, packagesErr := sources.Packages().Version(context.Background(), "orders", "stripe")
	databaseErr := sources.Database().Connect(context.Background(), "orders")
	for name, err := range map[string]error{"packages": packagesErr, "database": databaseErr} {
		if err == nil {
			t.Fatalf("%s: the failing fake did not fail", name)
		}
		if strings.Contains(err.Error(), "hunter2") || strings.Contains(err.Error(), "postgresql://") {
			t.Errorf("%s source rendered an unrecognised error verbatim: %q", name, err)
		}
	}
}
