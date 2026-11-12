package probe

import (
	"time"

	"github.com/josh-heath123/culprit/cli/internal/probe/guardedhttp"
)

// The HTTP client lives in internal/probe/guardedhttp, a package of its own
// (Q27): no file here can reach its fields, its transport or its request
// constructor. These names are that package's, kept so the probes read as
// before.

// HTTPResponse is as much of a response as a probe is allowed to keep.
type HTTPResponse = guardedhttp.Response

// RealHTTPClient is the guarded client.
type RealHTTPClient = guardedhttp.RealHTTPClient

// Timing is one timed request.
type Timing = guardedhttp.Timing

// MaxRedirects is how many hops a probe will follow.
const MaxRedirects = guardedhttp.MaxRedirects

// DefaultMaxBodyBytes bounds how much of a response is read.
const DefaultMaxBodyBytes = guardedhttp.DefaultMaxBodyBytes

// NewRealHTTPClient builds the guarded client.
func NewRealHTTPClient(timeout time.Duration) *RealHTTPClient {
	return guardedhttp.NewRealHTTPClient(timeout)
}

// NewRealHTTPClientWithin is NewRealHTTPClient whose redirects are followed
// only to an address within reports true for (Q23).
func NewRealHTTPClientWithin(timeout time.Duration, within func(host string, port int) bool) *RealHTTPClient {
	return guardedhttp.NewRealHTTPClientWithin(timeout, within)
}
