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
	"fmt"
	"math"
	"net"
	"regexp"
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
// (TestOnlyThisFileImportsPgx), in a package of its own (Q27), so it is the
// one place a statement can be
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

// The statistics templates (Phase 37 part 2), under db.stats.read and
// db.plan.read. Each reads only the connected database's statements
// (`dbid`), never Culprit's own role's (Q29 (3)), and keeps a statement's
// text only when it begins with SELECT, WITH, INSERT, UPDATE, DELETE or
// MERGE — the statements pg_stat_statements normalises, constants replaced
// by $n. Any other text (a utility statement such as CREATE ROLE ...
// PASSWORD '...', stored as written, or one beginning with a comment) is
// NULL before it leaves the server (Q29 (2)). Before PostgreSQL 16 every
// text is NULL (Q32): there a SELECT ... INTO is a utility statement whose
// constants Postgres did not normalise, yet its text begins with SELECT.
const (
	// statsProbeStatement is the server's version and whether this
	// database has pg_stat_statements.
	statsProbeStatement statement = `
		SELECT current_setting('server_version_num')::int,
		       EXISTS (SELECT 1 FROM pg_catalog.pg_extension WHERE extname = 'pg_stat_statements')`
	// statsSnapshotStatement is one snapshot of this database's statements.
	statsSnapshotStatement statement = `
		SELECT s.queryid, sum(s.calls)::bigint, sum(s.total_exec_time)::float8,
		       max(CASE WHEN current_setting('server_version_num')::int >= 160000
		                 AND s.query ~* '^(select|with|insert|update|delete|merge)\M'
		                THEN s.query END)
		FROM pg_stat_statements s
		WHERE s.dbid = (SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database())
		  AND s.userid <> (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = current_user)
		  AND s.queryid IS NOT NULL
		GROUP BY s.queryid`
	// statsInfoStatement is the view's own reset time and eviction count:
	// a change between two snapshots means a delta cannot be trusted.
	statsInfoStatement statement = `SELECT dealloc, stats_reset FROM pg_stat_statements_info`
	// planRowStatement is one statement's text, by queryid, from this
	// database, and only when it is a SELECT or a WITH: the one text that
	// becomes a plannedStatement.
	planRowStatement statement = `
		SELECT max(s.query)
		FROM pg_stat_statements s
		WHERE s.queryid = $1
		  AND s.dbid = (SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database())
		  AND s.userid <> (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = current_user)
		  AND s.query ~* '^(select|with)\M'`
)

// isTemplate reports whether s is one of the constants above: a switch,
// not a map, so no other file in the package can add a statement to the
// set at run time (the Phase 37 part 1 audit added one from an init()).
func isTemplate(s statement) bool {
	switch s {
	case columnsStatement, alembicExistsStatement, alembicVersionStatement, leadingColumnsStatement,
		statsProbeStatement, statsSnapshotStatement, statsInfoStatement, planRowStatement:
		return true
	}
	return false
}

// plannedStatement is the one non-constant text this binary ever sends
// (Phase 37 part 2, "Decisions — where the fields predate the build"): a
// statement read back from pg_stat_statements in the same session, chosen by
// queryid, never by an input. Only planFromRow makes one, from a statistics
// row, and only for a single SELECT or WITH.
type plannedStatement struct{ text string }

// plannable is a SELECT or WITH, from its first character: a leading
// comment, a space or any other statement is not.
var plannable = regexp.MustCompile(`(?i)^(select|with)\b`)

// planFromRow is the only constructor of a plannedStatement.
func planFromRow(text string) (plannedStatement, error) {
	if !plannable.MatchString(text) || strings.Contains(text, ";") {
		return plannedStatement{}, ErrNotPlannable
	}
	return plannedStatement{text: text}, nil
}

// ErrNotAQuery is the refusal of a parsed statement that returns no rows
// (a SELECT ... INTO): nothing is asked of the planner.
var ErrNotAQuery = errors.New(
	"refused after parsing, before planning: the statement returns no rows, so it is not a query")

// ErrNotPlannable is the refusal of a text that is not one SELECT or WITH.
var ErrNotPlannable = errors.New(
	"refused before it was sent: only a single SELECT or WITH read from pg_stat_statements is planned")

// planner is what sendPlan needs of a session; *pgx.Conn is one, and tests
// count what reaches it.
type planner interface {
	querier
	Prepare(ctx context.Context, name, sql string) (*pgconn.StatementDescription, error)
	Deallocate(ctx context.Context, name string) error
}

// planName is the one prepared statement a session ever holds.
const planName = "culprit_plan"

// sendPlan is the other function that hands a statement to the driver,
// and the only one that sends a text that is not a template. It returns
// the planner's generic plan for p and executes nothing:
//
//  1. p's text is parsed as a named prepared statement — a protocol Parse,
//     which carries exactly one statement and runs none;
//  2. EXPLAIN (FORMAT JSON) EXECUTE culprit_plan(NULL, ...) asks for its
//     plan. The session's plan_cache_mode is force_generic_plan
//     (openSession), so the plan is built without the parameters' values:
//     a filter reads `category = $1`, never NULL folded to false. EXPLAIN
//     without ANALYZE runs nothing. The EXECUTE's text is fixed but for the
//     count of NULLs, which is the statement's parameter count;
//  3. the prepared statement is deallocated.
//
// (Phase 37's decisions name EXPLAIN (GENERIC_PLAN, ...) over the extended
// protocol. Over the extended protocol every $n must be bound, and a bound
// value is folded as a constant, so GENERIC_PLAN there plans for NULL: the
// first real-Postgres run showed a one-time filter of false. This is the
// generic plan the decision asks for, every message still extended.)
func sendPlan(ctx context.Context, session planner, p plannedStatement) (string, error) {
	if !plannable.MatchString(p.text) || strings.Contains(p.text, ";") {
		return "", ErrNotPlannable
	}
	description, err := session.Prepare(ctx, planName, p.text)
	if err != nil {
		return "", err
	}
	defer func() { _ = session.Deallocate(context.Background(), planName) }()
	// A query returns rows; the server's own description says whether this
	// one does. SELECT ... INTO begins with SELECT and returns none: it is
	// CREATE TABLE AS, and is not planned (found on PostgreSQL 16, Phase 37
	// part 3). Decided by the server, not by a pattern over the text.
	if len(description.Fields) == 0 {
		return "", ErrNotAQuery
	}
	nulls := make([]string, len(description.ParamOIDs))
	for index := range nulls {
		nulls[index] = "NULL"
	}
	explain := "EXPLAIN (FORMAT JSON) EXECUTE " + planName
	if len(nulls) > 0 {
		explain += "(" + strings.Join(nulls, ", ") + ")"
	}
	rows, err := session.Query(ctx, explain)
	if err != nil {
		return "", err
	}
	defer rows.Close()
	var plan string
	if rows.Next() {
		if err := rows.Scan(&plan); err != nil {
			return "", err
		}
	}
	return plan, rows.Err()
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
	// A prepared statement is planned without its parameters' values
	// (sendPlan). pgx prepares the templates too, under its default
	// statement cache, so they are planned generically as well; that
	// changes how they are planned, never what they read.
	config.RuntimeParams["plan_cache_mode"] = "force_generic_plan"
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

// --- Statements and plans (Phase 37 part 2) ----------------------------

// StatementStats is one normalised statement over a window: the change in
// its call count and in its total execution time, in whole microseconds,
// converted once from pg_stat_statements' milliseconds at reading.
type StatementStats struct {
	QueryID     int64
	Calls       int64
	TotalMicros int64
	// Text is set only when the statement is one Postgres normalises
	// (SELECT, WITH, INSERT, UPDATE, DELETE, MERGE); TextKept says so.
	Text     string
	TextKept bool
	// PlanJSON is the generic plan sendPlan reads (EXPLAIN (FORMAT JSON) of
	// the prepared statement under force_generic_plan), when the
	// window was asked to plan and the statement is a SELECT or a WITH.
	PlanJSON string
}

// StatementWindow is what two snapshots of one session give.
type StatementWindow struct {
	Statements []StatementStats
	// Reset is a reset of the statistics, or an eviction from them,
	// between the two snapshots: no delta of the window can be trusted.
	Reset bool
	// Unavailable says why nothing was measured: no pg_stat_statements in
	// this database, or a server too old for it. Empty when measured.
	Unavailable   string
	ServerVersion int
	// TableColumns are each table's columns, "namespace.table", when the
	// window was planned: how a plan's filter is read without storing it.
	TableColumns map[string][]string
}

// StatementPlan is one statement's generic plan.
type StatementPlan struct {
	PlanJSON      string
	Unavailable   string
	ServerVersion int
	TableColumns  map[string][]string
}

// StatsReader reads statement statistics and plans, each in one
// read-only session. Never a row of an application table, never a reset,
// never EXPLAIN ANALYZE.
type StatsReader struct {
	Timeout time.Duration
	// Span is the time between the two snapshots: 30 seconds, fixed by
	// the plan; settable for tests.
	Span time.Duration
	// Wait waits out the window; nil waits on a timer, cut by ctx.
	Wait func(ctx context.Context, d time.Duration) error
}

// StatementWindowLength is the window, fixed (PERFORMANCE_PLAN.md, Phase 37
// part 2: "not configurable, and the walk's deadline cuts it").
const StatementWindowLength = 30 * time.Second

// MinimumPlanVersion is PostgreSQL 16: the brief's floor for the plan
// probe, set when GENERIC_PLAN was the mechanism and kept as ruled on
// 2026-11-13; force_generic_plan is older, but 16 is what CI holds it to.
const MinimumPlanVersion = 160000

// minimumStatsVersion is PostgreSQL 14, the first with
// pg_stat_statements_info, without which a reset cannot be seen.
const minimumStatsVersion = 140000

type snapshotRow struct {
	calls  int64
	micros int64
	text   *string
}

func readSnapshot(ctx context.Context, conn querier) (map[int64]snapshotRow, error) {
	rows, err := send(ctx, conn, statsSnapshotStatement)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[int64]snapshotRow{}
	for rows.Next() {
		var queryID, calls int64
		var total float64
		var text *string
		if err := rows.Scan(&queryID, &calls, &total, &text); err != nil {
			return nil, err
		}
		// Converted once, here, to whole microseconds (P2: integers from
		// the reading on).
		out[queryID] = snapshotRow{calls: calls, micros: int64(math.Round(total * 1000)), text: text}
	}
	return out, rows.Err()
}

func readInfo(ctx context.Context, conn querier) (int64, time.Time, error) {
	rows, err := send(ctx, conn, statsInfoStatement)
	if err != nil {
		return 0, time.Time{}, err
	}
	defer rows.Close()
	var dealloc int64
	var reset time.Time
	if rows.Next() {
		if err := rows.Scan(&dealloc, &reset); err != nil {
			return 0, time.Time{}, err
		}
	}
	return dealloc, reset, rows.Err()
}

// probeStats reads the server version and whether pg_stat_statements is
// here, and says why not when it cannot be used.
func probeStats(ctx context.Context, conn querier, minimum int) (int, string, error) {
	rows, err := send(ctx, conn, statsProbeStatement)
	if err != nil {
		return 0, "", err
	}
	defer rows.Close()
	var version int
	var present bool
	if rows.Next() {
		if err := rows.Scan(&version, &present); err != nil {
			return 0, "", err
		}
	}
	if err := rows.Err(); err != nil {
		return 0, "", err
	}
	switch {
	case !present:
		return version, "pg_stat_statements is not installed in this database", nil
	case version < minimum:
		return version, fmt.Sprintf("PostgreSQL %d is before %d", version/10000, minimum/10000), nil
	}
	return version, "", nil
}

// unloaded is pg_stat_statements present but not preloaded: its view
// refuses to be read (SQLSTATE 55000).
func unloaded(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "55000"
}

func (r StatsReader) wait(ctx context.Context, d time.Duration) error {
	if r.Wait != nil {
		return r.Wait(ctx, d)
	}
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-timer.C:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (r StatsReader) session(parent context.Context, dsn string, extra time.Duration) (context.Context, context.CancelFunc, *pgx.Conn, error) {
	timeout := r.Timeout
	if timeout == 0 {
		timeout = 20 * time.Second
	}
	ctx, cancel := context.WithTimeout(parent, timeout+extra)
	conn, err := openSession(ctx, dsn)
	if err != nil {
		cancel()
		return nil, nil, nil, err
	}
	return ctx, cancel, conn, nil
}

// Window takes two snapshots of this database's statements, the window
// apart, in one session, and returns each statement's change. With plan,
// it then asks the planner, in the same session, for each kept SELECT or
// WITH's generic plan, and reads the tables' columns.
func (r StatsReader) Window(parent context.Context, dsn string, plan bool) (StatementWindow, error) {
	window := r.Span
	if window == 0 {
		window = StatementWindowLength
	}
	ctx, cancel, conn, err := r.session(parent, dsn, window)
	if err != nil {
		return StatementWindow{}, err
	}
	defer cancel()
	defer conn.Close(context.Background())

	version, missing, err := probeStats(ctx, conn, minimumStatsVersion)
	if err != nil {
		return StatementWindow{}, classify(ctx, err)
	}
	result := StatementWindow{ServerVersion: version, Unavailable: missing}
	if missing != "" {
		return result, nil
	}
	deallocBefore, resetBefore, err := readInfo(ctx, conn)
	if err == nil {
		var before map[int64]snapshotRow
		before, err = readSnapshot(ctx, conn)
		if err == nil {
			if err = r.wait(ctx, window); err == nil {
				var after map[int64]snapshotRow
				after, err = readSnapshot(ctx, conn)
				if err == nil {
					deallocAfter, resetAfter, infoErr := readInfo(ctx, conn)
					err = infoErr
					result.Reset = deallocAfter != deallocBefore || !resetAfter.Equal(resetBefore)
					for queryID, now := range after {
						then := before[queryID]
						calls, micros := now.calls-then.calls, now.micros-then.micros
						if calls < 0 || micros < 0 {
							result.Reset = true
							continue
						}
						if calls == 0 {
							continue
						}
						stats := StatementStats{QueryID: queryID, Calls: calls, TotalMicros: micros}
						if now.text != nil {
							stats.Text, stats.TextKept = *now.text, true
						}
						result.Statements = append(result.Statements, stats)
					}
				}
			}
		}
	}
	if err != nil {
		if unloaded(err) {
			result.Unavailable = "pg_stat_statements is installed but not loaded (shared_preload_libraries)"
			return result, nil
		}
		return StatementWindow{}, classify(ctx, err)
	}
	sort.Slice(result.Statements, func(i, j int) bool {
		a, b := result.Statements[i], result.Statements[j]
		if a.TotalMicros != b.TotalMicros {
			return a.TotalMicros > b.TotalMicros
		}
		return a.QueryID < b.QueryID
	})
	if plan && version >= MinimumPlanVersion {
		for index := range result.Statements {
			if json, err := planOne(ctx, conn, result.Statements[index].QueryID); err == nil {
				result.Statements[index].PlanJSON = json
			}
		}
		if result.TableColumns, err = tableColumns(ctx, conn); err != nil {
			return StatementWindow{}, classify(ctx, err)
		}
	}
	return result, nil
}

// planOne reads one statement by queryid, in this session, and plans it.
func planOne(ctx context.Context, conn planner, queryID int64) (string, error) {
	rows, err := send(ctx, conn, planRowStatement, queryID)
	if err != nil {
		return "", err
	}
	var text *string
	if rows.Next() {
		err = rows.Scan(&text)
	}
	rows.Close()
	if err == nil {
		err = rows.Err()
	}
	if err != nil {
		return "", err
	}
	if text == nil {
		return "", ErrNotPlannable
	}
	planned, err := planFromRow(*text)
	if err != nil {
		return "", err
	}
	return sendPlan(ctx, conn, planned)
}

func tableColumns(ctx context.Context, conn querier) (map[string][]string, error) {
	rows, err := send(ctx, conn, columnsStatement, excludedSchemas)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[string][]string{}
	for rows.Next() {
		var namespace, table, column string
		var nullable bool
		if err := rows.Scan(&namespace, &table, &column, &nullable); err != nil {
			return nil, err
		}
		key := namespace + "." + table
		out[key] = append(out[key], column)
	}
	return out, rows.Err()
}

// Plan reads the statement queryID names from this database's statistics,
// in one session, and returns its generic plan. Before PostgreSQL 16, or
// without pg_stat_statements, Unavailable says why.
func (r StatsReader) Plan(parent context.Context, dsn string, queryID int64) (StatementPlan, error) {
	ctx, cancel, conn, err := r.session(parent, dsn, 0)
	if err != nil {
		return StatementPlan{}, err
	}
	defer cancel()
	defer conn.Close(context.Background())
	version, missing, err := probeStats(ctx, conn, MinimumPlanVersion)
	if err != nil {
		return StatementPlan{}, classify(ctx, err)
	}
	result := StatementPlan{ServerVersion: version, Unavailable: missing}
	if missing != "" {
		return result, nil
	}
	plan, err := planOne(ctx, conn, queryID)
	switch {
	case errors.Is(err, ErrNotPlannable):
		result.Unavailable = "no SELECT or WITH with that queryid in this database's statistics"
		return result, nil
	case errors.Is(err, ErrNotAQuery):
		result.Unavailable = "the statement with that queryid returns no rows (a SELECT ... INTO), so it is not planned"
		return result, nil
	case err != nil && unloaded(err):
		result.Unavailable = "pg_stat_statements is installed but not loaded (shared_preload_libraries)"
		return result, nil
	case err != nil:
		return StatementPlan{}, classify(ctx, err)
	}
	result.PlanJSON = plan
	if result.TableColumns, err = tableColumns(ctx, conn); err != nil {
		return StatementPlan{}, classify(ctx, err)
	}
	return result, nil
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
