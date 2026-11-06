package probe

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/capability"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// secretSource's own tests (Phase 33 part 1): the real source, over the
// process adapter with a stubbed environment — not the fake the token_env
// tests use. What they pin down:
//
//   - the value is read only under config.inspect.values for exactly
//     component/KEY;
//   - config.read.values does not satisfy it (storing a value and
//     inspecting one are different permissions);
//   - every refusal is recorded on the ledger and exercises nothing;
//   - a read records config.inspect.values as exercised, so the reading's
//     grants_used names it.

const secretHolder = "order-service"
const secretKey = "INVENTORY_TOKEN"

func secretSources(t *testing.T, raw map[string]capability.Raw, environ []string) *Sources {
	t.Helper()
	grants, err := capability.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	return &Sources{
		Environment: "test-env",
		Spec: extract.EnvironmentSpec{
			Adapter:    extract.AdapterProcess,
			Components: map[string]extract.EnvironmentComponent{secretHolder: {}},
		},
		Grants:  grants,
		Ledger:  capability.NewLedger(grants),
		Environ: func() []string { return environ },
	}
}

func readSecret(t *testing.T, sources *Sources) (string, error, []string) {
	t.Helper()
	ctx, used := capability.WithExercised(context.Background())
	value, err := sources.Secrets().Secret(ctx, secretHolder, secretKey)
	return value, err, used.List()
}

func refusedNaming(t *testing.T, err error, want string) {
	t.Helper()
	var refused *RefusedError
	if !errors.As(err, &refused) {
		t.Fatalf("err = %v, want a refusal", err)
	}
	if refused.Capability != want || !strings.Contains(refused.Reason, want) {
		t.Errorf("refused under %q (%q), want %q named", refused.Capability, refused.Reason, want)
	}
}

func TestSecretSourceReadsUnderConfigInspectValuesForThatKey(t *testing.T) {
	sources := secretSources(t, map[string]capability.Raw{
		"config.inspect.values": {Items: []string{secretHolder + "/" + secretKey}},
	}, []string{secretKey + "=the-token", "OTHER=x"})
	value, err, used := readSecret(t, sources)
	if err != nil || value != "the-token" {
		t.Fatalf("value %q, err %v", value, err)
	}
	if strings.Join(used, ",") != "config.inspect.values" {
		t.Errorf("exercised %v, want [config.inspect.values]", used)
	}
	if refusals := sources.Ledger.Refusals(); len(refusals) != 0 {
		t.Errorf("a granted read left refusals: %+v", refusals)
	}
}

func TestConfigReadValuesDoesNotLetASecretBeInspected(t *testing.T) {
	sources := secretSources(t, map[string]capability.Raw{
		"config.read.values": {Items: []string{secretHolder + "/" + secretKey}},
	}, []string{secretKey + "=the-token"})
	value, err, used := readSecret(t, sources)
	if value != "" {
		t.Fatal("a value was read under config.read.values")
	}
	refusedNaming(t, err, "config.inspect.values")
	if len(used) != 0 {
		t.Errorf("a refused read exercised %v", used)
	}
	refusals := sources.Ledger.Refusals()
	if len(refusals) != 1 || refusals[0].Capability != "config.inspect.values" {
		t.Errorf("ledger refusals %+v, want one for config.inspect.values", refusals)
	}
}

func TestASecretOffTheAllowlistIsRefused(t *testing.T) {
	sources := secretSources(t, map[string]capability.Raw{
		"config.inspect.values": {Items: []string{secretHolder + "/SOME_OTHER_KEY"}},
	}, []string{secretKey + "=the-token"})
	_, err, used := readSecret(t, sources)
	refusedNaming(t, err, "config.inspect.values")
	if !strings.Contains(err.Error()+err.(*RefusedError).Reason, "allowlist") {
		t.Errorf("the refusal does not say the key is off the allowlist: %v", err)
	}
	if len(used) != 0 {
		t.Errorf("a refused read exercised %v", used)
	}
}

func TestASecretThatIsNotSetIsUnavailableNotRefused(t *testing.T) {
	sources := secretSources(t, map[string]capability.Raw{
		"config.inspect.values": {Items: []string{secretHolder + "/" + secretKey}},
	}, []string{"OTHER=x"})
	_, err, _ := readSecret(t, sources)
	var unavailable *UnavailableError
	if !errors.As(err, &unavailable) || !strings.Contains(unavailable.Reason, "not set") {
		t.Errorf("err = %v, want unavailable: not set", err)
	}
}

func TestASecretSourceRefusalNeverQuotesTheValue(t *testing.T) {
	sources := secretSources(t, map[string]capability.Raw{
		"config.read.values": {Items: []string{secretHolder + "/" + secretKey}},
	}, []string{secretKey + "=sekrit-value-xyz"})
	_, err, _ := readSecret(t, sources)
	if strings.Contains(err.Error(), "sekrit") {
		t.Errorf("the refusal quotes the value: %v", err)
	}
}

// --- grants_used, through the runner ---------------------------------------

func tokenShapeThroughRunner(t *testing.T, raw map[string]capability.Raw, environ []string) model.Reading {
	t.Helper()
	sources := secretSources(t, raw, environ)
	runner := NewRunner(Options{
		Ledger: sources.Ledger,
		Deps:   Deps{Secrets: sources.Secrets(), Now: fixedClock()},
	})
	target := model.MustBuildSubject(model.KindAuth, model.Parts{
		"from_component": secretHolder, "to_component": "inventory-service", "aspect": "audience",
	})
	readings := runner.Run(context.Background(), []Request{{
		ProbeID: "probe.auth.token_shape", Target: target, Environment: "test-env",
		Inputs: map[string]any{"token_env": secretKey, "expect_audience": "inventory-service"},
	}})
	return readings[0]
}

func TestATokenShapeReadingThatReadACredentialNamesTheGrant(t *testing.T) {
	reading := tokenShapeThroughRunner(t, map[string]capability.Raw{
		"config.inspect.values": {Items: []string{secretHolder + "/" + secretKey}},
	}, []string{secretKey + "=" + wrongAudienceToken})
	if reading.Verdict != model.VerdictFail {
		t.Fatalf("verdict %s (%s), want fail on the wrong audience", reading.Verdict, reading.Reason)
	}
	if strings.Join(reading.GrantsUsed, ",") != "config.inspect.values" {
		t.Errorf("grants_used %v, want [config.inspect.values]: the manifest declares nothing, "+
			"but the run read a credential under it", reading.GrantsUsed)
	}
}

func TestARefusedTokenShapeReadingNamesNoGrant(t *testing.T) {
	reading := tokenShapeThroughRunner(t, map[string]capability.Raw{
		"config.read.values": {Items: []string{secretHolder + "/" + secretKey}},
	}, []string{secretKey + "=" + wrongAudienceToken})
	if reading.Verdict != model.VerdictRefused || !strings.Contains(reading.Reason, "config.inspect.values") {
		t.Fatalf("verdict %s (%q), want refused naming config.inspect.values", reading.Verdict, reading.Reason)
	}
	if len(reading.GrantsUsed) != 0 {
		t.Errorf("a refused reading lists grants_used %v", reading.GrantsUsed)
	}
}

func TestATokenHandedInExercisesNoGrant(t *testing.T) {
	runner := NewRunner(Options{Deps: Deps{Now: fixedClock()}})
	target := model.MustBuildSubject(model.KindAuth, model.Parts{
		"from_component": secretHolder, "to_component": "inventory-service", "aspect": "audience",
	})
	reading := runner.Run(context.Background(), []Request{{
		ProbeID: "probe.auth.token_shape", Target: target,
		Inputs: map[string]any{"token": wrongAudienceToken, "expect_audience": "inventory-service"},
	}})[0]
	if len(reading.GrantsUsed) != 0 {
		t.Errorf("grants_used %v for a token the caller already held", reading.GrantsUsed)
	}
}
