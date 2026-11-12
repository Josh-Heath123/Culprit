// Package extract orchestrates intent extraction (Phase 28, D3).
//
// The shape of the thing, before the details. `culprit intent` needs
// facts about what a system is *supposed* to do. Those come from three
// places, in this preference order (.claude/rules/model.md):
//
//  1. Machine-readable declarations that already exist — OpenAPI
//     documents, migration files, lockfiles, .env.example. Read here, in
//     Go, with no plugin and nothing installed.
//  2. Runtime introspection of the application — `app.openapi()`,
//     SQLAlchemy metadata. Only the project's own virtualenv can do this,
//     so it happens in a subprocess extractor (D3).
//  3. Thin language-specific static extraction, for what neither of the
//     above gives — chiefly client call sites.
//
// This orchestrator never parses application code itself. That is D3's
// central claim and the reason the polyglot problem is tractable at all:
// each ecosystem contributes a small extractor in its own language,
// rather than this binary growing a static analyser per language.
package extract

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// ManifestVersion is the one shape this loader understands, matching
// api/app/model/manifest.py's MANIFEST_VERSION.
const ManifestVersion = 1

// Manifest is culprit.yaml as this binary needs it.
//
// Its top-level keys are the API's model's too (manifest_keys.json), and
// since Phase 37 part 1's close-out an unknown one is refused, as the API
// refuses it: a mistyped `budgets:` silently ignored is a check that looks
// like a gate and isn't. (Until then this loader ignored unknown keys, so
// that a CLI older than its server would still run; the shared key list,
// held equal in both, is what replaces that.) Within a section, fields
// this binary does not read are still tolerated.
type Manifest struct {
	Version    int                 `yaml:"version"`
	Components []ManifestComponent `yaml:"components"`
	Extract    ExtractConfig       `yaml:"extract"`
	// Phase 29's check-time sections. Parsed and validated here,
	// consumed by internal/diverge and internal/severity — see policy.go.
	Invariants        []Invariant        `yaml:"invariants"`
	Suppress          []Suppression      `yaml:"suppress"`
	SeverityOverrides []SeverityOverride `yaml:"severity_overrides"`
	// Phase 36: how fast a subject must be. See budgets.go.
	Budgets []Budget `yaml:"budgets"`
	// Phase 30: how to reach each environment, and what culprit may look
	// at there. See environments.go.
	Environments map[string]EnvironmentSpec `yaml:"environments"`
	// Phase 31: which probes run, how long they may take, and where they
	// apply. Capabilities are not configurable here — they belong to the
	// probe's manifest and the environment's grants. See probes.go.
	Probes map[string]ProbeSpec `yaml:"probes"`

	// Isolation bounds `culprit diagnose` (Phase 32 field 10).
	Isolation IsolationSpec `yaml:"isolation"`
}

// ManifestComponent is one component. Only the fields extraction and
// comparison need.
type ManifestComponent struct {
	Name        string `yaml:"name"`
	Kind        string `yaml:"kind"`
	DisplayName string `yaml:"display_name"`
	// Connections give severity its graph (Phase 29). `culprit intent`
	// ignores them; `culprit check` cannot work without them, because
	// "does this subject lie on a request path" is the whole difference
	// between `breaks_request_path` and `cosmetic`.
	Connections []ManifestConnection `yaml:"connections"`
}

// ExtractConfig is the `extract:` section (field 10): extractor commands
// and per-component source roots.
//
//	extract:
//	  extractors:
//	    - name: python
//	      command: ["uv", "run", "culprit-extract-python"]
//	    - name: node
//	      command: ["npx", "--no-install", "culprit-extract-node"]
//	  components:
//	    orders-api:
//	      root: api
//	      extractors: [python]
//	    web:
//	      root: frontend
//	      extractors: [node]
//
// **A component with no entry here is not extracted**, and the report
// says so by name. That is the opposite of the first thing tried, and
// the fixture corpus is what changed it: defaulting an undeclared
// component's root to the manifest directory meant every reader ran once
// per component over the same tree, so `orders-db` — a database, with no
// source of its own — was credited with the API's routes, config keys and
// Alembic head. Every fact in the capture existed twice, attributed to
// two different components, one of them wrongly.
//
// Duplicated facts are not a cosmetic problem here. Comparison in Phase
// 29 is subject equality, so a wrongly-attributed fact is a subject that
// will be compared against something it has nothing to do with. A skip
// naming the component and saying what to add is strictly better than a
// confident wrong answer.
type ExtractConfig struct {
	Extractors []ExtractorSpec                   `yaml:"extractors"`
	Components map[string]ComponentExtractConfig `yaml:"components"`
}

// ExtractorSpec names one plugin command.
type ExtractorSpec struct {
	// Name is how a component's `extractors:` list refers to this one.
	Name string `yaml:"name"`
	// Command is argv, not a shell string. No shell is involved at any
	// point: a manifest is a committed file, and `command: "rm -rf /
	// # &&"` going through a shell would make culprit.yaml an
	// arbitrary-execution vector for anyone who can open a pull request.
	// argv still executes what it names — see docs/EXTRACTOR_PROTOCOL.md
	// on trust — but it executes exactly and only that.
	Command []string `yaml:"command"`
	// Want optionally narrows what this extractor is asked for. Empty
	// means "ask for everything and let it skip what it cannot do",
	// which is the intended default: the extractor knows better than the
	// manifest author what it can answer.
	Want []string `yaml:"want"`
}

// ComponentExtractConfig is one component's extraction settings.
type ComponentExtractConfig struct {
	// Root is the source directory for this component, relative to the
	// manifest. Extractors are run with this as their `root`.
	Root string `yaml:"root"`
	// Extractors names entries from ExtractConfig.Extractors. Empty
	// means every declared extractor.
	Extractors []string `yaml:"extractors"`
	// Artefacts optionally points at files the built-in readers would
	// not find on their own — an OpenAPI document written somewhere
	// unusual, for instance.
	Artefacts []string `yaml:"artefacts"`
	// CallsTo names the component whose routes this component's HTTP
	// client calls hit.
	//
	// A client-call extractor cannot work this out: it sees
	// `fetch('/api/v2/users')` and has no way to know whose route that
	// is. So it emits the fact under the *caller's* component, and this
	// declaration is what lets the orchestrator rebuild the subject
	// against the callee — which is the only way a "the frontend calls
	// /api/v2, the API serves /api/v1" divergence can ever be found,
	// since comparison is subject equality and nothing else.
	//
	// Left unset, client-call facts stay under the caller. They are
	// still truthful inventory; they simply have nothing to compare
	// against.
	CallsTo string `yaml:"calls_to"`
}

// ManifestError is a manifest that cannot be loaded. Loud, and carrying
// the offending path: a manifest that half-loads produces a partial
// model, and a partial model produces confident findings about a system
// that is not the one described.
type ManifestError struct {
	Path    string
	Message string
}

func (e *ManifestError) Error() string { return e.Path + ": " + e.Message }

// TopLevelKeys are the keys a culprit.yaml may have at its top level: the
// yaml tags of Manifest, which shared/tests/manifest_keys.json holds equal
// to the API's model's fields.
func TopLevelKeys() []string {
	manifest := reflect.TypeOf(Manifest{})
	var keys []string
	for index := 0; index < manifest.NumField(); index++ {
		if tag, _, _ := strings.Cut(manifest.Field(index).Tag.Get("yaml"), ","); tag != "" && tag != "-" {
			keys = append(keys, tag)
		}
	}
	sort.Strings(keys)
	return keys
}

// unknownTopLevelKeys lists the top-level keys of a document that no field
// takes, including those a merge (`<<`) brings in. A key written as the
// string "<<" rather than a merge is unknown like any other.
func unknownTopLevelKeys(root *yaml.Node) []string {
	known := map[string]bool{}
	for _, key := range TopLevelKeys() {
		known[key] = true
	}
	var unknown []string
	var visit func(mapping *yaml.Node)
	visit = func(mapping *yaml.Node) {
		if mapping.Kind == yaml.AliasNode && mapping.Alias != nil {
			mapping = mapping.Alias
		}
		if mapping.Kind != yaml.MappingNode {
			return
		}
		for index := 0; index+1 < len(mapping.Content); index += 2 {
			key, value := mapping.Content[index], mapping.Content[index+1]
			if key.Tag == "!!merge" {
				if value.Kind == yaml.SequenceNode {
					for _, merged := range value.Content {
						visit(merged)
					}
				} else {
					visit(value)
				}
				continue
			}
			if !known[key.Value] {
				unknown = append(unknown, fmt.Sprintf("%q", key.Value))
			}
		}
	}
	visit(root)
	return unknown
}

// LoadManifest parses and validates a culprit.yaml.
func LoadManifest(path string) (*Manifest, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, &ManifestError{Path: path, Message: "cannot be read: " + err.Error()}
	}
	var manifest Manifest
	// One document, and only the top-level keys the API's model knows too
	// (shared/tests/manifest_keys.json): the two readers of one file must
	// read one schema (Phase 37 part 1 close-out). Until then a second
	// document was read by this loader and refused by the API, and an
	// unknown key — a mistyped `budgets:` — was silently ignored here.
	decoder := yaml.NewDecoder(bytes.NewReader(data))
	var document yaml.Node
	if err := decoder.Decode(&document); err != nil && !errors.Is(err, io.EOF) {
		return nil, &ManifestError{Path: path, Message: "not valid YAML: " + err.Error()}
	}
	var second yaml.Node
	if err := decoder.Decode(&second); !errors.Is(err, io.EOF) {
		return nil, &ManifestError{Path: path, Message: "holds more than one YAML document; culprit.yaml is one"}
	}
	if len(document.Content) > 0 {
		if unknown := unknownTopLevelKeys(document.Content[0]); len(unknown) > 0 {
			return nil, &ManifestError{Path: path, Message: fmt.Sprintf(
				"unknown top-level key %s; the keys culprit.yaml takes are %s",
				strings.Join(unknown, ", "), strings.Join(TopLevelKeys(), ", "))}
		}
		if err := document.Decode(&manifest); err != nil {
			return nil, &ManifestError{Path: path, Message: "not valid YAML: " + err.Error()}
		}
	}
	if manifest.Version == 0 {
		manifest.Version = ManifestVersion
	}
	if manifest.Version != ManifestVersion {
		return nil, &ManifestError{Path: path, Message: fmt.Sprintf(
			"unsupported culprit.yaml version %d (this build understands version %d)",
			manifest.Version, ManifestVersion)}
	}
	if err := manifest.validate(); err != nil {
		return nil, &ManifestError{Path: path, Message: err.Error()}
	}
	if err := manifest.validatePolicy(); err != nil {
		return nil, &ManifestError{Path: path, Message: err.Error()}
	}
	if err := manifest.validateBudgets(); err != nil {
		return nil, &ManifestError{Path: path, Message: err.Error()}
	}
	if err := manifest.validateEnvironments(); err != nil {
		return nil, &ManifestError{Path: path, Message: err.Error()}
	}
	if err := manifest.validateIsolation(); err != nil {
		return nil, &ManifestError{Path: path, Message: err.Error()}
	}
	if err := manifest.validateProbes(); err != nil {
		return nil, &ManifestError{Path: path, Message: err.Error()}
	}
	return &manifest, nil
}

func (m *Manifest) validate() error {
	seen := map[string]bool{}
	for _, component := range m.Components {
		if strings.TrimSpace(component.Name) == "" {
			return fmt.Errorf("a component has no name")
		}
		if seen[component.Name] {
			return fmt.Errorf("duplicate component name: %s", component.Name)
		}
		seen[component.Name] = true
	}

	names := map[string]bool{}
	for _, spec := range m.Extract.Extractors {
		if strings.TrimSpace(spec.Name) == "" {
			return fmt.Errorf("extract.extractors: an entry has no name")
		}
		if len(spec.Command) == 0 {
			return fmt.Errorf("extract.extractors.%s: command is empty", spec.Name)
		}
		if names[spec.Name] {
			return fmt.Errorf("extract.extractors: duplicate name %s", spec.Name)
		}
		names[spec.Name] = true
	}

	// A component's extract entry naming a component that does not exist
	// is refused rather than ignored. Ignoring it means the author
	// believes a source root is being scanned that is not, and every
	// fact they expected is simply absent from the report — which reads
	// as "nothing wrong there".
	for name, config := range m.Extract.Components {
		if !seen[name] {
			return fmt.Errorf(
				"extract.components.%s: no component named %s is declared in this file", name, name)
		}
		for _, extractor := range config.Extractors {
			if !names[extractor] {
				return fmt.Errorf(
					"extract.components.%s: no extractor named %s is declared in extract.extractors",
					name, extractor)
			}
		}
		// Refused rather than ignored, for the same reason as above: a
		// calls_to pointing at nothing means the retarget silently does
		// not happen and every client-call fact lands on the wrong
		// subject, comparing against nothing at all.
		if config.CallsTo != "" && !seen[config.CallsTo] {
			return fmt.Errorf(
				"extract.components.%s: calls_to names %s, which is not a component in this file",
				name, config.CallsTo)
		}
	}
	return nil
}

// Targets is one component's resolved extraction plan: where its source
// is, and which extractors to run over it.
type Target struct {
	Component string
	Kind      string
	// Root is absolute.
	Root       string
	Extractors []ExtractorSpec
	Artefacts  []string
	CallsTo    string
}

// Targets resolves the manifest into one Target per component, in the
// manifest's own order.
//
// baseDir is the directory the manifest lives in; every relative path in
// the file is resolved against it, not against the process's working
// directory. Running `culprit intent -f ../other/culprit.yaml` from
// anywhere must produce the same facts.
func (m *Manifest) Targets(baseDir string) []Target {
	byName := map[string]ExtractorSpec{}
	for _, spec := range m.Extract.Extractors {
		byName[spec.Name] = spec
	}

	targets := make([]Target, 0, len(m.Components))
	for _, component := range m.Components {
		config, declared := m.Extract.Components[component.Name]
		if !declared {
			// Recorded as a target with no root so Run() can report it
			// by name rather than silently returning fewer facts. See
			// ExtractConfig's own comment for why this is not extracted
			// from the manifest directory instead.
			targets = append(targets, Target{Component: component.Name, Kind: component.Kind})
			continue
		}

		root := baseDir
		if config.Root != "" {
			root = filepath.Join(baseDir, filepath.FromSlash(config.Root))
		}

		var specs []ExtractorSpec
		if len(config.Extractors) == 0 {
			specs = append(specs, m.Extract.Extractors...)
		} else {
			for _, name := range config.Extractors {
				specs = append(specs, byName[name])
			}
		}

		artefacts := make([]string, 0, len(config.Artefacts))
		for _, artefact := range config.Artefacts {
			artefacts = append(artefacts, filepath.Join(baseDir, filepath.FromSlash(artefact)))
		}

		targets = append(targets, Target{
			Component:  component.Name,
			Kind:       component.Kind,
			Root:       root,
			Extractors: specs,
			Artefacts:  artefacts,
			CallsTo:    config.CallsTo,
		})
	}
	return targets
}

// Wants returns the wants this extractor should be asked for, defaulting
// to everything.
func (s ExtractorSpec) Wants() []model.Want {
	if len(s.Want) == 0 {
		return model.AllWants
	}
	wants := make([]model.Want, 0, len(s.Want))
	for _, want := range s.Want {
		wants = append(wants, model.Want(want))
	}
	sort.Slice(wants, func(i, j int) bool { return wants[i] < wants[j] })
	return wants
}

// sortStrings is sort.Strings, named so policy.go can use it without
// importing sort for one call.
func sortStrings(values []string) { sort.Strings(values) }
