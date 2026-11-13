package probe

import (
	"context"
	"fmt"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The three network probes.
//
// Each one stops exactly where `internal/capture`'s passive equivalent
// stops — a resolver query, a TCP handshake, a TLS handshake — and none
// of them sends application data. What they add is a verdict: capture
// records that an environment is set up with a given endpoint, while
// these answer "and can it actually be reached, right now, from here".

// --- probe.net.dns_resolve ---------------------------------------------

type dnsResolve struct{}

func (dnsResolve) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID:       "probe.net.dns_resolve",
		Verdicts: allVerdicts,
		// No Discriminates: a name that resolves says nothing about whether a
		// connection opens. probe.net.tcp_connect resolves the name too, so it
		// alone rules out connection_unreachable (found in Phase 32's first run).
		Version:      1,
		Effect:       model.EffectInspect,
		Capabilities: []string{"net.dns.resolve"},
		TimeoutMS:    5_000,
		ExpectedFrom: model.PlaneConfigured,
		Produces: []model.Produces{
			{SubjectTemplate: "component:{component}", Predicate: "dns_resolves"},
		},
		Cost: model.CostCheap,
		Inputs: map[string]any{
			"type":     "object",
			"required": []any{"host"},
			"properties": map[string]any{
				"host": map[string]any{"type": "string"},
			},
		},
	}
}

func (dnsResolve) Run(ctx context.Context, request Request, deps Deps) Outcome {
	host, ok := stringInput(request.Inputs, "host")
	if !ok {
		return inconclusive(
			"no host to resolve: this target declares no endpoint, so there is " +
				"nothing to look up")
	}
	if deps.Network == nil {
		return inconclusive("no resolver is available to this agent")
	}

	addresses, err := deps.Network.Resolve(ctx, host)
	if err != nil {
		return inconclusive(fmt.Sprintf(
			"the resolver did not answer for %q: %s", host, model.RedactCredentials(err.Error())))
	}
	measured := map[string]any{"host": host, "addresses": len(addresses)}
	if len(addresses) == 0 {
		return fail(measured, fmt.Sprintf("%q does not resolve to any address", host))
	}
	return pass(measured)
}

// --- probe.net.tcp_connect ---------------------------------------------

type tcpConnect struct{}

func (tcpConnect) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID:            "probe.net.tcp_connect",
		Verdicts:      allVerdicts,
		Discriminates: []string{model.HypothesisConnectionUnreachable},
		Version:       1,
		Effect:        model.EffectInspect,
		Capabilities:  []string{"net.tcp.connect"},
		TimeoutMS:     5_000,
		ExpectedFrom:  model.PlaneConfigured,
		Produces: []model.Produces{
			{SubjectTemplate: "connection:{from}->{to}", Predicate: "tcp_connects"},
		},
		Cost: model.CostCheap,
		Inputs: map[string]any{
			"type":     "object",
			"required": []any{"host", "port"},
			"properties": map[string]any{
				"host": map[string]any{"type": "string"},
				"port": map[string]any{"type": "integer"},
			},
		},
	}
}

func (tcpConnect) Run(ctx context.Context, request Request, deps Deps) Outcome {
	host, hasHost := stringInput(request.Inputs, "host")
	port, hasPort := intInput(request.Inputs, "port")
	if !hasHost || !hasPort {
		return inconclusive(
			"no host and port to connect to: this target declares no endpoint")
	}
	if deps.Network == nil {
		return inconclusive("no network is available to this agent")
	}

	measured := map[string]any{"host": host, "port": port}
	if err := deps.Network.Dial(ctx, host, port); err != nil {
		// A timeout proves nothing. A firewall that drops packets, a host
		// under load and a genuinely dead service look identical from
		// here, so this is `inconclusive` — saying `fail` would send
		// someone to fix the wrong thing.
		if isIndeterminate(err) {
			return inconclusive(fmt.Sprintf(
				"no answer from %s:%d within the timeout. That is not the same "+
					"as the port being closed: a dropped packet and a dead "+
					"service look alike from here",
				host, port))
		}
		// A refused connection, by contrast, is definitive: something
		// answered and said no. This is the broken-relationship case —
		// both components can be perfectly healthy in themselves while
		// this comes back fail.
		return fail(measured, fmt.Sprintf(
			"cannot open a TCP connection to %s:%d: %s",
			host, port, model.RedactCredentials(err.Error())))
	}
	return pass(measured)
}

// --- probe.net.tls_validity --------------------------------------------

type tlsValidity struct{}

func (tlsValidity) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID:            "probe.net.tls_validity",
		Verdicts:      allVerdicts,
		Discriminates: []string{model.HypothesisTLSInvalid},
		Version:       1,
		Effect:        model.EffectInspect,
		// A TLS handshake is a TCP connection first, so both are needed.
		// Declaring only the TLS one would let a grant of it alone open a
		// socket the operator did not agree to.
		Capabilities: []string{"net.tls.inspect", "net.tcp.connect"},
		TimeoutMS:    10_000,
		ExpectedFrom: model.PlaneConfigured,
		Produces: []model.Produces{
			{SubjectTemplate: "component:{component}", Predicate: "tls_certificate"},
		},
		Cost: model.CostCheap,
		Inputs: map[string]any{
			"type":     "object",
			"required": []any{"host", "port"},
			"properties": map[string]any{
				"host": map[string]any{"type": "string"},
				"port": map[string]any{"type": "integer"},
			},
		},
	}
}

func (tlsValidity) Run(ctx context.Context, request Request, deps Deps) Outcome {
	host, hasHost := stringInput(request.Inputs, "host")
	port, hasPort := intInput(request.Inputs, "port")
	if !hasHost || !hasPort {
		return inconclusive("no host and port to inspect: this target declares no endpoint")
	}
	if deps.Network == nil {
		return inconclusive("no network is available to this agent")
	}

	status, err := deps.Network.InspectTLS(ctx, host, port, deps.Now())
	measured := map[string]any{"host": host, "port": port, "status": string(status)}

	if err != nil && status == TLSHandshakeError {
		return inconclusive(fmt.Sprintf(
			"the TLS handshake with %s:%d did not complete, so the certificate "+
				"could not be read: %s",
			host, port, model.RedactCredentials(err.Error())))
	}

	switch status {
	case TLSValid:
		return pass(measured)
	case TLSExpiringSoon:
		return fail(measured, fmt.Sprintf(
			"the certificate presented by %s:%d expires within 30 days", host, port))
	case TLSExpired:
		return fail(measured, fmt.Sprintf(
			"the certificate presented by %s:%d has expired", host, port))
	case TLSUntrusted:
		return fail(measured, fmt.Sprintf(
			"the certificate presented by %s:%d is not trusted", host, port))
	default:
		return inconclusive(fmt.Sprintf(
			"the certificate presented by %s:%d could not be classified", host, port))
	}
}
