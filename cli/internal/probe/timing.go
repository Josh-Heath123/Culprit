package probe

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptrace"
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
// to its last byte, under the same size cap as every other request, and
// discarded unread.

// Timing is one timed request.
type Timing struct {
	Status int
	// Connect is from the start of the request to the connection being
	// ready to send on.
	Connect time.Duration
	// Total is from the start of the request to the last byte of the
	// response.
	Total time.Duration
	// TimedOut says the request did not complete within its timeout. A
	// timeout is a sample slower than any answer, not an error.
	TimedOut bool
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
	client := &http.Client{
		Transport: transport,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}

	requestCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	var connected time.Time
	trace := &httptrace.ClientTrace{GotConn: func(httptrace.GotConnInfo) { connected = time.Now() }}
	// A constant method, as RealHTTPClient.do allows: GET, with no body.
	request, err := http.NewRequestWithContext(
		httptrace.WithClientTrace(requestCtx, trace), http.MethodGet, url, nil)
	if err != nil {
		return Timing{}, err
	}

	started := time.Now()
	timedOut := func() bool {
		return ctx.Err() == nil && errors.Is(requestCtx.Err(), context.DeadlineExceeded)
	}
	response, err := client.Do(request)
	if err != nil {
		if timedOut() {
			return Timing{TimedOut: true, Total: time.Since(started)}, nil
		}
		return Timing{}, err
	}
	_, readErr := io.Copy(io.Discard, io.LimitReader(response.Body, c.MaxBodyBytes))
	_ = response.Body.Close()
	total := time.Since(started)
	if readErr != nil {
		if timedOut() {
			return Timing{TimedOut: true, Total: total}, nil
		}
		return Timing{}, readErr
	}
	timing := Timing{Status: response.StatusCode, Total: total}
	if !connected.IsZero() {
		timing.Connect = connected.Sub(started)
	}
	return timing, nil
}
