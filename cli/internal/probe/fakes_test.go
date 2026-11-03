package probe

import (
	"context"
	"errors"
	"net"
	"time"
)

// Fakes for every seam in Deps.
//
// Probes are written against interfaces precisely so that all three of
// pass, fail and inconclusive are reachable in a test. Two of those are
// awkward to arrange against real infrastructure — you cannot ask a
// healthy database to be missing a column — and a probe whose failure
// path is never executed is a probe whose failure path is a guess.

var errBoom = errors.New("dial tcp 10.0.0.5:5432: connect: connection refused")

// errTimeout satisfies net.Error with Timeout() true, which is how a
// probe tells "I could not tell" from "the answer is no".
var errTimeout net.Error = &timeoutError{}

type timeoutError struct{}

func (*timeoutError) Error() string   { return "dial tcp 192.0.2.1:81: i/o timeout" }
func (*timeoutError) Timeout() bool   { return true }
func (*timeoutError) Temporary() bool { return true }

type fakeNetwork struct {
	addresses  []string
	resolveErr error
	dialErr    error
	tlsStatus  TLSStatus
	tlsErr     error
}

func (f fakeNetwork) Resolve(context.Context, string) ([]string, error) {
	return f.addresses, f.resolveErr
}

func (f fakeNetwork) Dial(context.Context, string, int) error { return f.dialErr }

func (f fakeNetwork) InspectTLS(context.Context, string, int, time.Time) (TLSStatus, error) {
	return f.tlsStatus, f.tlsErr
}

type fakeHTTP struct {
	response HTTPResponse
	err      error
	// lastHeaders records what the probe sent, so the token-material test
	// can confirm the token really did go out on the wire — otherwise
	// "the token does not appear in the output" would pass trivially for
	// a probe that never sent it.
	lastHeaders map[string]string
}

func (f *fakeHTTP) Get(
	_ context.Context, _ string, headers map[string]string,
) (HTTPResponse, error) {
	f.lastHeaders = headers
	return f.response, f.err
}

func (f *fakeHTTP) Options(
	_ context.Context, _ string, headers map[string]string,
) (HTTPResponse, error) {
	f.lastHeaders = headers
	return f.response, f.err
}

type fakeDatabase struct {
	connectErr error
	columns    []TableColumn
	columnsErr error
}

func (f fakeDatabase) Connect(context.Context, string) error { return f.connectErr }

func (f fakeDatabase) Columns(
	context.Context, string, string, string,
) ([]TableColumn, error) {
	return f.columns, f.columnsErr
}

type fakeMetrics struct {
	sample ImpedanceSample
	found  bool
	err    error
}

func (f fakeMetrics) Impedance(context.Context, string) (ImpedanceSample, bool, error) {
	return f.sample, f.found, f.err
}

type fakeConfig struct {
	present bool
	err     error
}

func (f fakeConfig) Present(context.Context, string, string) (bool, error) {
	return f.present, f.err
}

type fakePackages struct {
	version string
	found   bool
	err     error
}

func (f fakePackages) Version(context.Context, string, string) (string, bool, error) {
	return f.version, f.found, f.err
}

// fixedClock keeps every reading's timestamp reproducible.
func fixedClock() func() time.Time {
	moment := time.Date(2026, 9, 12, 10, 0, 0, 0, time.UTC)
	return func() time.Time { return moment }
}
