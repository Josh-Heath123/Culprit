package probe

import (
	"fmt"
	"sort"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Catalogue is the set of probes a binary knows how to run.
//
// Field 3: "Manifests are data, not code, so the catalogue is extensible
// without recompiling the engine." The fourteen below are compiled in
// because they are the core set; a third party adds one as a manifest
// plus an `exec` procedure on `process.exec.allowlist` (field 7), which
// is why Register is exported and why nothing here assumes a probe is
// one of the built-ins.
type Catalogue struct {
	probes map[string]Probe
}

// NewCatalogue returns an empty catalogue.
func NewCatalogue() *Catalogue {
	return &Catalogue{probes: map[string]Probe{}}
}

// register adds a probe, refusing one whose manifest does not validate.
//
// This is the second place `effect: mutate` is stopped — the first being
// ProbeManifest.Validate itself. Registration is the choke point every
// probe passes through, so a manifest that declares a write cannot reach a
// runner by any route.
//
// Unexported (Phase 36 part 2): only BuiltIn registers a probe (Q25), and
// the source scan that held it while this was exported was evaded by an
// interface whose parameter is an alias of Probe, and by a generic one —
// both found by the re-audit of part 1. Unexported, no other package can
// name it by any route; TestOnlyBuiltInRegistersAProbe remains the
// backstop inside this package.
func (c *Catalogue) register(probe Probe) error {
	manifest := probe.Manifest()
	if err := manifest.Validate(); err != nil {
		return fmt.Errorf("refusing to register a probe: %w", err)
	}
	if _, exists := c.probes[manifest.ID]; exists {
		return fmt.Errorf(
			"probe %q is already registered; two probes with one id would make "+
				"a reading ambiguous about what took it", manifest.ID)
	}
	c.probes[manifest.ID] = probe
	return nil
}

// Get returns a probe by id.
func (c *Catalogue) Get(id string) (Probe, bool) {
	probe, found := c.probes[id]
	return probe, found
}

// Manifests returns every registered manifest, sorted by id, for
// `culprit probe --list` and `GET /probes`.
func (c *Catalogue) Manifests() []model.ProbeManifest {
	manifests := make([]model.ProbeManifest, 0, len(c.probes))
	for _, probe := range c.probes {
		manifests = append(manifests, probe.Manifest())
	}
	sort.Slice(manifests, func(i, j int) bool { return manifests[i].ID < manifests[j].ID })
	return manifests
}

// IDs returns every registered probe id, sorted.
func (c *Catalogue) IDs() []string {
	ids := make([]string, 0, len(c.probes))
	for id := range c.probes {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

// Len reports how many probes are registered.
func (c *Catalogue) Len() int { return len(c.probes) }

// builtIn is the core catalogue of §3 Phase 31 field 4, in the order that
// field lists them.
func builtIn() []Probe {
	return []Probe{
		dnsResolve{},
		tcpConnect{},
		tlsValidity{},
		httpReachable{},
		httpRouteConformance{},
		httpSchemaConformance{},
		authTokenShape{},
		authPropagation{},
		dbConnect{},
		dbSchemaConformance{},
		configPresent{},
		depVersion{},
		edgeImpedance{},
		// Phase 36 part 1.
		httpLatency{},
	}
}

// BuiltIn returns a catalogue of the core probes.
//
// It panics on a registration failure, which can only mean a built-in
// manifest is invalid — a programming error caught by
// TestBuiltInCatalogueRegisters, not a condition a caller can handle.
func BuiltIn() *Catalogue {
	catalogue := NewCatalogue()
	for _, probe := range builtIn() {
		if err := catalogue.register(probe); err != nil {
			panic(fmt.Sprintf("built-in probe catalogue is invalid: %v", err))
		}
	}
	return catalogue
}
