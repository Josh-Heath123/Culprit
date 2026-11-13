package capture

import "github.com/josh-heath123/culprit/cli/internal/capture/dbsession"

// The database session lives in internal/capture/dbsession, a package of
// its own (Q27): no file here can reach its connection, its statements or
// send. These names are that package's, kept so capture and the probes read
// as before.

type (
	// TableShape is one table as the live database reports it.
	TableShape = dbsession.TableShape
	// Schema is everything the metadata statements return.
	Schema = dbsession.Schema
	// MetadataReader reads a database's schema.
	MetadataReader = dbsession.MetadataReader
	// DBErrorKind classifies a database failure.
	DBErrorKind = dbsession.DBErrorKind
	// DBError is a database failure reduced to its kind.
	DBError = dbsession.DBError
	// PostgresReader is the read-only, template-only Postgres reader.
	PostgresReader = dbsession.PostgresReader
	// StatsReader reads statement statistics and generic plans (Phase 37
	// part 2), each in one read-only session.
	StatsReader = dbsession.StatsReader
	// StatementStats is one statement's change over a window.
	StatementStats = dbsession.StatementStats
	// StatementWindow is what a window of two snapshots gives.
	StatementWindow = dbsession.StatementWindow
	// StatementPlan is one statement's generic plan.
	StatementPlan = dbsession.StatementPlan
)

// The closed set of database failures.
const (
	DBUnreachable  = dbsession.DBUnreachable
	DBAuthFailed   = dbsession.DBAuthFailed
	DBNoSuchDB     = dbsession.DBNoSuchDB
	DBNoPermission = dbsession.DBNoPermission
	DBTimedOut     = dbsession.DBTimedOut
	DBBadDSN       = dbsession.DBBadDSN
	DBOtherFailure = dbsession.DBOtherFailure
)

// StatementWindowLength is the fixed window between a statement probe's two
// snapshots, and MinimumPlanVersion the first PostgreSQL with generic plans
// (Phase 37 part 2).
const (
	StatementWindowLength = dbsession.StatementWindowLength
	MinimumPlanVersion    = dbsession.MinimumPlanVersion
)
