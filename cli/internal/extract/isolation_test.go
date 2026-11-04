package extract

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

const isolationManifest = `version: 1
components:
  - name: api
    kind: service
environments:
  staging:
    adapter: process
    components: { api: {} }
  production:
    adapter: process
    components: { api: {} }
isolation:
%s
`

func loadIsolation(t *testing.T, block string) (*Manifest, error) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "culprit.yaml")
	if err := os.WriteFile(path, []byte(strings.Replace(isolationManifest, "%s", block, 1)), 0o600); err != nil {
		t.Fatal(err)
	}
	return LoadManifest(path)
}

func TestTheTighterIsolationBudgetWins(t *testing.T) {
	manifest, err := loadIsolation(t, `  max_probes: 20
  max_wall_clock: 90s
  environments:
    production: { max_probes: 5 }
    staging: { max_probes: 50 }`)
	if err != nil {
		t.Fatal(err)
	}
	for environment, want := range map[string]int{"production": 5, "staging": 20} {
		probes, wallClock := manifest.IsolationBudget(environment)
		if probes != want || wallClock != 90*time.Second {
			t.Errorf("%s: budget %d / %s, want %d / 90s", environment, probes, wallClock, want)
		}
	}
}

func TestAnUnsetIsolationBudgetIsTheWalksDefault(t *testing.T) {
	manifest, err := loadIsolation(t, `  environments:
    production: { max_probes: 7 }`)
	if err != nil {
		t.Fatal(err)
	}
	if probes, wallClock := manifest.IsolationBudget("staging"); probes != 0 || wallClock != 0 {
		t.Errorf("staging: %d / %s, want 0 / 0 (the walk's defaults)", probes, wallClock)
	}
	if probes, _ := manifest.IsolationBudget("production"); probes != 7 {
		t.Errorf("production: %d, want 7", probes)
	}
}

func TestABadIsolationBlockIsRefused(t *testing.T) {
	for _, block := range []string{
		"  max_wall_clock: banana",
		"  max_probes: -1",
		"  environments:\n    nowhere: { max_probes: 3 }",
	} {
		if _, err := loadIsolation(t, block); err == nil {
			t.Errorf("accepted %q", block)
		}
	}
}
