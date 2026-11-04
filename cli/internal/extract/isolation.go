package extract

import (
	"fmt"
	"time"
)

// IsolationSpec is `isolation:` in culprit.yaml (Phase 32 field 10): how
// far one `culprit diagnose` may go. A walk that reaches a limit stops and
// says so — every hypothesis it did not get to is reported as unexplored,
// with the limit as its reason — rather than running on.
//
//	isolation:
//	  max_probes: 40          # per investigation
//	  max_wall_clock: 2m
//	  environments:
//	    production:
//	      max_probes: 10      # tighter where probing costs more
type IsolationSpec struct {
	MaxProbes    int                                 `yaml:"max_probes"`
	MaxWallClock string                              `yaml:"max_wall_clock"`
	Environments map[string]IsolationEnvironmentSpec `yaml:"environments"`
}

// IsolationEnvironmentSpec is one environment's own budget.
type IsolationEnvironmentSpec struct {
	MaxProbes int `yaml:"max_probes"`
}

// IsolationBudget is the effective limit for one environment: the tighter
// of the global and per-environment caps. Zero means "use the walk's
// default".
func (m *Manifest) IsolationBudget(environment string) (int, time.Duration) {
	probes := m.Isolation.MaxProbes
	if own, ok := m.Isolation.Environments[environment]; ok && own.MaxProbes > 0 &&
		(probes == 0 || own.MaxProbes < probes) {
		probes = own.MaxProbes
	}
	var wallClock time.Duration
	if m.Isolation.MaxWallClock != "" {
		// Validated when the manifest loaded.
		wallClock, _ = time.ParseDuration(m.Isolation.MaxWallClock)
	}
	return probes, wallClock
}

func (m *Manifest) validateIsolation() error {
	spec := m.Isolation
	if spec.MaxProbes < 0 {
		return fmt.Errorf("isolation.max_probes: must be positive")
	}
	if spec.MaxWallClock != "" {
		duration, err := time.ParseDuration(spec.MaxWallClock)
		if err != nil || duration <= 0 {
			return fmt.Errorf("isolation.max_wall_clock: a duration such as 2m or 90s")
		}
	}
	for name, own := range spec.Environments {
		if _, declared := m.Environments[name]; !declared {
			return fmt.Errorf("isolation.environments.%s: not an environment declared under environments:", name)
		}
		if own.MaxProbes < 0 {
			return fmt.Errorf("isolation.environments.%s.max_probes: must be positive", name)
		}
	}
	return nil
}

// componentNamed finds a component declared in components:.
func (m *Manifest) componentNamed(name string) (ManifestComponent, bool) {
	for _, component := range m.Components {
		if component.Name == name {
			return component, true
		}
	}
	return ManifestComponent{}, false
}
