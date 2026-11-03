package extract

import (
	"fmt"
	"sort"
	"strings"
)

// culprit.yaml's `probes:` section (Phase 31 field 10).
//
// Enable/disable, timeout overrides, and per-environment applicability —
// and deliberately nothing else. A probe's capabilities are declared by
// the probe itself, in its manifest, and granted per environment under
// `environments:`. Letting this section widen a grant would put "what
// culprit may do to my system" in two places, and the whole point of the
// permission model is that it is in one.
//
//	probes:
//	  probe.net.tls_validity:
//	    enabled: false
//	    reason: our certificates are managed elsewhere
//	  probe.http.route_conformance:
//	    timeout_ms: 30000
//	    environments: [staging]
type ProbeSpec struct {
	// Enabled is a pointer so "absent" and "explicitly false" stay
	// distinguishable: the default is on, and a probe nobody mentioned is
	// not the same as one somebody turned off.
	Enabled *bool `yaml:"enabled"`
	// Reason is required when disabling. Same discipline as `suppress:`
	// and `severity_overrides:` in Phase 29: a silenced check with no
	// stated reason is indistinguishable from an oversight six months
	// later.
	Reason    string `yaml:"reason"`
	TimeoutMS int    `yaml:"timeout_ms"`
	// Environments restricts a probe to named environments. Empty means
	// every environment.
	Environments []string `yaml:"environments"`
}

// ProbeIDs returns the probe ids configured here, sorted, so error
// messages and listings are stable.
func (m *Manifest) ProbeIDs() []string {
	ids := make([]string, 0, len(m.Probes))
	for id := range m.Probes {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

// validateProbes checks the section against itself and against
// `environments:`.
//
// It deliberately does NOT check ids against the built-in catalogue.
// Third-party probes are manifests plus an `exec` procedure (field 7), so
// a manifest may legitimately configure a probe this binary does not
// know; the runner reports an unknown id as inconclusive at run time,
// which is the honest place for it. Refusing it here would make
// culprit.yaml unshareable between a team using a plugin and one that is
// not.
func (m *Manifest) validateProbes() error {
	environments := map[string]bool{}
	for _, name := range m.EnvironmentNames() {
		environments[name] = true
	}

	for _, id := range m.ProbeIDs() {
		spec := m.Probes[id]

		parts := strings.Split(id, ".")
		if len(parts) != 3 || parts[0] != "probe" || parts[1] == "" || parts[2] == "" {
			return fmt.Errorf(
				"probes: %q is not a probe id; expected 'probe.<group>.<name>', "+
					"e.g. probe.net.tcp_connect", id)
		}

		if spec.Enabled != nil && !*spec.Enabled && strings.TrimSpace(spec.Reason) == "" {
			return fmt.Errorf(
				"probes.%s is disabled but gives no reason. A check switched off "+
					"without a stated reason is indistinguishable from one nobody "+
					"noticed was off", id)
		}

		if spec.TimeoutMS < 0 {
			return fmt.Errorf("probes.%s: timeout_ms cannot be negative", id)
		}
		if spec.TimeoutMS > 300_000 {
			return fmt.Errorf(
				"probes.%s: timeout_ms %d is above the 300000 ceiling; a probe that "+
					"can hang for five minutes is not diagnosing, it is waiting",
				id, spec.TimeoutMS)
		}

		for _, environment := range spec.Environments {
			if !environments[environment] {
				// The same convention validateEnvironments uses: a name
				// that does not exist is a typo, and a typo that silently
				// disables a probe everywhere is the worst possible
				// outcome.
				return fmt.Errorf(
					"probes.%s names environment %q, which is not declared under "+
						"environments:", id, environment)
			}
		}
	}
	return nil
}
