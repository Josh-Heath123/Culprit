package probe

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sort"
	"strings"
	"time"
)

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
		client: &http.Client{
			Transport: methodGuard{next: http.DefaultTransport},
			Timeout:   timeout,
			CheckRedirect: func(request *http.Request, via []*http.Request) error {
				if len(via) >= MaxRedirects {
					return fmt.Errorf("stopped after %d redirects", MaxRedirects)
				}
				return nil
			},
		},
		MaxBodyBytes: DefaultMaxBodyBytes,
	}
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
) (HTTPResponse, error) {
	return c.do(ctx, http.MethodGet, url, headers)
}

// Options issues an OPTIONS, which asks whether a route exists without
// invoking it.
func (c *RealHTTPClient) Options(
	ctx context.Context, url string, headers map[string]string,
) (HTTPResponse, error) {
	return c.do(ctx, http.MethodOptions, url, headers)
}

// newProbeRequest is the one place in this package an HTTP request is
// built, and so the one place its method is checked: GET or OPTIONS, with
// no body. TestEveryRequestIsBuiltInOnePlace holds that nothing else in
// internal/probe builds one — not http.NewRequest, not a literal
// http.Request — so no request can be built around the check (Phase 36
// part 2: TimeGet built its own).
func newProbeRequest(ctx context.Context, method, url string) (*http.Request, error) {
	if err := checkMethod(method); err != nil {
		return nil, err
	}
	return http.NewRequestWithContext(ctx, method, url, nil)
}

// checkMethod is the method check: GET or OPTIONS, nothing else. This is
// the line that would have to change for a probe to be able to write, and
// it should be loud. newProbeRequest asks it before a request exists, and
// methodGuard asks it again as any request leaves, so a request built
// around newProbeRequest is still refused (the Phase 36 part 2 audit found
// three ways to build one that the source scan missed).
func checkMethod(method string) error {
	if method != http.MethodGet && method != http.MethodOptions {
		return fmt.Errorf("probes issue only GET and OPTIONS; %s would be a write", method)
	}
	return nil
}

// methodGuard is the transport under every client this package builds:
// it refuses, before anything is dialled, a request checkMethod refuses,
// or one that carries a body. TestEveryRequestIsBuiltInOnePlace holds that
// every http.Client literal here has one.
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
) (HTTPResponse, error) {
	request, err := newProbeRequest(ctx, method, url)
	if err != nil {
		// The URL is the caller's own configuration, not a secret, but it
		// goes through the same redaction every other error does —
		// standing invariant 11 says error text is output, enforced at
		// one point rather than per call site.
		return HTTPResponse{}, fmt.Errorf("could not build the request: %w", err)
	}
	for name, value := range headers {
		request.Header.Set(name, value)
	}

	started := time.Now()
	response, err := c.client.Do(request)
	if err != nil {
		return HTTPResponse{}, err
	}
	defer func() {
		_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, c.MaxBodyBytes))
		_ = response.Body.Close()
	}()
	elapsed := time.Since(started)

	result := HTTPResponse{
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
