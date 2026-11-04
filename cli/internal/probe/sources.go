package probe

import (
	"context"
	"errors"
	"fmt"
	"os"
	"sort"
	"strings"
	"sync"

	"github.com/josh-heath123/culprit/cli/internal/capability"
	"github.com/josh-heath123/culprit/cli/internal/capture"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Data sources for the database, config and dependency probes — Phase 31.1.
//
// Phase 31 gave these probes interfaces and fakes and nothing real behind
// them, so from the command line all four returned inconclusive. They are
// built here on the Phase 30 capture machinery rather than beside it:
//
//   - the database through capture.PostgresReader (pgx, a read-only
//     session, pg_catalog) — not a second client;
//   - configuration through the environment's capture adapter (compose,
//     kubernetes, process, exec);
//   - installed packages through the same allowlisted command and parser
//     `culprit env capture` uses.
//
// So a probe and a capture read one environment the same way, and each
// source asks the ledger for exactly what a capture would: the runner has
// already checked the manifest's capability, and a source that runs a
// command also needs that command on `process.exec.allowlist`.
//
// Values never leave this file. The config source answers presence and
// drops the map the adapter returned; the database source returns column
// names; a DSN is looked up by the name culprit.yaml gives and handed
// straight to the reader, whose errors are a closed set of kinds.

// Sources builds the data sources for one declared environment.
type Sources struct {
	Environment string
	Spec        extract.EnvironmentSpec
	ManifestDir string
	Grants      capability.Grants
	Ledger      *capability.Ledger

	Runner    capture.Runner
	Reader    capture.MetadataReader
	LookupEnv func(string) (string, bool)
	Environ   func() []string

	once    sync.Once
	adapter capture.Adapter
	err     error
}

func (s *Sources) withDefaults() {
	if s.Runner == nil {
		s.Runner = capture.ExecRunner{}
	}
	if s.Reader == nil {
		s.Reader = capture.PostgresReader{}
	}
	if s.LookupEnv == nil {
		s.LookupEnv = os.LookupEnv
	}
	if s.Environ == nil {
		s.Environ = os.Environ
	}
}

func (s *Sources) component(name string) (extract.EnvironmentComponent, error) {
	settings, ok := s.Spec.Components[name]
	if !ok {
		return settings, &UnavailableError{Reason: fmt.Sprintf(
			"environment %s declares no component %s, so it cannot be read there",
			s.Environment, name)}
	}
	return settings, nil
}

// requireCommand is the extra grant a source that runs a command needs.
func (s *Sources) requireCommand(command, component, check string) error {
	if !s.Grants.Has(capability.ProcessExecAllowlist) {
		s.Ledger.Require(capability.ProcessExecAllowlist, component, check)
		return &RefusedError{Capability: string(capability.ProcessExecAllowlist), Reason: fmt.Sprintf(
			"reading this runs %s, and process.exec.allowlist is not granted for this environment",
			command)}
	}
	if !s.Ledger.RequireItem(capability.ProcessExecAllowlist, command, component, check) {
		return &RefusedError{Capability: string(capability.ProcessExecAllowlist), Reason: fmt.Sprintf(
			"reading this runs %s, which is not on this environment's process.exec.allowlist",
			command)}
	}
	return nil
}

// workloadOf reads a component's environment through the adapter, once.
// The map it returns holds real values; callers read membership (config)
// or one granted value (secrets), and neither keeps it.
func (s *Sources) workloadOf(ctx context.Context, component string) (capture.Workload, error) {
	settings, err := s.component(component)
	if err != nil {
		return capture.Workload{}, err
	}
	if s.Spec.Adapter == extract.AdapterExec {
		if err := s.requireCommand(settings.EnvCommand, component, "environment"); err != nil {
			return capture.Workload{}, err
		}
	}
	s.once.Do(func() {
		s.adapter, s.err = capture.NewAdapter(s.Spec, s.ManifestDir, s.Runner, s.Environ)
	})
	if s.err != nil {
		return capture.Workload{}, errors.New(capture.SafeReason(s.err))
	}
	workload, err := s.adapter.Workload(ctx, component, settings)
	if err != nil {
		// Rendered under capture's closure: one of its closed kinds, or a
		// fixed phrase. Runner and Reader are injectable, so "the current
		// implementations only return closed kinds" is not a guarantee.
		return capture.Workload{}, fmt.Errorf("the %s adapter could not read %s's environment: %s",
			s.adapter.Name(), component, capture.SafeReason(err))
	}
	return workload, nil
}

// --- a credential's value -----------------------------------------------

// Secrets reads one variable's value under config.read.values for it.
func (s *Sources) Secrets() SecretReader { s.withDefaults(); return secretSource{s} }

type secretSource struct{ s *Sources }

func (c secretSource) Secret(ctx context.Context, component, key string) (string, error) {
	item := component + "/" + key
	check := "the value of " + key
	if !c.s.Grants.Has(capability.ConfigReadValues) {
		c.s.Ledger.Require(capability.ConfigReadValues, component, check)
		return "", &RefusedError{Capability: string(capability.ConfigReadValues), Reason: fmt.Sprintf(
			"reading %s needs config.read.values for %s, and config.read.values is not "+
				"granted for this environment", key, item)}
	}
	if !c.s.Ledger.RequireItem(capability.ConfigReadValues, item, component, check) {
		return "", &RefusedError{Capability: string(capability.ConfigReadValues), Reason: fmt.Sprintf(
			"reading %s needs config.read.values for %s, which is not on this "+
				"environment's allowlist", key, item)}
	}
	workload, err := c.s.workloadOf(ctx, component)
	if err != nil {
		return "", err
	}
	value, present := workload.Env[key]
	if !present {
		return "", &UnavailableError{Reason: fmt.Sprintf("%s is not set for %s", key, component)}
	}
	if !value.Known {
		// Set by reference (a Kubernetes secretKeyRef): the key exists, but
		// this adapter cannot see its value, and an empty string is not it.
		return "", &UnavailableError{Reason: fmt.Sprintf(
			"%s is set by reference for %s, so its value is not visible to this agent", key, component)}
	}
	return value.Value, nil
}

// --- configuration ----------------------------------------------------

// Config answers whether a key is set, through the environment's adapter.
func (s *Sources) Config() ConfigReader { s.withDefaults(); return configSource{s} }

type configSource struct{ s *Sources }

func (c configSource) Present(ctx context.Context, component, key string) (bool, error) {
	workload, err := c.s.workloadOf(ctx, component)
	if err != nil {
		return false, err
	}
	// The map holds real values. Only membership is read, and the map is
	// not kept.
	_, present := workload.Env[key]
	if !present && !workload.Complete {
		return false, &UnavailableError{Reason: fmt.Sprintf(
			"%s is not among the variables read, but %s's environment could not be fully "+
				"enumerated (%s), so its absence is not established",
			key, component, strings.Join(workload.Incomplete, "; "))}
	}
	return present, nil
}

// --- installed packages -----------------------------------------------

// Packages reads installed versions through the component's declared
// packages command.
func (s *Sources) Packages() PackageReader { s.withDefaults(); return &packageSource{s: s} }

type packageSource struct {
	s     *Sources
	mutex sync.Mutex
	read  map[string]map[string]string
}

func (p *packageSource) Version(ctx context.Context, component, name string) (string, bool, error) {
	settings, err := p.s.component(component)
	if err != nil {
		return "", false, err
	}
	if settings.Packages == "" {
		return "", false, &UnavailableError{Reason: fmt.Sprintf(
			"environment %s declares no packages command for %s", p.s.Environment, component)}
	}
	if err := p.s.requireCommand(settings.Packages, component, "packages"); err != nil {
		return "", false, err
	}

	p.mutex.Lock()
	defer p.mutex.Unlock()
	versions, cached := p.read[component]
	if !cached {
		out, err := p.s.Runner.Run(ctx, p.s.Spec.Exec[settings.Packages])
		if err != nil {
			return "", false, fmt.Errorf("%s's installed packages were not read: %s",
				component, capture.SafeReason(err))
		}
		parsed, ok := capture.ParsePackages(out)
		if !ok {
			return "", false, &UnavailableError{Reason: fmt.Sprintf(
				"the output of %s was neither `pip freeze` nor `npm ls --json`", settings.Packages)}
		}
		versions = map[string]string{}
		for installed, version := range parsed {
			versions[model.CanonicalComponent(installed)] = version
		}
		if p.read == nil {
			p.read = map[string]map[string]string{}
		}
		p.read[component] = versions
	}
	version, found := versions[model.CanonicalComponent(name)]
	return version, found, nil
}

// --- database ---------------------------------------------------------

// Database reads schema metadata through capture.PostgresReader.
func (s *Sources) Database() DatabaseInspector { s.withDefaults(); return &databaseSource{s: s} }

type databaseSource struct {
	s     *Sources
	mutex sync.Mutex
	read  map[string]capture.Schema
}

// dsnFor finds the component whose database is `name` — the component
// itself, or the one whose `database.name` it is — and reads the
// variable its `dsn_env` names. The DSN goes no further than the reader.
func (d *databaseSource) dsnFor(name string) (string, error) {
	names := make([]string, 0, len(d.s.Spec.Components))
	for component := range d.s.Spec.Components {
		names = append(names, component)
	}
	sort.Strings(names)
	for _, component := range names {
		settings := d.s.Spec.Components[component]
		if settings.Database == nil {
			continue
		}
		if component != name && settings.Database.DatabaseName(component) != name {
			continue
		}
		dsn, ok := d.s.LookupEnv(settings.Database.DSNEnv)
		if !ok || strings.TrimSpace(dsn) == "" {
			return "", &UnavailableError{Reason: fmt.Sprintf(
				"%s is not set in the environment culprit is running in, so %s cannot be reached",
				settings.Database.DSNEnv, name)}
		}
		return dsn, nil
	}
	return "", &UnavailableError{Reason: fmt.Sprintf(
		"environment %s declares no database %s (a component's database: dsn_env)",
		d.s.Environment, name)}
}

func (d *databaseSource) schema(ctx context.Context, name string) (capture.Schema, error) {
	d.mutex.Lock()
	defer d.mutex.Unlock()
	if schema, ok := d.read[name]; ok {
		return schema, nil
	}
	dsn, err := d.dsnFor(name)
	if err != nil {
		return capture.Schema{}, err
	}
	schema, err := d.s.Reader.Read(ctx, dsn)
	if err != nil {
		// Never the reader's error text alongside the DSN: PostgresReader
		// returns a closed kind (capture.DBError) for exactly this reason,
		// and a timeout is a measurement that did not complete.
		var dbErr *capture.DBError
		if errors.As(err, &dbErr) && dbErr.Kind == capture.DBTimedOut {
			return capture.Schema{}, &UnavailableError{Reason: string(dbErr.Kind)}
		}
		return capture.Schema{}, errors.New(capture.SafeReason(err))
	}
	if d.read == nil {
		d.read = map[string]capture.Schema{}
	}
	d.read[name] = schema
	return schema, nil
}

func (d *databaseSource) Connect(ctx context.Context, name string) error {
	_, err := d.schema(ctx, name)
	return err
}

func (d *databaseSource) Columns(
	ctx context.Context, name, namespace, table string,
) ([]TableColumn, error) {
	schema, err := d.schema(ctx, name)
	if err != nil {
		return nil, err
	}
	for _, shape := range schema.Tables {
		if shape.Namespace != namespace || shape.Table != table {
			continue
		}
		columns := make([]TableColumn, 0, len(shape.Columns))
		for column, nullable := range shape.Columns {
			columns = append(columns, TableColumn{Name: column, Nullable: nullable})
		}
		sort.Slice(columns, func(i, j int) bool { return columns[i].Name < columns[j].Name })
		return columns, nil
	}
	return []TableColumn{}, nil
}
