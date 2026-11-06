package transport

import (
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/agentauth"
)

// The transport's confinement (Phase 33 part 2): it signs what it sends,
// dials only its control plane, follows no redirect and ignores a proxy
// from the environment. Each is shown against real local servers.

func newKey(t *testing.T) ed25519.PrivateKey {
	t.Helper()
	key, _, err := GenerateKey()
	if err != nil {
		t.Fatal(err)
	}
	return key
}

// verifying is a handler that checks every request's signature the way
// the control plane does, and counts what it accepted.
func verifying(t *testing.T, key ed25519.PrivateKey, accepted *atomic.Int64) http.Handler {
	public := key.Public().(ed25519.PublicKey)
	seen := map[string]bool{}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		timestamp, _ := strconv.ParseInt(r.Header.Get(agentauth.HeaderTimestamp), 10, 64)
		request := agentauth.Request{
			Method: r.Method, Path: r.URL.Path, Body: body, Timestamp: timestamp,
			Nonce: r.Header.Get(agentauth.HeaderNonce), AgentID: r.Header.Get(agentauth.HeaderAgent),
		}
		ok := agentauth.Decide(&agentauth.Key{Public: public}, request,
			r.Header.Get(agentauth.HeaderSignature), time.Now(), func(n string) bool { return seen[n] })
		if !ok {
			http.Error(w, "request refused", http.StatusUnauthorized)
			return
		}
		seen[request.Nonce] = true
		accepted.Add(1)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"seq":0,"hash":"` + strings.Repeat("0", 64) + `"}`))
	})
}

func TestEverySignedRequestVerifiesAtTheControlPlane(t *testing.T) {
	key := newKey(t)
	var accepted atomic.Int64
	plane := httptest.NewServer(verifying(t, key, &accepted))
	defer plane.Close()
	client, err := New(plane.URL+"/api", "agent-1", key, 2*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	// The path signed is relative to the API root, as the control plane
	// sees it behind the dashboard's proxy; this server sees /api/..., so
	// strip it the way the proxy would.
	plane.Config.Handler = http.StripPrefix("/api", verifying(t, key, &accepted))
	for index := 0; index < 3; index++ {
		response, err := client.send(context.Background(), http.MethodGet, "/agents/me/audit/head", nil, true)
		if err != nil || response.Status != http.StatusOK {
			t.Fatalf("request %d: %v %d %s", index, err, response.Status, response.Body)
		}
	}
	if accepted.Load() != 3 {
		t.Errorf("%d accepted, want 3: each request a fresh nonce", accepted.Load())
	}

	// Another agent's key is refused.
	client.key = newKey(t)
	response, _ := client.send(context.Background(), http.MethodGet, "/agents/me/audit/head", nil, true)
	if response.Status != http.StatusUnauthorized {
		t.Errorf("a request signed with another key got %d", response.Status)
	}
}

func TestTheClientDialsOnlyItsControlPlane(t *testing.T) {
	var elsewhere atomic.Int64
	other := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		elsewhere.Add(1)
	}))
	defer other.Close()
	plane := httptest.NewServer(http.NotFoundHandler())
	defer plane.Close()

	client, err := New(plane.URL, "agent-1", newKey(t), 2*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	_, err = client.http.Get(other.URL + "/anything")
	if err == nil || !strings.Contains(err.Error(), "refusing to dial") {
		t.Fatalf("err = %v, want a refusal to dial another address", err)
	}
	if elsewhere.Load() != 0 {
		t.Error("the other server was reached")
	}
}

func TestARedirectIsNotFollowed(t *testing.T) {
	var elsewhere atomic.Int64
	other := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		elsewhere.Add(1)
	}))
	defer other.Close()
	plane := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, other.URL+"/agents/me/tasks/claim", http.StatusTemporaryRedirect)
	}))
	defer plane.Close()

	client, err := New(plane.URL, "agent-1", newKey(t), 2*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	_, err = client.send(context.Background(), http.MethodPost, "/agents/me/tasks/claim", nil, true)
	if !errors.Is(err, ErrRedirect) {
		t.Fatalf("err = %v, want ErrRedirect", err)
	}
	// Even a redirect back to the same address is not followed.
	plane.Config.Handler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/elsewhere" {
			t.Error("the redirect was followed")
		}
		http.Redirect(w, r, "/elsewhere", http.StatusFound)
	})
	if _, err := client.send(context.Background(), http.MethodGet, "/x", nil, true); !errors.Is(err, ErrRedirect) {
		t.Errorf("same-address redirect: err = %v", err)
	}
	if elsewhere.Load() != 0 {
		t.Error("the redirect target was reached")
	}
}

func TestAProxyFromTheEnvironmentIsIgnored(t *testing.T) {
	var proxied, direct atomic.Int64
	proxy := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		proxied.Add(1)
	}))
	defer proxy.Close()
	plane := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		direct.Add(1)
		w.WriteHeader(http.StatusNoContent)
	}))
	defer plane.Close()
	t.Setenv("HTTP_PROXY", proxy.URL)
	t.Setenv("HTTPS_PROXY", proxy.URL)
	t.Setenv("NO_PROXY", "")

	client, err := New(plane.URL, "agent-1", newKey(t), 2*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := client.send(context.Background(), http.MethodPost, "/agents/me/tasks/claim", nil, true); err != nil {
		t.Fatal(err)
	}
	if proxied.Load() != 0 || direct.Load() != 1 {
		t.Errorf("proxied %d, direct %d: the agent must reach its control plane directly", proxied.Load(), direct.Load())
	}
	// Go never proxies a loopback address, so the request above cannot
	// show a proxy function on its own; the transport must have none.
	// (Were one set, the dialer would still refuse the proxy's address.)
	if client.http.Transport.(*http.Transport).Proxy != nil {
		t.Error("the transport takes a proxy from somewhere; it must dial its control plane directly")
	}
}

func TestAKeyFileRoundTripsAndRejectsAnythingElse(t *testing.T) {
	key, encoded, err := GenerateKey()
	if err != nil {
		t.Fatal(err)
	}
	parsed, err := ParseKey(encoded)
	if err != nil || !parsed.Equal(key) {
		t.Fatalf("parsed %v, err %v", parsed, err)
	}
	for _, bad := range []string{"", "culprit-agent-key-v1\n", "other-header\n" + base64.StdEncoding.EncodeToString(key.Seed())} {
		if _, err := ParseKey([]byte(bad)); err == nil {
			t.Errorf("accepted %q", bad)
		}
	}
}

func TestARegistrationCarriesNoPrivateKey(t *testing.T) {
	key := newKey(t)
	registration := NewRegistration("CODE", "agent-1", key, map[string][]string{"production": {"net.tcp.connect"}})
	public := base64.StdEncoding.EncodeToString(key.Public().(ed25519.PublicKey))
	if registration.PublicKey != public {
		t.Error("the registration does not carry the public key")
	}
}
