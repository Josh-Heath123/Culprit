// Package guardedhttp is the one place the binary builds and sends an
// HTTP request to a system under test, and the only package that can
// (Q27, ruled 2026-11-12, docs/PERFORMANCE_PLAN.md end of Phase 37).
//
// Phase 36 part 2 held "GET only" with a scan of internal/probe's syntax;
// Q26 replaced it with "only two files import net/http". The phase-auditor
// showed both were the wrong unit: Go's visibility is per package, so any
// file in internal/probe could reach a client's transport through its
// unexported fields, with no import, and send a DELETE. So the client is a
// package of its own, with this one non-test file:
//
//   - newProbeRequest builds every request, refusing any method but GET or
//     OPTIONS before the request exists;
//   - newGuardedClient builds every client, with methodGuard under it,
//     which refuses anything but a bodiless GET or OPTIONS as each request
//     leaves;
//   - RealHTTPClient is all a caller gets: Get, Options and TimeGet. Its
//     exported surface names no type from net/http or net
//     (TestTheExportedSurfaceNamesNoNetworkType), so no caller can unwrap
//     a client, a transport or a request.
//
// TestThisPackageHasOneFile holds the one file. `reflect` and `unsafe`
// still get through; this is a guard against ordinary code, not a proof
// against deliberate code (docs/LIMITS.md).
package guardedhttp

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptrace"
	"sort"
	"strings"
	"sync/atomic"
	"time"
)

// Response is as much of a response as a probe is allowed to keep.
//
// No body. Route and schema conformance need the status, the content type
// and the shape of what came back — never its contents, which on a real
// system are user data. A probe that returned bodies would be a probe
// that turns a capture file into a data breach.
type Response struct {
	Status      int
	ContentType string
	// BodyKeys are the top-level field names of a JSON object response,
	// sorted. Names only, never values — the same rule config keys follow.
	BodyKeys []string
	// BodyKind is "object", "array", "empty" or "other".
	BodyKind string
	Elapsed  time.Duration
}

// RealHTTPClient is the only place in this repository that makes an
// application request to the system under test.
//
// # Why this file is allowed to exist
//
// Until Phase 31 the `culprit` binary linked no HTTP client at all, and a
// test asserted it on the grounds that the binary "has nothing to talk
// to". Probes change that premise: `probe.http.reachable` and its
// siblings exist to ask a running service a question, and §2.7 provisions
// `net.http.outbound` for exactly this. The guarantee that survives is
// the one that was always the point — the deterministic core cannot open
// a socket — and it is now asserted per package, on `internal/check`,
// `internal/diverge`, `internal/severity`, `internal/report` and
// `internal/extract`, which is finer-grained than the binary-wide grep it
// replaces. See cli/cmd/culprit/check_test.go.
//
// # What it deliberately cannot do
//
// There is no method here that sends a body, and none that uses a method
// other than GET or OPTIONS. Phase 31 field 17 and §4 of the plan forbid
// a synthetic transaction against a write endpoint in this or any later
// phase, and the way to keep that promise is to make it unsayable rather
// than to document it.
//
// Bodies are read only far enough to name their top-level fields, under a
// hard size cap, and are never retained. A response body on a real system
// is user data; a probe that kept one would turn a reading into a
// disclosure.
type RealHTTPClient struct {
	client *http.Client
	// MaxBodyBytes bounds how much of a response is parsed for field
	// names. A diagnostic tool must not be turned into a memory
	// exhaustion vector by a service that answers with a gigabyte.
	MaxBodyBytes int64
}

// MaxRedirects is how many hops a probe will follow.
//
// Some, because a health endpoint behind a redirect is ordinary; not
// unlimited, because following a redirect chain wherever it leads is how
// a probe aimed at a service ends up talking to something else entirely.
const MaxRedirects = 3

// DefaultMaxBodyBytes is one mebibyte, which is far more than the field
// names of any sane JSON response need.
const DefaultMaxBodyBytes = 1 << 20

// NewRealHTTPClient builds a client with the safety limits applied.
func NewRealHTTPClient(timeout time.Duration) *RealHTTPClient {
	if timeout <= 0 {
		timeout = 10 * time.Second
	}
	return &RealHTTPClient{
		client: newGuardedClient(http.DefaultTransport, timeout,
			func(request *http.Request, via []*http.Request) error {
				if len(via) >= MaxRedirects {
					return fmt.Errorf("stopped after %d redirects", MaxRedirects)
				}
				return nil
			}),
		MaxBodyBytes: DefaultMaxBodyBytes,
	}
}

// newGuardedClient is the one way this package builds an HTTP client
// (Q26, ruled 2026-11-12): every client sends through methodGuard, which
// refuses anything but a bodiless GET or OPTIONS as the request leaves —
// whatever built the request, and whatever was done to it after.
// TestEveryClientComesFromTheGuardedConstructor holds that http.go and
// timing.go, the only files here that may import net/http, build no
// client any other way.
func newGuardedClient(next http.RoundTripper, timeout time.Duration,
	redirect func(*http.Request, []*http.Request) error,
) *http.Client {
	return &http.Client{Transport: methodGuard{next: next}, Timeout: timeout, CheckRedirect: redirect}
}

// NewRealHTTPClientWithin is NewRealHTTPClient whose redirects are
// followed only to an address within reports true for (Phase 35 part 2,
// Q23). `culprit_probe` binds a probe's address to the endpoints the
// environment declares; without this, a declared endpoint that answered
// 302 would carry the request to wherever the redirect pointed.
func NewRealHTTPClientWithin(timeout time.Duration, within func(host string, port int) bool) *RealHTTPClient {
	bound := NewRealHTTPClient(timeout)
	bound.client.CheckRedirect = func(request *http.Request, via []*http.Request) error {
		if len(via) >= MaxRedirects {
			return fmt.Errorf("stopped after %d redirects", MaxRedirects)
		}
		port := 80
		if request.URL.Scheme == "https" {
			port = 443
		}
		if given := request.URL.Port(); given != "" {
			if _, err := fmt.Sscanf(given, "%d", &port); err != nil {
				return fmt.Errorf("refused a redirect with a port that is not a number")
			}
		}
		if (request.URL.Scheme != "http" && request.URL.Scheme != "https") || !within(request.URL.Hostname(), port) {
			return fmt.Errorf("refused a redirect to an address the environment does not declare")
		}
		return nil
	}
	return bound
}

// Get issues a GET.
func (c *RealHTTPClient) Get(
	ctx context.Context, url string, headers map[string]string,
) (Response, error) {
	return c.do(ctx, http.MethodGet, url, headers)
}

// Options issues an OPTIONS, which asks whether a route exists without
// invoking it.
func (c *RealHTTPClient) Options(
	ctx context.Context, url string, headers map[string]string,
) (Response, error) {
	return c.do(ctx, http.MethodOptions, url, headers)
}

// newProbeRequest builds every request this package sends, refusing any
// method but GET or OPTIONS before the request exists. It is not what
// holds the rule — methodGuard is, as each request leaves — but it keeps
// a write from being built by accident (Phase 36 part 2: TimeGet built
// its own).
func newProbeRequest(ctx context.Context, method, url string) (*http.Request, error) {
	if err := checkMethod(method); err != nil {
		return nil, err
	}
	return http.NewRequestWithContext(ctx, method, url, nil)
}

// checkMethod is the method check: GET or OPTIONS, nothing else. This is
// the line that would have to change for a probe to be able to write, and
// it should be loud. newProbeRequest asks it before a request exists, and
// methodGuard asks it again as any request leaves, so a request built, or
// changed, around newProbeRequest is still refused.
func checkMethod(method string) error {
	if method != http.MethodGet && method != http.MethodOptions {
		return fmt.Errorf("probes issue only GET and OPTIONS; %s would be a write", method)
	}
	return nil
}

// methodGuard is the transport under every client this package builds
// (newGuardedClient): it refuses, before anything is dialled, a request
// checkMethod refuses, or one that carries a body.
type methodGuard struct{ next http.RoundTripper }

func (g methodGuard) RoundTrip(request *http.Request) (*http.Response, error) {
	if err := checkMethod(request.Method); err != nil {
		return nil, err
	}
	if request.Body != nil && request.Body != http.NoBody {
		return nil, fmt.Errorf("probes send no body")
	}
	return g.next.RoundTrip(request)
}

func (c *RealHTTPClient) do(
	ctx context.Context, method, url string, headers map[string]string,
) (Response, error) {
	request, err := newProbeRequest(ctx, method, url)
	if err != nil {
		// The URL is the caller's own configuration, not a secret, but it
		// goes through the same redaction every other error does —
		// standing invariant 11 says error text is output, enforced at
		// one point rather than per call site.
		return Response{}, fmt.Errorf("could not build the request: %w", err)
	}
	for name, value := range headers {
		request.Header.Set(name, value)
	}

	started := time.Now()
	response, err := c.client.Do(request)
	if err != nil {
		return Response{}, err
	}
	defer func() {
		_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, c.MaxBodyBytes))
		_ = response.Body.Close()
	}()
	elapsed := time.Since(started)

	result := Response{
		Status:      response.StatusCode,
		ContentType: response.Header.Get("Content-Type"),
		Elapsed:     elapsed,
		BodyKind:    "other",
	}

	if !strings.Contains(strings.ToLower(result.ContentType), "json") {
		return result, nil
	}

	body, err := io.ReadAll(io.LimitReader(response.Body, c.MaxBodyBytes))
	if err != nil || len(body) == 0 {
		result.BodyKind = "empty"
		return result, nil
	}
	result.BodyKind, result.BodyKeys = describeJSON(body)
	return result, nil
}

// describeJSON reports the shape of a JSON document and, for an object,
// its top-level field names.
//
// Names only. The values are decoded — there is no way to parse JSON
// without doing so — but they are discarded here and never reach a
// Reading, which is the same rule config keys follow and for the same
// reason.
func describeJSON(body []byte) (string, []string) {
	trimmed := strings.TrimSpace(string(body))
	switch {
	case trimmed == "":
		return "empty", nil
	case strings.HasPrefix(trimmed, "["):
		return "array", nil
	case !strings.HasPrefix(trimmed, "{"):
		return "other", nil
	}

	var document map[string]json.RawMessage
	if err := json.Unmarshal(body, &document); err != nil {
		return "other", nil
	}
	keys := make([]string, 0, len(document))
	for key := range document {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return "object", keys
}

// Timing one request — Phase 36 part 1, for probe.http.latency.
//
// What one sample measures is fixed and recorded (docs/PERFORMANCE_PLAN.md,
// "How Phase 36 is run"): one GET on a new connection, timed from dialling
// to the last byte of the response, with the connection's setup — name
// resolution, TCP and any TLS handshake — recorded separately. A client
// that pools connections sees less, and the reading says what it measured.
// Part 2 needs the setup time to tell the hop from the component.
//
// GET only, no header, no body, and no redirect followed: a redirect is an
// answer other than 2xx, so it is not a sample. The response body is read
// to its last byte or to the same 1 MiB cap every other request has,
// whichever comes first, and discarded unread: past the cap, the time is
// to the cap, not to the last byte (LIMITS).

// Timing is one timed request.
type Timing struct {
	Status int
	// Connect is from the start of the request to the connection being
	// ready to send on.
	Connect time.Duration
	// Total is from the start of the request to the last byte of the
	// response, or to MaxBodyBytes of it.
	Total time.Duration
	// TimedOut says the request did not complete within its timeout. A
	// timeout is a sample slower than any answer, not an error.
	TimedOut bool
	// Connected says the connection was ready before the request ended —
	// for a timeout, whether it timed out waiting for the server or before
	// its connection completed (Phase 36 part 2: one counts against the
	// component, the other against the hop). Connect is set only when it
	// is true.
	Connected bool
}

// TimeGet sends one GET on a connection of its own and times it.
func (c *RealHTTPClient) TimeGet(ctx context.Context, url string, timeout time.Duration) (Timing, error) {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.DisableKeepAlives = true
	defer transport.CloseIdleConnections()
	client := newGuardedClient(transport, 0, func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	})

	requestCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	// When the connection became ready, as nanoseconds since started; zero
	// until then. Written by the transport, which may still be dialling on
	// its own goroutine when a timeout returns.
	var connectedAfter atomic.Int64
	started := time.Now()
	trace := &httptrace.ClientTrace{GotConn: func(httptrace.GotConnInfo) {
		connectedAfter.CompareAndSwap(0, int64(max(time.Since(started), 1)))
	}}
	// Built where every probe request is, under its one method check.
	request, err := newProbeRequest(httptrace.WithClientTrace(requestCtx, trace), http.MethodGet, url)
	if err != nil {
		return Timing{}, err
	}

	timedOut := func() bool {
		return ctx.Err() == nil && errors.Is(requestCtx.Err(), context.DeadlineExceeded)
	}
	stamp := func(timing Timing) Timing {
		if after := connectedAfter.Load(); after > 0 {
			timing.Connected, timing.Connect = true, time.Duration(after)
		}
		return timing
	}
	response, err := client.Do(request)
	if err != nil {
		if timedOut() {
			return stamp(Timing{TimedOut: true, Total: time.Since(started)}), nil
		}
		return Timing{}, err
	}
	_, readErr := io.Copy(io.Discard, io.LimitReader(response.Body, c.MaxBodyBytes))
	_ = response.Body.Close()
	total := time.Since(started)
	if readErr != nil {
		if timedOut() {
			return stamp(Timing{TimedOut: true, Total: total}), nil
		}
		return Timing{}, readErr
	}
	return stamp(Timing{Status: response.StatusCode, Total: total}), nil
}
