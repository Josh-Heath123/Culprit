package probe

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The HTTP probes.
//
// These are the first code in the `culprit` binary that makes an
// application request, which is why they are gated on
// `net.http.outbound` and why the HTTPClient interface cannot express a
// write. Phase 31 field 17 and §4 of the plan both forbid a synthetic
// transaction against a write endpoint — not as a setting, but by there
// being no method to call.
//
// GET and OPTIONS only. Neither is guaranteed safe on a badly built
// system, but they are the two HTTP defines as safe, and the alternative
// (asking a stranger's production service to accept a POST) is not a
// diagnostic tool, it is an outage.

// --- probe.http.reachable ----------------------------------------------

type httpReachable struct{}

func (httpReachable) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID:           "probe.http.reachable",
		Version:      1,
		Effect:       model.EffectInterrogate,
		Capabilities: []string{"net.http.outbound"},
		TimeoutMS:    10_000,
		ExpectedFrom: model.PlaneConfigured,
		Produces: []model.Produces{
			{SubjectTemplate: "component:{component}", Predicate: "http_reachable"},
		},
		Cost: model.CostCheap,
		Inputs: map[string]any{
			"type":     "object",
			"required": []any{"url"},
			"properties": map[string]any{
				"url": map[string]any{"type": "string"},
			},
		},
	}
}

func (httpReachable) Run(ctx context.Context, request Request, deps Deps) Outcome {
	url, ok := stringInput(request.Inputs, "url")
	if !ok {
		return inconclusive("no URL to request: this target declares no health endpoint")
	}
	if deps.HTTP == nil {
		return inconclusive("no HTTP client is available to this agent")
	}

	response, err := deps.HTTP.Get(ctx, url, nil)
	if err != nil {
		// A timeout, or a redirect chain we stopped following, establishes
		// nothing about whether the service is healthy — both are
		// failures of the measurement, not measurements of failure.
		if isIndeterminate(err) || strings.Contains(err.Error(), "stopped after") {
			return inconclusive(fmt.Sprintf(
				"no usable HTTP response from %s: %s",
				url, model.RedactCredentials(err.Error())))
		}
		return fail(map[string]any{"url": url}, fmt.Sprintf(
			"no HTTP response from %s: %s", url, model.RedactCredentials(err.Error())))
	}
	measured := map[string]any{
		"url": url, "status": response.Status,
		"elapsed_ms": response.Elapsed.Milliseconds(),
	}
	if response.Status >= 500 {
		return fail(measured, fmt.Sprintf(
			"%s answered %d; the service is reachable but failing", url, response.Status))
	}
	if response.Status >= 400 {
		return inconclusive(fmt.Sprintf(
			"%s answered %d. The service is reachable, but a 4xx may mean the "+
				"health path is wrong rather than the service being unhealthy",
			url, response.Status))
	}
	return pass(measured)
}

// --- probe.http.route_conformance --------------------------------------

type httpRouteConformance struct{}

func (httpRouteConformance) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID:           "probe.http.route_conformance",
		Version:      1,
		Effect:       model.EffectInterrogate,
		Capabilities: []string{"net.http.outbound"},
		TimeoutMS:    15_000,
		// The expectation is a route the INTENT plane says should exist.
		ExpectedFrom: model.PlaneIntent,
		Produces: []model.Produces{
			{SubjectTemplate: "http:{component}/{method} {path}", Predicate: "route_exists"},
		},
		Cost: model.CostCheap,
		Inputs: map[string]any{
			"type":     "object",
			"required": []any{"url"},
			"properties": map[string]any{
				"url":    map[string]any{"type": "string"},
				"method": map[string]any{"type": "string"},
			},
		},
	}
}

func (httpRouteConformance) Run(ctx context.Context, request Request, deps Deps) Outcome {
	url, ok := stringInput(request.Inputs, "url")
	if !ok {
		return inconclusive("no URL to check: no route was named for this target")
	}
	if deps.HTTP == nil {
		return inconclusive("no HTTP client is available to this agent")
	}
	method, _ := stringInput(request.Inputs, "method")
	if method == "" {
		method = "GET"
	}

	// OPTIONS asks whether a route exists without invoking it. For a
	// method that is not safe to call, this is the only honest way to
	// ask, and a service that does not answer OPTIONS gives us
	// inconclusive rather than a guess.
	var response HTTPResponse
	var err error
	if strings.EqualFold(method, "GET") {
		response, err = deps.HTTP.Get(ctx, url, nil)
	} else {
		response, err = deps.HTTP.Options(ctx, url, nil)
	}
	if err != nil {
		return inconclusive(fmt.Sprintf(
			"could not reach %s to check whether the route exists: %s",
			url, model.RedactCredentials(err.Error())))
	}

	measured := map[string]any{"url": url, "method": method, "status": response.Status}
	expected := map[string]any{"route_exists": true}

	switch {
	case response.Status == 404:
		// "is declared" only if something actually declared it. Without an
		// expectation this probe has measured a 404 and nothing more, and
		// saying otherwise would be asserting a claim it never established
		// — the exact guessing this architecture exists to avoid.
		if request.Expectation == nil {
			return inconclusive(fmt.Sprintf(
				"%s %s answers 404, but no INTENT fact declares this route, so "+
					"there is nothing to say it should exist", method, url))
		}
		return Outcome{
			Verdict: model.VerdictFail, Measured: measured, Expected: expected,
			ExpectedSource: provenanceOf(request.Expectation),
			Reason: fmt.Sprintf(
				"%s %s is declared but the running service answers 404", method, url),
		}
	case response.Status == 405:
		if request.Expectation == nil {
			return inconclusive(fmt.Sprintf(
				"%s is not allowed on %s, but no INTENT fact declares that method "+
					"for this route", method, url))
		}
		return Outcome{
			Verdict: model.VerdictFail, Measured: measured, Expected: expected,
			ExpectedSource: provenanceOf(request.Expectation),
			Reason: fmt.Sprintf(
				"%s is declared for %s but the running service does not allow that method",
				method, url),
		}
	case response.Status >= 500:
		return inconclusive(fmt.Sprintf(
			"%s answered %d, so whether the route exists cannot be established",
			url, response.Status))
	default:
		return Outcome{
			Verdict: model.VerdictPass, Measured: measured, Expected: expected,
			ExpectedSource: provenanceOf(request.Expectation),
		}
	}
}

// --- probe.http.schema_conformance -------------------------------------

type httpSchemaConformance struct{}

func (httpSchemaConformance) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID:           "probe.http.schema_conformance",
		Version:      1,
		Effect:       model.EffectInterrogate,
		Capabilities: []string{"net.http.outbound"},
		TimeoutMS:    15_000,
		ExpectedFrom: model.PlaneIntent,
		Produces: []model.Produces{
			{SubjectTemplate: "http:{component}/{method} {path}#response.body",
				Predicate: "response_fields"},
		},
		Cost: model.CostCheap,
		Inputs: map[string]any{
			"type":     "object",
			"required": []any{"url", "expect_fields"},
			"properties": map[string]any{
				"url": map[string]any{"type": "string"},
				"expect_fields": map[string]any{
					"type": "array", "items": map[string]any{"type": "string"},
				},
			},
		},
	}
}

func (httpSchemaConformance) Run(ctx context.Context, request Request, deps Deps) Outcome {
	url, hasURL := stringInput(request.Inputs, "url")
	wanted, hasFields := stringsInput(request.Inputs, "expect_fields")
	if !hasURL {
		return inconclusive("no URL to request: no response schema was named for this target")
	}
	if !hasFields || len(wanted) == 0 {
		return inconclusive(fmt.Sprintf(
			"no declared response fields for %s, so there is nothing to conform to", url))
	}
	if deps.HTTP == nil {
		return inconclusive("no HTTP client is available to this agent")
	}

	response, err := deps.HTTP.Get(ctx, url, nil)
	if err != nil {
		return inconclusive(fmt.Sprintf(
			"could not reach %s to read its response shape: %s",
			url, model.RedactCredentials(err.Error())))
	}
	if response.Status >= 400 {
		return inconclusive(fmt.Sprintf(
			"%s answered %d, so its success-response shape could not be read",
			url, response.Status))
	}
	if response.BodyKind != "object" {
		return inconclusive(fmt.Sprintf(
			"%s returned a %s, and field conformance is only meaningful for an object",
			url, response.BodyKind))
	}

	present := map[string]bool{}
	for _, key := range response.BodyKeys {
		present[key] = true
	}
	var missing []string
	for _, field := range wanted {
		if !present[field] {
			missing = append(missing, field)
		}
	}
	sort.Strings(missing)

	// Field names only, never values — the same rule config keys follow,
	// and for the same reason: a response body on a real system is user
	// data.
	measured := map[string]any{"url": url, "fields": response.BodyKeys}
	expected := map[string]any{"fields": wanted}

	if len(missing) > 0 {
		return Outcome{
			Verdict: model.VerdictFail, Measured: measured, Expected: expected,
			ExpectedSource: provenanceOf(request.Expectation),
			Reason: fmt.Sprintf(
				"%s does not return declared field(s): %s",
				url, strings.Join(missing, ", ")),
		}
	}
	return Outcome{
		Verdict: model.VerdictPass, Measured: measured, Expected: expected,
		ExpectedSource: provenanceOf(request.Expectation),
	}
}

// provenanceOf carries the expectation's source onto the reading, so a
// failing reading can be traced back to the claim it contradicts rather
// than just asserting one.
func provenanceOf(fact *model.Fact) *model.Provenance {
	if fact == nil {
		return nil
	}
	provenance := fact.Provenance
	return &provenance
}
