package probe

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The database probes.
//
// Both run under `db.metadata.read`, and the DatabaseInspector interface
// has no method that can return a row. "Schema, constraints, migration
// version, NOT rows" is §2.7's wording for the capability, and the way to
// keep a promise like that is to make the other thing unsayable.

// --- probe.db.connect --------------------------------------------------

type dbConnect struct{}

func (dbConnect) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID:            "probe.db.connect",
		Discriminates: []string{model.HypothesisDatabaseUnreachable},
		// Version 2 (Phase 31.1): no `dsn` input. Which database is named
		// by the target; how to reach it is culprit.yaml's `dsn_env`, read
		// by the data source. See DatabaseInspector.
		Version:      2,
		Effect:       model.EffectInspect,
		Capabilities: []string{"db.metadata.read"},
		TimeoutMS:    10_000,
		ExpectedFrom: model.PlaneConfigured,
		Produces: []model.Produces{
			{SubjectTemplate: "connection:{from}->{to}", Predicate: "database_connects"},
		},
		Cost:   model.CostCheap,
		Inputs: map[string]any{"type": "object", "properties": map[string]any{}},
	}
}

func (dbConnect) Run(ctx context.Context, request Request, deps Deps) Outcome {
	if deps.Database == nil {
		return inconclusive("no database client is available to this agent")
	}
	database := databaseOf(request.Target)

	// Never in `measured`, the reason or evidence: anything about how the
	// database was reached. Only whether it was.
	if err := deps.Database.Connect(ctx, database); err != nil {
		if outcome, decided := sourceOutcome(err); decided {
			return outcome
		}
		return fail(map[string]any{"database": database, "connected": false}, fmt.Sprintf(
			"%s did not accept a read-only connection: %s",
			database, model.RedactCredentials(err.Error())))
	}
	return pass(map[string]any{"database": database, "connected": true})
}

// --- probe.db.schema_conformance ---------------------------------------

type dbSchemaConformance struct{}

func (dbSchemaConformance) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID: "probe.db.schema_conformance",
		// Version 2 (Phase 31.1): no `dsn` input, the table may be named
		// by a schema: target, and the expected columns come from the
		// declaring facts (the migrations, the ORM) when no expect_columns
		// is given.
		Version:      2,
		Effect:       model.EffectInspect,
		Capabilities: []string{"db.metadata.read"},
		TimeoutMS:    15_000,
		ExpectedFrom: model.PlaneIntent,
		Produces: []model.Produces{
			{SubjectTemplate: "schema:{database}/{schema}.{table}", Predicate: model.PredicateColumns},
		},
		Cost: model.CostCheap,
		Inputs: map[string]any{
			"type": "object",
			"properties": map[string]any{
				"schema": map[string]any{"type": "string"},
				"table":  map[string]any{"type": "string"},
				"expect_columns": map[string]any{
					"type": "array", "items": map[string]any{"type": "string"},
				},
			},
		},
	}
}

func (dbSchemaConformance) Run(ctx context.Context, request Request, deps Deps) Outcome {
	database := databaseOf(request.Target)
	schema, table := "public", ""
	if kind, parts, err := model.ParseSubject(request.Target); err == nil && kind == model.KindSchema {
		schema, table = parts["namespace"], parts["table"]
	}
	if named, ok := stringInput(request.Inputs, "table"); ok {
		table = named
	}
	if named, ok := stringInput(request.Inputs, "schema"); ok {
		schema = named
	}
	if table == "" {
		return inconclusive("no table was named: give a schema: target or pass --input table=")
	}
	if deps.Database == nil {
		return inconclusive("no database client is available to this agent")
	}

	columns, err := deps.Database.Columns(ctx, database, schema, table)
	if err != nil {
		if outcome, decided := sourceOutcome(err); decided {
			return outcome
		}
		return inconclusive(fmt.Sprintf(
			"the live columns of %s.%s could not be read: %s",
			schema, table, model.RedactCredentials(err.Error())))
	}

	names := make([]string, 0, len(columns))
	present := map[string]bool{}
	for _, column := range columns {
		present[column.Name] = true
		names = append(names, column.Name)
	}
	sort.Strings(names)
	measured := map[string]any{"table": schema + "." + table, "columns": names}

	// As for dep.version: an explicit expect_columns is the caller's own
	// question, and then no declaration is cited.
	wanted, explicit := stringsInput(request.Inputs, "expect_columns")
	var source *model.Provenance
	if !explicit && request.Expectation != nil {
		wanted, explicit = stringsOf(request.Expectation.Value)
		source = provenanceOf(request.Expectation)
	}
	if !explicit || len(wanted) == 0 {
		return withoutExpectation(request, measured,
			fmt.Sprintf("%s.%s has %d live column(s)", schema, table, len(names)))
	}
	expected := map[string]any{"columns": wanted}

	if len(columns) == 0 {
		return Outcome{
			Verdict: model.VerdictFail, Measured: measured, Expected: expected,
			ExpectedSource: source,
			Reason:         fmt.Sprintf("%s.%s does not exist in the running database", schema, table),
		}
	}
	var missing []string
	for _, column := range wanted {
		if !present[column] {
			missing = append(missing, column)
		}
	}
	sort.Strings(missing)
	if len(missing) > 0 {
		return Outcome{
			Verdict: model.VerdictFail, Measured: measured, Expected: expected,
			ExpectedSource: source,
			Reason: fmt.Sprintf(
				"%s.%s is missing column(s) the code maps: %s",
				schema, table, strings.Join(missing, ", ")),
		}
	}
	return Outcome{Verdict: model.VerdictPass, Measured: measured, Expected: expected,
		ExpectedSource: source}
}

// databaseOf is the database a target names: the database of a schema:
// subject, the far end of a connection, or a component.
func databaseOf(target string) string {
	return calleeOfTarget(target)
}

// stringsOf reads a fact's list-of-strings value.
func stringsOf(value any) ([]string, bool) {
	switch list := value.(type) {
	case []string:
		return list, true
	case []any:
		out := make([]string, 0, len(list))
		for _, item := range list {
			text, ok := item.(string)
			if !ok {
				return nil, false
			}
			out = append(out, text)
		}
		return out, true
	}
	return nil, false
}
