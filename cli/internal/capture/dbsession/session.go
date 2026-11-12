// Package dbsession is the one place the binary opens a database
// connection and sends it a statement, and the only package that can (Q27,
// ruled 2026-11-12, docs/PERFORMANCE_PLAN.md end of Phase 37).
//
// Phase 37 part 1 held this with "one file imports pgx"; the phase-auditor
// showed the unit was wrong: Go's visibility is per package, so another
// file in internal/capture took the session this file opened and sent it
// EXPLAIN ANALYZE, with no import. So the session is a package of its own,
// with this one non-test file (TestThisPackageHasOneFile), whose exported
// surface names no pgx or net type (TestTheExportedSurfaceNamesNoDriverType):
// a caller gets PostgresReader.Read and the schema it returns, and nothing
// it could send a statement through.
package dbsession

import (
	"context"
	"errors"
	"net"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

// Live DDL via metadata queries (field 4), under `db.metadata.read`.
//
// # Metadata, never rows
//
// §0.4: "Schema, constraints, indexes, migration version, connection
// counts, lock waits — yes. Row contents — no, by default and by
// capability." Three queries run here and they are the whole list:
//
//  1. `information_schema.columns` — which tables have which columns,
//     and whether each is nullable.
//  2. `to_regclass('public.alembic_version')` — whether the migration
//     version table exists at all.
//  3. `SELECT version_num FROM alembic_version` — the migration version.
//
// The third reads a row, and it is the one row §0.4 names as metadata by
// name ("migration version"). Nothing else does. The session is opened
// read-only (`default_transaction_read_only`), so even a query that
// somehow tried to write would be refused by Postgres, not by a promise
// in this comment; and it carries a statement timeout, so a lock wait on
// a busy production database cannot hang the capture.
//
// # What is deliberately not compared
//
// `information_schema.columns.data_type` is not captured. It says
// `character varying` where SQLAlchemy says `VARCHAR(255)`, and there is
// no mapping between the two worth trusting: every column would be a
// type "disagreement" between the planes and none of them would be real.
// Columns and nullability are compared; types are a recorded limit.

// TableShape is one table as the live database reports it.
type TableShape struct {
	Namespace string
	Table     string
	Columns   map[string]bool // column -> nullable
	// Leading are the columns that lead a valid, non-partial index on the
	// table (Phase 37 part 1).
	Leading map[string]bool
}

// Schema is everything the metadata queries return.
type Schema struct {
	Tables []TableShape
	// MigrationHeads is the alembic version, or nil when there is no
	// alembic_version table — a database that has never been migrated by
	// Alembic, which is a different answer from "at no revision".
	MigrationHeads []string
	HasAlembic     bool
	// VersionUnreadable is set when alembic_version exists but could not
	// be read — the role lacks SELECT on it. The tables are still whole.
	VersionUnreadable DBErrorKind
}

// MetadataReader reads a database's schema. An interface so capture can
// be tested without a database; PostgresReader is the real one.
type MetadataReader interface {
	Read(ctx context.Context, dsn string) (Schema, error)
}

// DBErrorKind classifies a database failure. A closed set, for the same
// reason RunErrorKind is: a pgx error message carries the host, the user
// and the database name, and a connection string is precisely the thing
// that must never reach a report.
type DBErrorKind string

const (
	DBUnreachable  DBErrorKind = "the database could not be reached"
	DBAuthFailed   DBErrorKind = "the database refused the credentials"
	DBNoSuchDB     DBErrorKind = "the named database does not exist"
	DBNoPermission DBErrorKind = "the role lacks permission to read the schema"
	DBTimedOut     DBErrorKind = "the metadata queries timed out"
	DBBadDSN       DBErrorKind = "the connection string could not be parsed"
	DBOtherFailure DBErrorKind = "the metadata queries failed"
)

// DBError is a database failure reduced to its kind.
type DBError struct{ Kind DBErrorKind }

func (e *DBError) Error() string { return string(e.Kind) }

// PostgresReader is the pgx-backed MetadataReader.
type PostgresReader struct {
	Timeout time.Duration
}

// excludedSchemas are the catalogs and extension internals that are not
// the application's schema. TimescaleDB's appear because this
// repository's own database carries it.
var excludedSchemas = []string{
	"pg_catalog", "information_schema", "pg_toast",
	"_timescaledb_catalog", "_timescaledb_internal", "_timescaledb_config",
	"_timescaledb_cache", "_timescaledb_functions", "timescaledb_information",
	"timescaledb_experimental", "toolkit_experimental",
}

// # The boundary (Phase 37 part 1)
//
// This is the one file in the binary that imports pgx
// (TestOnlyThisFileImportsPgx), so it is the one place a statement can be
// sent to a database. Three layers hold what it sends:
//
//  1. A statement is a value of the unexported type statement, and every
//     value is a constant declared below. Nothing outside this package can
//     make one, and nothing inside builds one from text it was given.
//  2. send is the only function that hands a statement to the driver, and
//     it refuses one that is not a template before anything leaves —
//     an arbitrary statement and an EXPLAIN ANALYZE included. Values travel
//     as bind parameters, never spliced into the text.
//  3. Every session is opened read-only, with a statement timeout, as
//     connection parameters (openSession). Were the first two to fail,
//     Postgres itself refuses a write.

// statement is one statement this binary may send. Its values are the
// constants below and nothing else.
type statement string

const (
	// columnsStatement enumerates every column of every ordinary and
	// partitioned table, from pg_catalog (see Read).
	columnsStatement statement = `
		SELECT n.nspname, c.relname, a.attname, NOT a.attnotnull
		FROM pg_catalog.pg_attribute a
		JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
		JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
		WHERE c.relkind IN ('r', 'p')
		  AND NOT c.relispartition
		  AND a.attnum > 0
		  AND NOT a.attisdropped
		  AND n.nspname <> ALL($1)
		  AND n.nspname NOT LIKE 'pg\_temp%'
		  AND n.nspname NOT LIKE 'pg\_toast%'
		ORDER BY n.nspname, c.relname, a.attnum`
	// alembicExistsStatement asks whether the migration version table
	// exists at all.
	alembicExistsStatement statement = `SELECT to_regclass('public.alembic_version')::text`
	// alembicVersionStatement reads the migration version: the one row
	// §0.4 names as metadata.
	alembicVersionStatement statement = `SELECT version_num FROM public.alembic_version`
	// leadingColumnsStatement lists, for every valid index on an ordinary
	// or partitioned table, the column that leads it (Phase 37 part 1): an
	// index on (a, b) serves a filter on a, not on b. A partial index
	// (indpred) and one led by an expression (indkey[0] = 0) are left out,
	// as the migration reader leaves them out.
	leadingColumnsStatement statement = `
		SELECT DISTINCT n.nspname, c.relname, a.attname
		FROM pg_catalog.pg_index i
		JOIN pg_catalog.pg_class c ON c.oid = i.indrelid
		JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
		JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid AND a.attnum = i.indkey[0]
		WHERE c.relkind IN ('r', 'p')
		  AND NOT c.relispartition
		  AND i.indisvalid
		  AND i.indpred IS NULL
		  AND i.indkey[0] <> 0
		  AND n.nspname <> ALL($1)
		  AND n.nspname NOT LIKE 'pg\_temp%'
		  AND n.nspname NOT LIKE 'pg\_toast%'
		ORDER BY n.nspname, c.relname, a.attname`
)

// isTemplate reports whether s is one of the constants above: a switch,
// not a map, so no other file in the package can add a statement to the
// set at run time (the Phase 37 part 1 audit added one from an init()).
func isTemplate(s statement) bool {
	switch s {
	case columnsStatement, alembicExistsStatement, alembicVersionStatement, leadingColumnsStatement:
		return true
	}
	return false
}

// ErrNotATemplate is send's refusal of a statement outside templates.
var ErrNotATemplate = errors.New("refused before it was sent: not one of the statements this binary may send")

// querier is what send needs of a session; *pgx.Conn is one, and tests
// count what reaches it.
type querier interface {
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
}

// send is the only function that hands a statement to the driver.
func send(ctx context.Context, session querier, s statement, args ...any) (pgx.Rows, error) {
	if !isTemplate(s) {
		return nil, ErrNotATemplate
	}
	return session.Query(ctx, string(s), args...)
}

// openSession connects read-only, with a statement timeout and a name the
// database's own views show, all set as connection parameters so they hold
// for every statement of the session.
func openSession(ctx context.Context, dsn string) (*pgx.Conn, error) {
	config, err := pgx.ParseConfig(withoutDriverSuffix(dsn))
	if err != nil {
		// Never wrapped: pgx's parse error quotes the string it failed on.
		return nil, &DBError{Kind: DBBadDSN}
	}
	config.RuntimeParams["default_transaction_read_only"] = "on"
	config.RuntimeParams["statement_timeout"] = "10000"
	config.RuntimeParams["application_name"] = "culprit-capture"
	conn, err := pgx.ConnectConfig(ctx, config)
	if err != nil {
		return nil, classify(ctx, err)
	}
	return conn, nil
}

// Read connects, reads, and disconnects.
func (r PostgresReader) Read(parent context.Context, dsn string) (Schema, error) {
	timeout := r.Timeout
	if timeout == 0 {
		timeout = 20 * time.Second
	}
	ctx, cancel := context.WithTimeout(parent, timeout)
	defer cancel()

	conn, err := openSession(ctx, dsn)
	if err != nil {
		return Schema{}, err
	}
	defer conn.Close(context.Background())

	schema := Schema{}
	// pg_catalog, not information_schema — and the difference is a false
	// positive, not a style choice. `information_schema.columns` lists
	// only the columns of tables the connecting role holds *some*
	// privilege on, so capturing with a least-privilege role (the right
	// thing to do) would make every table it cannot read look absent from
	// the live database, and each of those would be reported as
	// "production is missing a table the code maps". `pg_attribute`
	// lists every column of every table to any role, which is what a
	// schema enumeration that is then treated as complete has to be.
	//
	// Ordinary and partitioned tables only; partitions themselves are
	// left out, since the code maps the parent.
	rows, err := send(ctx, conn, columnsStatement, excludedSchemas)
	if err != nil {
		return Schema{}, classify(ctx, err)
	}
	byTable := map[[2]string]*TableShape{}
	var order [][2]string
	for rows.Next() {
		var namespace, table, column string
		var nullable bool
		if err := rows.Scan(&namespace, &table, &column, &nullable); err != nil {
			rows.Close()
			return Schema{}, classify(ctx, err)
		}
		key := [2]string{namespace, table}
		shape, ok := byTable[key]
		if !ok {
			shape = &TableShape{Namespace: namespace, Table: table, Columns: map[string]bool{}}
			byTable[key] = shape
			order = append(order, key)
		}
		shape.Columns[column] = nullable
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return Schema{}, classify(ctx, err)
	}

	leading, err := send(ctx, conn, leadingColumnsStatement, excludedSchemas)
	if err != nil {
		return Schema{}, classify(ctx, err)
	}
	for leading.Next() {
		var namespace, table, column string
		if err := leading.Scan(&namespace, &table, &column); err != nil {
			leading.Close()
			return Schema{}, classify(ctx, err)
		}
		if shape, ok := byTable[[2]string{namespace, table}]; ok {
			if shape.Leading == nil {
				shape.Leading = map[string]bool{}
			}
			shape.Leading[column] = true
		}
	}
	leading.Close()
	if err := leading.Err(); err != nil {
		return Schema{}, classify(ctx, err)
	}
	for _, key := range order {
		schema.Tables = append(schema.Tables, *byTable[key])
	}

	var exists *string
	existsRows, err := send(ctx, conn, alembicExistsStatement)
	if err != nil {
		return Schema{}, classify(ctx, err)
	}
	if existsRows.Next() {
		if err := existsRows.Scan(&exists); err != nil {
			existsRows.Close()
			return Schema{}, classify(ctx, err)
		}
	}
	existsRows.Close()
	if err := existsRows.Err(); err != nil {
		return Schema{}, classify(ctx, err)
	}
	if exists != nil {
		schema.HasAlembic = true
		// Reading the version needs SELECT on alembic_version, which the
		// schema enumeration above does not. A role without it still
		// produced a complete, correct table list, so that is kept and
		// only the version is reported as unread.
		unreadable := func(err error) (Schema, error) {
			var dbErr *DBError
			if !errors.As(classify(ctx, err), &dbErr) {
				dbErr = &DBError{Kind: DBOtherFailure}
			}
			schema.VersionUnreadable = dbErr.Kind
			schema.MigrationHeads = nil
			return schema, nil
		}
		versions, err := send(ctx, conn, alembicVersionStatement)
		if err != nil {
			return unreadable(err)
		}
		for versions.Next() {
			var version string
			if err := versions.Scan(&version); err != nil {
				versions.Close()
				return unreadable(err)
			}
			schema.MigrationHeads = append(schema.MigrationHeads, version)
		}
		versions.Close()
		// pgx reports a query's failure — permission denied included —
		// here, after iteration, not from Query(). Found by capturing with
		// a role that lacks SELECT on alembic_version: without this check
		// the loop simply ran zero times and the capture reported the
		// migration head as `[]`, which the comparator would have turned
		// into "production is at no revision at all", ranked
		// breaks_request_path. A silent empty answer is a false finding.
		if err := versions.Err(); err != nil {
			return unreadable(err)
		}
		sort.Strings(schema.MigrationHeads)
		if schema.MigrationHeads == nil {
			schema.MigrationHeads = []string{}
		}
	}
	return schema, nil
}

// withoutDriverSuffix turns SQLAlchemy's `postgresql+asyncpg://` into the
// `postgresql://` libpq and pgx read. A `dsn_env` pointing at an
// application's own DATABASE_URL — the obvious thing to point it at — is
// in SQLAlchemy's spelling as often as not, and refusing it would be a
// papercut with nothing gained.
func withoutDriverSuffix(dsn string) string {
	scheme, rest, found := strings.Cut(dsn, "://")
	if !found {
		return dsn
	}
	if base, _, hasDriver := strings.Cut(scheme, "+"); hasDriver {
		return base + "://" + rest
	}
	return dsn
}

// classify maps any pgx/network error onto a closed kind.
func classify(ctx context.Context, err error) error {
	if ctx.Err() == context.DeadlineExceeded || errors.Is(err, context.DeadlineExceeded) {
		return &DBError{Kind: DBTimedOut}
	}
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) {
		switch pgErr.Code {
		case "28P01", "28000":
			return &DBError{Kind: DBAuthFailed}
		case "3D000":
			return &DBError{Kind: DBNoSuchDB}
		case "42501":
			return &DBError{Kind: DBNoPermission}
		case "57014":
			return &DBError{Kind: DBTimedOut}
		}
		return &DBError{Kind: DBOtherFailure}
	}
	var netErr net.Error
	if errors.As(err, &netErr) {
		if netErr.Timeout() {
			return &DBError{Kind: DBTimedOut}
		}
		return &DBError{Kind: DBUnreachable}
	}
	var connectErr *pgconn.ConnectError
	if errors.As(err, &connectErr) {
		return &DBError{Kind: DBUnreachable}
	}
	return &DBError{Kind: DBOtherFailure}
}
