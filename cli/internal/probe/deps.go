package probe

import (
	"context"
	"errors"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Deps is every way a probe can touch the outside world.
//
// One struct of narrow interfaces rather than probes reaching for the
// standard library directly, for three reasons that all matter here:
//
//  1. Field 13 requires a pass, a fail *and* an inconclusive fixture for
//     every probe. Two of those three are hard to arrange against real
//     infrastructure and trivial against a fake.
//  2. It keeps the socket-opening code in one place per protocol, so
//     "what can this binary actually talk to" is answerable by reading
//     this file rather than grepping thirteen probes.
//  3. A probe that needs something not on this struct is a probe that
//     needs a new capability, which is a deliberate decision rather than
//     an import.
//
// A nil member is not a crash: the probe that needs it returns
// inconclusive with a reason. A `culprit` invoked without database access
// should say "I could not check the schema" and keep going, not fall
// over.
type Deps struct {
	Network  Network
	HTTP     HTTPClient
	Database DatabaseInspector
	Metrics  MetricsReader
	Config   ConfigReader
	Secrets  SecretReader
	Packages PackageReader
	// Now is the clock. Injected so TLS-expiry arithmetic and reading
	// timestamps are reproducible in tests, and so SOURCE_DATE_EPOCH
	// keeps working.
	Now func() time.Time
}

// TLSStatus is the closed set of things a certificate inspection can
// conclude. Deliberately not a timestamp or a subject name: the point is
// to report the health of the certificate without copying its contents
// into a reading.
type TLSStatus string

const (
	TLSValid          TLSStatus = "valid"
	TLSExpiringSoon   TLSStatus = "expiring_soon"
	TLSExpired        TLSStatus = "expired"
	TLSUntrusted      TLSStatus = "untrusted"
	TLSHandshakeError TLSStatus = "handshake_failed"
)

// Network is DNS, TCP and TLS, and nothing above them.
//
// These three deliberately overlap `internal/capture`'s passive checks;
// see docs/PROBES.md, "Why both exist". The difference visible here is
// the return type: capture answers yes/no because it is recording what an
// environment is configured as, while a probe must distinguish "no" from
// "I could not tell", because inconclusive is a verdict it is required to
// be able to reach.
type Network interface {
	// Resolve returns the addresses a name resolves to. An empty result
	// with a nil error means the name resolved to nothing.
	Resolve(ctx context.Context, host string) ([]string, error)
	// Dial opens a TCP connection and closes it immediately. No byte of
	// application protocol is sent.
	Dial(ctx context.Context, host string, port int) error
	// InspectTLS completes a TLS handshake, classifies the peer
	// certificate and closes. No application request is made.
	InspectTLS(ctx context.Context, host string, port int, now time.Time) (TLSStatus, error)
}

// HTTPResponse is as much of a response as a probe is allowed to keep.
//
// No body. Route and schema conformance need the status, the content type
// and the shape of what came back — never its contents, which on a real
// system are user data. A probe that returned bodies would be a probe
// that turns a capture file into a data breach.
type HTTPResponse struct {
	Status      int
	ContentType string
	// BodyKeys are the top-level field names of a JSON object response,
	// sorted. Names only, never values — the same rule config keys follow.
	BodyKeys []string
	// BodyKind is "object", "array", "empty" or "other".
	BodyKind string
	Elapsed  time.Duration
}

// HTTPClient is the only way a probe makes an application request, and it
// is gated on `net.http.outbound`.
//
// Phase 31 field 17, and §4 of the plan for all time: no synthetic
// transaction against a write endpoint. The interface takes no body and
// no method beyond the safe ones, so a caller cannot express one.
type HTTPClient interface {
	// Get issues a GET. Headers are supplied by the probe (an auth probe
	// sends a token it was given); none are read back into a reading.
	Get(ctx context.Context, url string, headers map[string]string) (HTTPResponse, error)
	// Options issues an OPTIONS, used to ask whether a route exists
	// without invoking it.
	Options(ctx context.Context, url string, headers map[string]string) (HTTPResponse, error)
}

// TableColumn is one column of a live schema.
type TableColumn struct {
	Name     string
	DataType string
	Nullable bool
}

// DatabaseInspector reads schema metadata under `db.metadata.read`. Never
// rows: there is no method here that can return one.
//
// It takes a database's *name* — the `database` part of a `schema:`
// subject, or a component — never a connection string. Phase 31 took the
// DSN as a probe input, which put a credential on the command line, in
// shell history and in every process listing. Phase 31.1 field 12: the
// DSN "reaches the probe from the environment, by the name culprit.yaml
// gives". The implementation resolves name -> `dsn_env` -> value itself,
// so no probe ever holds the string.
type DatabaseInspector interface {
	// Connect establishes that the database is reachable and answering,
	// under a read-only session.
	Connect(ctx context.Context, database string) error
	// Columns returns the live columns of a table, read from pg_catalog
	// rather than information_schema — information_schema lists only what
	// the connecting role may use, which would make a least-privilege
	// probe report every other table as missing.
	Columns(ctx context.Context, database, schema, table string) ([]TableColumn, error)
}

// UnavailableError is a data source saying a probe's preconditions are
// unmet — the component is not declared in this environment, the
// variable naming its DSN is unset, its environment could not be fully
// enumerated. A probe turns it into inconclusive: nothing was measured.
type UnavailableError struct{ Reason string }

func (e *UnavailableError) Error() string { return e.Reason }

// RefusedError is a data source declining for want of a grant beyond
// the manifest's own — reading installed packages runs an allowlisted
// command, and that command must be on `process.exec.allowlist` exactly
// as it must be for `culprit env capture`. A probe turns it into refused.
type RefusedError struct {
	Capability string
	Reason     string
}

func (e *RefusedError) Error() string { return e.Reason }

// sourceOutcome maps a data source's error onto a verdict, or reports
// that the caller must decide (a plain error is a measurement failure,
// whose meaning depends on the probe).
func sourceOutcome(err error) (Outcome, bool) {
	var unavailable *UnavailableError
	if errors.As(err, &unavailable) {
		return inconclusive(unavailable.Reason), true
	}
	var refused *RefusedError
	if errors.As(err, &refused) {
		return Outcome{Verdict: model.VerdictRefused, Reason: refused.Reason}, true
	}
	return Outcome{}, false
}

// ImpedanceSample is the OBSERVED-plane summary of one connection.
type ImpedanceSample struct {
	// Deviation is the scorer's z-score: how unusual the current latency
	// or error rate is against that connection's own history.
	Deviation float64
	Metric    string
	// Samples is how many observations the figure rests on. A small
	// number is why a probe returns inconclusive rather than a verdict.
	Samples int
}

// MetricsReader reads already-scored telemetry under
// `telemetry.metrics.read`.
//
// The scoring itself is `worker/app/anomaly/` — EWMA, deterministic, and
// unchanged by this phase (D5). This interface only reads what that job
// wrote; a probe never does statistics of its own.
type MetricsReader interface {
	Impedance(ctx context.Context, connectionSubject string) (ImpedanceSample, bool, error)
}

// ConfigReader answers whether a configuration key is set, under
// `config.read.names`. It returns presence, never a value — there is no
// method here that can return one.
type ConfigReader interface {
	Present(ctx context.Context, component, key string) (bool, error)
}

// SecretReader returns one variable's value, for the one probe that must
// inspect a credential to answer (probe.auth.token_shape reads a token's
// audience, issuer and expiry, and nothing else). It answers only under
// `config.read.values` granted for exactly that `component/KEY` — the
// same grant that lets a capture record a value (Phase 32 part 1's
// review: a service's own credential is what that grant exists to gate).
// Kept apart from ConfigReader so that interface still has no method
// that can return a value.
type SecretReader interface {
	Secret(ctx context.Context, component, key string) (string, error)
}

// PackageReader reads installed dependency versions under `repo.read`.
type PackageReader interface {
	Version(ctx context.Context, component, packageName string) (string, bool, error)
}
