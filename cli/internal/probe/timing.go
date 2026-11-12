package probe

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptrace"
	"sync/atomic"
	"time"
)

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

// Timer times one GET on a fresh connection. RealHTTPClient implements it;
// an HTTPClient that does not (a test fake) cannot take a latency sample,
// and the probe says so.
type Timer interface {
	TimeGet(ctx context.Context, url string, timeout time.Duration) (Timing, error)
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
