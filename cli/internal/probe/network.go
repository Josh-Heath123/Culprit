package probe

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"net"
	"os"
	"sort"
	"strconv"
	"time"
)

// RealNetwork is DNS, TCP and TLS against the actual network.
//
// This is the only place in the probe package that opens a socket below
// HTTP, and it stops where `internal/capture`'s equivalent stops: a
// resolver query, a TCP handshake closed immediately, a TLS handshake
// closed as soon as the certificate is in hand. No byte of application
// protocol is sent by anything in this file.
//
// It deliberately overlaps capture/network.go rather than calling it.
// The reason is the return types: capture answers yes/no because it is
// recording what an environment is configured as, and a probe must be
// able to distinguish "no" from "I could not tell". Collapsing the two
// would mean changing capture's interface, which this phase does not own.
// docs/PROBES.md, "Why both exist", states the overlap and what it costs.
type RealNetwork struct {
	// Timeout bounds each individual operation. The runner also applies
	// the manifest timeout to the probe as a whole; this one keeps a
	// single hung dial from eating the whole budget.
	Timeout time.Duration
	// ExpiringSoon is how much remaining certificate life still counts as
	// a warning. Thirty days, matching capture's classification, because
	// two different answers to "is this expiring" would be worse than
	// either.
	ExpiringSoon time.Duration
}

// NewRealNetwork returns a RealNetwork with the standard budgets.
func NewRealNetwork(timeout time.Duration) *RealNetwork {
	if timeout <= 0 {
		timeout = 5 * time.Second
	}
	return &RealNetwork{Timeout: timeout, ExpiringSoon: 30 * 24 * time.Hour}
}

// Resolve asks the resolver and stops. The endpoint is not contacted.
func (n *RealNetwork) Resolve(ctx context.Context, host string) ([]string, error) {
	ctx, cancel := context.WithTimeout(ctx, n.Timeout)
	defer cancel()

	addresses, err := net.DefaultResolver.LookupHost(ctx, host)
	if err != nil {
		var dnsErr *net.DNSError
		if errors.As(err, &dnsErr) && dnsErr.IsNotFound {
			// A name that does not exist is an answer, not a failure to
			// get one. The probe turns this into `fail`; a timeout below
			// becomes `inconclusive`.
			return nil, nil
		}
		return nil, err
	}
	sort.Strings(addresses)
	return addresses, nil
}

// Dial opens a TCP connection and closes it immediately.
func (n *RealNetwork) Dial(ctx context.Context, host string, port int) error {
	ctx, cancel := context.WithTimeout(ctx, n.Timeout)
	defer cancel()

	dialer := &net.Dialer{}
	conn, err := dialer.DialContext(ctx, "tcp", net.JoinHostPort(host, strconv.Itoa(port)))
	if err != nil {
		return err
	}
	return conn.Close()
}

// InspectTLS completes a handshake, classifies the certificate and closes.
//
// It returns a closed-set status rather than the certificate, so a
// reading can say "expiring within 30 days" without carrying a subject
// name, a serial or an issuer into a file someone attaches to a ticket.
func (n *RealNetwork) InspectTLS(
	ctx context.Context, host string, port int, now time.Time,
) (TLSStatus, error) {
	ctx, cancel := context.WithTimeout(ctx, n.Timeout)
	defer cancel()

	dialer := &tls.Dialer{NetDialer: &net.Dialer{}, Config: &tls.Config{ServerName: host}}
	conn, err := dialer.DialContext(ctx, "tcp", net.JoinHostPort(host, strconv.Itoa(port)))
	if err != nil {
		var unknownAuthority x509.UnknownAuthorityError
		var hostnameErr x509.HostnameError
		var invalid x509.CertificateInvalidError
		switch {
		case errors.As(err, &unknownAuthority), errors.As(err, &hostnameErr):
			return TLSUntrusted, nil
		case errors.As(err, &invalid):
			if invalid.Reason == x509.Expired {
				return TLSExpired, nil
			}
			return TLSUntrusted, nil
		}
		return TLSHandshakeError, err
	}
	defer func() { _ = conn.Close() }()

	tlsConn, ok := conn.(*tls.Conn)
	if !ok {
		return TLSHandshakeError, fmt.Errorf("connection to %s is not TLS", host)
	}
	certificates := tlsConn.ConnectionState().PeerCertificates
	if len(certificates) == 0 {
		return TLSHandshakeError, fmt.Errorf("%s presented no certificate", host)
	}

	leaf := certificates[0]
	switch {
	case now.After(leaf.NotAfter):
		return TLSExpired, nil
	case now.Add(n.ExpiringSoon).After(leaf.NotAfter):
		return TLSExpiringSoon, nil
	default:
		return TLSValid, nil
	}
}

// isIndeterminate reports whether a network error means "I could not
// tell" rather than "the answer is no".
//
// The distinction is the whole reason probes have four verdicts. A
// connection that is actively refused proves the port is closed. A
// connection that times out proves nothing: a firewall that drops
// packets, a host under load and a genuinely dead service are
// indistinguishable from the caller's side, and reporting any of them as
// `fail` sends someone to fix the wrong thing.
//
// Phase 31 shipped this the wrong way round in its first cut — every
// dial error became `fail`, while docs/PROBES.md, docs/LIMITS.md and
// CLAUDE.md all described the behaviour implemented here. The phase
// audit caught the contradiction. The documents described the better
// behaviour, so the code moved.
func isIndeterminate(err error) bool {
	if err == nil {
		return false
	}
	if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, os.ErrDeadlineExceeded) {
		return true
	}
	var netErr net.Error
	if errors.As(err, &netErr) {
		return netErr.Timeout()
	}
	return false
}
