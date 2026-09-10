package capture

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"net"
	"strconv"
	"time"
)

// DNS resolvability, reachable ports and TLS certificate expiry (field 4),
// each under its own `net.*` capability.
//
// # These are not requests into the system under test
//
// Field 17 says "No requests into the system under test." Each check here
// stops strictly short of one:
//
//   - **DNS** asks a resolver about a name. The endpoint is not contacted.
//   - **A reachable port** is a TCP handshake, closed immediately. No byte
//     of application protocol is sent.
//   - **A certificate** is a TLS handshake, closed immediately after the
//     server presents its chain. Again, no application byte — no HTTP
//     request line, no SQL startup message.
//
// Nothing here ever reaches the application's code, and nothing is
// written anywhere. Phase 31's probes (`probe.net.tcp_connect`,
// `probe.net.tls_validity`, …) are the active, verdict-returning versions
// of these; this is the passive "what is this environment set up as"
// half, and it is recorded as an overlap for that phase to reconcile
// rather than resolved by guessing which phase should own it.
//
// # Results are closed classes, not measurements
//
// A certificate is `valid`, `expires_within_30_days`, `expired`,
// `untrusted` or `handshake_failed` — never a timestamp. Two environments'
// certificates expire on different days as a matter of course, and a
// raw `not_after` would make every environment pair "disagree" about
// something nobody needs told. The class is the part that is ever wrong.

// TLS certificate classes.
const (
	TLSValid           = "valid"
	TLSExpiringSoon    = "expires_within_30_days"
	TLSExpired         = "expired"
	TLSUntrusted       = "untrusted"
	TLSHandshakeFailed = "handshake_failed"
)

// expiryWarning is how close to expiry a certificate is flagged at.
const expiryWarning = 30 * 24 * time.Hour

// Network is the network half of a capture, injectable for tests.
type Network interface {
	Resolves(ctx context.Context, host string) bool
	Reachable(ctx context.Context, host string, port int) bool
	Certificate(ctx context.Context, host string, port int, now time.Time) string
}

// RealNetwork does it for real, with bounded timeouts.
type RealNetwork struct {
	Timeout time.Duration
}

func (n RealNetwork) timeout() time.Duration {
	if n.Timeout == 0 {
		return 5 * time.Second
	}
	return n.Timeout
}

// Resolves reports whether a hostname resolves to at least one address.
func (n RealNetwork) Resolves(parent context.Context, host string) bool {
	ctx, cancel := context.WithTimeout(parent, n.timeout())
	defer cancel()
	addresses, err := net.DefaultResolver.LookupHost(ctx, host)
	return err == nil && len(addresses) > 0
}

// Reachable reports whether a TCP handshake completes.
func (n RealNetwork) Reachable(parent context.Context, host string, port int) bool {
	dialer := net.Dialer{Timeout: n.timeout()}
	conn, err := dialer.DialContext(parent, "tcp", net.JoinHostPort(host, strconv.Itoa(port)))
	if err != nil {
		return false
	}
	_ = conn.Close()
	return true
}

// Certificate classifies the certificate an endpoint presents, verified
// against the system roots for the hostname as declared.
func (n RealNetwork) Certificate(parent context.Context, host string, port int, now time.Time) string {
	dialer := &tls.Dialer{
		NetDialer: &net.Dialer{Timeout: n.timeout()},
		Config:    &tls.Config{ServerName: host, MinVersion: tls.VersionTLS12},
	}
	ctx, cancel := context.WithTimeout(parent, n.timeout())
	defer cancel()
	conn, err := dialer.DialContext(ctx, "tcp", net.JoinHostPort(host, strconv.Itoa(port)))
	if err != nil {
		var unknownAuthority x509.UnknownAuthorityError
		var hostname x509.HostnameError
		var invalid x509.CertificateInvalidError
		switch {
		case errors.As(err, &invalid) && invalid.Reason == x509.Expired:
			return TLSExpired
		case errors.As(err, &unknownAuthority), errors.As(err, &hostname), errors.As(err, &invalid):
			return TLSUntrusted
		}
		return TLSHandshakeFailed
	}
	defer conn.Close()
	state := conn.(*tls.Conn).ConnectionState()
	if len(state.PeerCertificates) == 0 {
		return TLSHandshakeFailed
	}
	return classifyExpiry(state.PeerCertificates[0].NotAfter, now)
}

// classifyExpiry is the part worth a table-driven test: the boundary.
func classifyExpiry(notAfter, now time.Time) string {
	switch {
	case !now.Before(notAfter):
		return TLSExpired
	case notAfter.Sub(now) <= expiryWarning:
		return TLSExpiringSoon
	default:
		return TLSValid
	}
}
