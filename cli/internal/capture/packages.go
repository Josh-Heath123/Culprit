package capture

import (
	"encoding/json"
	"sort"
	"strings"
)

// Installed package versions (field 4), read from an allowlisted command
// the user declares — `pip freeze` inside the container, `npm ls --json`,
// anything that prints one of the two formats below.
//
// # A different predicate from the INTENT side, on purpose
//
// The dependency reader emits `version` facts, and what it reads is a
// *constraint* — `fastapi>=0.115`, `react: ^18.2.0`. What an environment
// has is an exact version. Comparing `>=0.115` with `0.115.4` by
// equality would report every dependency in every environment as a
// disagreement, and deciding whether one satisfies the other means
// implementing PEP 440 and semver ranges inside a comparator that D7
// says knows nothing about any domain. So installed versions are
// `installed_version`, a different claim: comparable environment against
// environment ("staging has fastapi 0.115.4, production 0.110.0" — a
// real "works in staging" cause), and not compared against the
// constraint at all. That gap is written down in docs/LIMITS.md.

// ParsePackages is parsePackages for `culprit probe`'s dependency data
// source (Phase 31.1), which reads installed versions through the same
// allowlisted command and the same two formats as a capture, so a probe
// and a capture cannot read one environment differently.
func ParsePackages(output []byte) (map[string]string, bool) {
	return parsePackages(output)
}

// parsePackages reads either `pip freeze` lines or `npm ls --json`.
func parsePackages(output []byte) (map[string]string, bool) {
	trimmed := strings.TrimSpace(string(output))
	if strings.HasPrefix(trimmed, "{") {
		return parseNpmLs([]byte(trimmed))
	}
	versions := map[string]string{}
	for _, line := range strings.Split(trimmed, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") || strings.HasPrefix(line, "-") {
			continue
		}
		// `name==1.2.3`. An editable install (`-e git+...`) or a direct
		// URL reference (`name @ file:///...`) has no comparable version
		// and is skipped rather than recorded as a path — a path is
		// machine-specific and would differ between every two
		// environments for no reason anyone cares about.
		name, version, found := strings.Cut(line, "==")
		if !found {
			continue
		}
		name = strings.ToLower(strings.TrimSpace(name))
		version = strings.TrimSpace(version)
		if name != "" && version != "" && !strings.ContainsAny(name, " @/=") &&
			!strings.HasPrefix(version, "=") {
			versions[name] = version
		}
	}
	return versions, len(versions) > 0
}

func parseNpmLs(output []byte) (map[string]string, bool) {
	var tree struct {
		Dependencies map[string]struct {
			Version string `json:"version"`
		} `json:"dependencies"`
	}
	if err := json.Unmarshal(output, &tree); err != nil {
		return nil, false
	}
	versions := map[string]string{}
	for name, dependency := range tree.Dependencies {
		if dependency.Version != "" {
			versions[name] = dependency.Version
		}
	}
	return versions, len(versions) > 0
}

func sortedKeys[V any](values map[string]V) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}
