package probe

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// fakeSecrets stands for the environment the agent runs in. It refuses the
// way secretSource does when config.read.values does not name the key.
type fakeSecrets struct {
	values  map[string]string // "component/KEY" -> value
	granted map[string]bool   // "component/KEY" -> config.read.values allows it
	asked   []string
}

func (f *fakeSecrets) Secret(_ context.Context, component, key string) (string, error) {
	item := component + "/" + key
	f.asked = append(f.asked, item)
	if !f.granted[item] {
		return "", &RefusedError{Capability: "config.read.values",
			Reason: "reading " + key + " needs config.read.values for " + item}
	}
	value, ok := f.values[item]
	if !ok {
		return "", &UnavailableError{Reason: key + " is not set for " + component}
	}
	return value, nil
}

func tokenEnvReading(t *testing.T, secrets *fakeSecrets) model.Reading {
	t.Helper()
	runner := NewRunner(Options{
		Ledger: grantEverything(t),
		Deps:   Deps{Secrets: secrets, Now: fixedClock()},
	})
	return runner.Run(context.Background(), []Request{{
		ProbeID: "probe.auth.token_shape", Target: authTarget, Environment: "staging",
		Inputs: map[string]any{"token_env": "INVENTORY_TOKEN", "expect_audience": "inventory-service"},
	}})[0]
}

// TestATokenIsReadOnlyUnderItsOwnGrant is part 2's first item (Phase 32
// part 1's review): reading a service's own credential needs
// config.read.values for that variable. Without it the reading is refused
// and says why; with it, the probe measures the token as before.
func TestATokenIsReadOnlyUnderItsOwnGrant(t *testing.T) {
	_, parts, _ := model.ParseSubject(authTarget)
	holder := parts["from_component"] + "/INVENTORY_TOKEN"

	ungranted := &fakeSecrets{values: map[string]string{holder: wrongAudienceToken}}
	reading := tokenEnvReading(t, ungranted)
	if reading.Verdict != model.VerdictRefused || !strings.Contains(reading.Reason, "config.read.values") {
		t.Fatalf("without the grant: %s (%q), want refused naming config.read.values", reading.Verdict, reading.Reason)
	}
	if len(reading.GrantsUsed) != 0 {
		t.Errorf("a refused reading lists grants_used %v", reading.GrantsUsed)
	}

	granted := &fakeSecrets{values: map[string]string{holder: wrongAudienceToken}, granted: map[string]bool{holder: true}}
	reading = tokenEnvReading(t, granted)
	if reading.Verdict != model.VerdictFail || !strings.Contains(reading.Reason, "audience") {
		t.Fatalf("with the grant: %s (%q), want fail on the audience", reading.Verdict, reading.Reason)
	}
	if len(granted.asked) != 1 || granted.asked[0] != holder {
		t.Errorf("asked for %v, want the caller's own variable %s", granted.asked, holder)
	}

	// A grant for another key is not a grant for this one.
	other := &fakeSecrets{values: map[string]string{holder: goodToken},
		granted: map[string]bool{parts["from_component"] + "/SOMETHING_ELSE": true}}
	if reading := tokenEnvReading(t, other); reading.Verdict != model.VerdictRefused {
		t.Errorf("a grant for another key: %s, want refused", reading.Verdict)
	}
}

func TestATokenReadFromTheEnvironmentNeverReachesTheReading(t *testing.T) {
	_, parts, _ := model.ParseSubject(authTarget)
	holder := parts["from_component"] + "/INVENTORY_TOKEN"
	for _, token := range []string{goodToken, wrongAudienceToken} {
		reading := tokenEnvReading(t, &fakeSecrets{
			values: map[string]string{holder: token}, granted: map[string]bool{holder: true}})
		encoded, err := json.Marshal(reading)
		if err != nil {
			t.Fatal(err)
		}
		for _, segment := range strings.Split(token, ".") {
			if strings.Contains(string(encoded), segment) {
				t.Errorf("a segment of the token reached the reading: %s", encoded)
			}
		}
	}
}
