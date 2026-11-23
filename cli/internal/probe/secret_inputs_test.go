// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package probe

import (
	"strings"
	"testing"
)

// credentialParts are the words that make an input's name a secret's
// name, as a part of it (Phase 44 batch 1, decision 4).
var credentialParts = map[string]bool{
	"password": true, "passwd": true, "pwd": true, "secret": true, "token": true,
	"apikey": true, "credential": true, "credentials": true, "dsn": true,
}

// TestEverySecretInputIsDeclaredOnTheInput: an input that carries a secret
// says so on the input itself — `"secret": true` — so the catalogue mirror
// carries the declaration to the API, which refuses a task that sets one
// (F44-005). An input named for a secret must declare it; an `_env` input
// names a variable, not a value, and is not one. A declared `env`
// alternative must be an input of the same probe.
func TestEverySecretInputIsDeclaredOnTheInput(t *testing.T) {
	declared := 0
	for _, manifest := range BuiltIn().Manifests() {
		properties, _ := manifest.Inputs["properties"].(map[string]any)
		for name, raw := range properties {
			schema, _ := raw.(map[string]any)
			secret, _ := schema["secret"].(bool)
			named := false
			if !strings.HasSuffix(name, "_env") {
				for _, part := range strings.Split(name, "_") {
					named = named || credentialParts[part]
				}
			}
			if named && !secret {
				t.Errorf("%s: input %q is named for a secret and does not declare \"secret\": true", manifest.ID, name)
			}
			if secret {
				declared++
			}
			if env, ok := schema["env"].(string); ok {
				if !secret {
					t.Errorf("%s: input %q names an env alternative but is not declared secret", manifest.ID, name)
				}
				if _, exists := properties[env]; !exists {
					t.Errorf("%s: input %q names %q as its env alternative, which is not an input", manifest.ID, name, env)
				}
			}
		}
	}
	if declared == 0 {
		t.Error("no input in the catalogue is declared secret, so nothing is refused")
	}
}

// TestTheTokenShapesTokenNamesItsEnvAlternative: the one secret input
// with an alternative today. probe.auth.propagation's token has none: it
// is declared secret, and refused as a task, with no alternative to name.
func TestTheTokenShapesTokenNamesItsEnvAlternative(t *testing.T) {
	for id, want := range map[string]string{"probe.auth.token_shape": "token_env", "probe.auth.propagation": ""} {
		probe, ok := BuiltIn().Get(id)
		if !ok {
			t.Fatalf("no %s", id)
		}
		properties, _ := probe.Manifest().Inputs["properties"].(map[string]any)
		token, _ := properties["token"].(map[string]any)
		if secret, _ := token["secret"].(bool); !secret {
			t.Errorf("%s: token is not declared secret", id)
		}
		if env, _ := token["env"].(string); env != want {
			t.Errorf("%s: token's env alternative is %q, want %q", id, env, want)
		}
	}
}
