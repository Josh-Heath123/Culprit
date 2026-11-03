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
		ID:           "probe.db.connect",
		Version:      1,
		Effect:       model.EffectInspect,
		Capabilities: []string{"db.metadata.read"},
		TimeoutMS:    10_000,
		ExpectedFrom: model.PlaneConfigured,
		Produces: []model.Produces{
			{SubjectTemplate: "connection:{from}->{to}", Predicate: "database_connects"},
		},
		Cost: model.CostCheap,
		Inputs: map[string]any{
			"type":     "object",
			"required": []any{"dsn"},
			"properties": map[string]any{
				"dsn": map[string]any{"type": "string"},
			},
		},
	}
}

func (dbConnect) Run(ctx context.Context, request Request, deps Deps) Outcome {
	dsn, ok := stringInput(request.Inputs, "dsn")
	if !ok {
		return inconclusive(
			"no connection string was supplied, so the database cannot be reached")
	}
	if deps.Database == nil {
		return inconclusive("no database client is available to this agent")
	}

	// The DSN is a credential. It is never put in `measured`, in the
	// reason, or in evidence — only the fact that a connection was or was
	// not established.
	if err := deps.Database.Connect(ctx, dsn); err != nil {
		return fail(map[string]any{"connected": false}, fmt.Sprintf(
			"the database did not accept a read-only connection: %s",
			model.RedactCredentials(err.Error())))
	}
	return pass(map[string]any{"connected": true})
}

// --- probe.db.schema_conformance ---------------------------------------

type dbSchemaConformance struct{}

func (dbSchemaConformance) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID:           "probe.db.schema_conformance",
		Version:      1,
		Effect:       model.EffectInspect,
		Capabilities: []string{"db.metadata.read"},
		TimeoutMS:    15_000,
		ExpectedFrom: model.PlaneIntent,
		Produces: []model.Produces{
			{SubjectTemplate: "schema:{database}/{schema}.{table}", Predicate: "columns"},
		},
		Cost: model.CostCheap,
		Inputs: map[string]any{
			"type":     "object",
			"required": []any{"dsn", "table", "expect_columns"},
			"properties": map[string]any{
				"dsn":    map[string]any{"type": "string"},
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
	dsn, hasDSN := stringInput(request.Inputs, "dsn")
	table, hasTable := stringInput(request.Inputs, "table")
	wanted, hasColumns := stringsInput(request.Inputs, "expect_columns")
	if !hasDSN || !hasTable {
		return inconclusive("a connection string and a table name are both needed")
	}
	if !hasColumns || len(wanted) == 0 {
		return inconclusive(fmt.Sprintf(
			"no columns are declared for %s, so there is nothing to conform to", table))
	}
	if deps.Database == nil {
		return inconclusive("no database client is available to this agent")
	}
	schema, ok := stringInput(request.Inputs, "schema")
	if !ok {
		schema = "public"
	}

	columns, err := deps.Database.Columns(ctx, dsn, schema, table)
	if err != nil {
		return inconclusive(fmt.Sprintf(
			"the live columns of %s.%s could not be read: %s",
			schema, table, model.RedactCredentials(err.Error())))
	}
	if len(columns) == 0 {
		return fail(
			map[string]any{"table": schema + "." + table, "columns": []string{}},
			fmt.Sprintf("%s.%s does not exist in the running database", schema, table))
	}

	present := map[string]bool{}
	names := make([]string, 0, len(columns))
	for _, column := range columns {
		present[column.Name] = true
		names = append(names, column.Name)
	}
	sort.Strings(names)

	var missing []string
	for _, column := range wanted {
		if !present[column] {
			missing = append(missing, column)
		}
	}
	sort.Strings(missing)

	measured := map[string]any{"table": schema + "." + table, "columns": names}
	expected := map[string]any{"columns": wanted}

	if len(missing) > 0 {
		return Outcome{
			Verdict: model.VerdictFail, Measured: measured, Expected: expected,
			ExpectedSource: provenanceOf(request.Expectation),
			Reason: fmt.Sprintf(
				"%s.%s is missing column(s) the code maps: %s",
				schema, table, strings.Join(missing, ", ")),
		}
	}
	return Outcome{
		Verdict: model.VerdictPass, Measured: measured, Expected: expected,
		ExpectedSource: provenanceOf(request.Expectation),
	}
}
