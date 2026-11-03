package probe

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The auth probes.
//
// Field 12 states the rule these exist under: "Auth probes inspect token
// *structure* and never log token material — enforced by a test that runs
// the auth probes against a fixture token and greps the full output for
// it."
//
// That test is TestAuthProbesNeverEmitTokenMaterial. It is the reason
// nothing in this file puts a token, a segment of one, or a signature
// into a Measured map, an Evidence value or a Reason string. Claims that
// are themselves identifiers — `aud`, `iss` — are reported, because a
// wrong audience is the finding; the credential is the signature and the
// whole assembled token, and neither ever leaves this file.

// --- probe.auth.token_shape --------------------------------------------

type authTokenShape struct{}

func (authTokenShape) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID:      "probe.auth.token_shape",
		Version: 1,
		Effect:  model.EffectInspect,
		// No capability: this probe opens nothing. It reads a token the
		// caller already holds and reports its structure.
		Capabilities: nil,
		TimeoutMS:    2_000,
		ExpectedFrom: model.PlaneIntent,
		Produces: []model.Produces{
			{SubjectTemplate: "auth:{from}->{to}/audience", Predicate: "token_claims"},
		},
		Cost: model.CostCheap,
		Inputs: map[string]any{
			"type":     "object",
			"required": []any{"token"},
			"properties": map[string]any{
				"token":           map[string]any{"type": "string"},
				"expect_audience": map[string]any{"type": "string"},
				"expect_issuer":   map[string]any{"type": "string"},
			},
		},
	}
}

// jwtClaims is the subset of a token this probe will look at. Everything
// else in the payload is ignored rather than collected, so there is no
// path by which an unexpected claim ends up in a reading.
type jwtClaims struct {
	Audience  any    `json:"aud"`
	Issuer    string `json:"iss"`
	Expiry    int64  `json:"exp"`
	NotBefore int64  `json:"nbf"`
}

func (authTokenShape) Run(ctx context.Context, request Request, deps Deps) Outcome {
	token, ok := stringInput(request.Inputs, "token")
	if !ok {
		return inconclusive("no token was supplied, so its shape cannot be inspected")
	}

	claims, err := decodeClaims(token)
	if err != nil {
		// The error deliberately describes the shape problem without
		// quoting the input. `err` here is constructed from a closed set
		// of messages below for exactly that reason.
		return inconclusive(fmt.Sprintf("the token could not be read: %s", err))
	}

	now := deps.Now()
	measured := map[string]any{
		"issuer":    claims.Issuer,
		"audiences": audienceList(claims),
		"expired":   claims.Expiry > 0 && now.Unix() >= claims.Expiry,
	}
	if claims.Expiry > 0 {
		measured["expires_in_seconds"] = claims.Expiry - now.Unix()
	}

	var problems []string
	if claims.Expiry > 0 && now.Unix() >= claims.Expiry {
		problems = append(problems, "it has expired")
	}
	if claims.NotBefore > 0 && now.Unix() < claims.NotBefore {
		problems = append(problems, "it is not valid yet")
	}

	expectedAudience, hasAudience := stringInput(request.Inputs, "expect_audience")
	expected := map[string]any{}
	if hasAudience {
		expected["audience"] = expectedAudience
		if !containsString(audienceList(claims), expectedAudience) {
			problems = append(problems, fmt.Sprintf(
				"its audience is %v, not %q", audienceList(claims), expectedAudience))
		}
	}
	expectedIssuer, hasIssuer := stringInput(request.Inputs, "expect_issuer")
	if hasIssuer {
		expected["issuer"] = expectedIssuer
		if claims.Issuer != expectedIssuer {
			problems = append(problems, fmt.Sprintf(
				"its issuer is %q, not %q", claims.Issuer, expectedIssuer))
		}
	}

	if len(problems) > 0 {
		return Outcome{
			Verdict: model.VerdictFail, Measured: measured, Expected: expected,
			ExpectedSource: provenanceOf(request.Expectation),
			Reason:         "the token will not be accepted: " + strings.Join(problems, "; "),
		}
	}
	if !hasAudience && !hasIssuer {
		return inconclusive(
			"the token is well-formed and unexpired, but no expected audience or " +
				"issuer was declared, so there is nothing to check it against")
	}
	return Outcome{
		Verdict: model.VerdictPass, Measured: measured, Expected: expected,
		ExpectedSource: provenanceOf(request.Expectation),
	}
}

// decodeClaims reads a JWT's payload segment.
//
// Every error it returns is a fixed string. Formatting the offending
// input into an error is how Phase 28 leaked four times over (standing
// invariant 11: error text is output), and a malformed token is exactly
// the case where the input is most likely to be a real credential.
func decodeClaims(token string) (jwtClaims, error) {
	segments := strings.Split(token, ".")
	if len(segments) != 3 {
		return jwtClaims{}, fmt.Errorf("it is not a three-segment JWT")
	}
	payload, err := base64.RawURLEncoding.DecodeString(strings.TrimRight(segments[1], "="))
	if err != nil {
		return jwtClaims{}, fmt.Errorf("its payload segment is not valid base64url")
	}
	var claims jwtClaims
	if err := json.Unmarshal(payload, &claims); err != nil {
		return jwtClaims{}, fmt.Errorf("its payload is not a JSON object")
	}
	return claims, nil
}

// audienceList normalises `aud`, which RFC 7519 allows to be either a
// string or an array of them.
func audienceList(claims jwtClaims) []string {
	switch value := claims.Audience.(type) {
	case string:
		if value == "" {
			return nil
		}
		return []string{value}
	case []any:
		result := make([]string, 0, len(value))
		for _, item := range value {
			if text, ok := item.(string); ok {
				result = append(result, text)
			}
		}
		return result
	default:
		return nil
	}
}

func containsString(haystack []string, needle string) bool {
	for _, item := range haystack {
		if item == needle {
			return true
		}
	}
	return false
}

// --- probe.auth.propagation --------------------------------------------

type authPropagation struct{}

func (authPropagation) Manifest() model.ProbeManifest {
	return model.ProbeManifest{
		ID:           "probe.auth.propagation",
		Version:      1,
		Effect:       model.EffectInterrogate,
		Capabilities: []string{"net.http.outbound"},
		TimeoutMS:    15_000,
		ExpectedFrom: model.PlaneIntent,
		Produces: []model.Produces{
			{SubjectTemplate: "auth:{from}->{to}/propagation", Predicate: "token_accepted"},
		},
		Cost: model.CostCheap,
		Inputs: map[string]any{
			"type":     "object",
			"required": []any{"url", "token"},
			"properties": map[string]any{
				"url":   map[string]any{"type": "string"},
				"token": map[string]any{"type": "string"},
			},
		},
	}
}

func (authPropagation) Run(ctx context.Context, request Request, deps Deps) Outcome {
	url, hasURL := stringInput(request.Inputs, "url")
	token, hasToken := stringInput(request.Inputs, "token")
	if !hasURL || !hasToken {
		return inconclusive(
			"a URL and a token are both needed to tell whether credentials survive the hop")
	}
	if deps.HTTP == nil {
		return inconclusive("no HTTP client is available to this agent")
	}

	// The token goes out on the wire, because that is the measurement.
	// It does not come back into the reading: `measured` below records
	// only the status.
	withToken, err := deps.HTTP.Get(ctx, url, map[string]string{
		"Authorization": "Bearer " + token,
	})
	if err != nil {
		return inconclusive(fmt.Sprintf(
			"could not reach %s to test credential propagation: %s",
			url, model.RedactCredentials(err.Error())))
	}

	measured := map[string]any{"url": url, "status_with_token": withToken.Status}

	switch {
	case withToken.Status == 401:
		return fail(measured, fmt.Sprintf(
			"%s rejected the token as unauthenticated (401); credentials are not "+
				"surviving this hop", url))
	case withToken.Status == 403:
		return fail(measured, fmt.Sprintf(
			"%s authenticated the token but refused it (403); the identity arrives "+
				"without the authority it needs", url))
	case withToken.Status >= 500:
		return inconclusive(fmt.Sprintf(
			"%s answered %d, so whether the credential was accepted cannot be told",
			url, withToken.Status))
	default:
		return pass(measured)
	}
}
