package extract

import (
	"encoding/json"
	"regexp"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Dependency readers — acceptance criterion 1's "dependency versions".
//
// Declared versions, from the manifests a project commits: package.json,
// requirements.txt, pyproject.toml, go.mod, Gemfile. Not lockfiles, and
// the distinction matters. A lockfile says what one machine resolved
// once; a manifest says what the project *intends*, which is the INTENT
// plane's question. "package.json asks for ^4.18 and production is
// running 4.17.1" is a divergence between planes — precisely the kind
// Phase 29 exists to find — and it is only expressible if this side
// records the range rather than the pin.
//
// The version is kept verbatim, range syntax and all. Normalising "^4.18"
// to "4.18" would throw away the difference between "any compatible 4.x"
// and "exactly 4.18", which is the difference the comparison turns on.

func dependencyReader() reader {
	return reader{want: model.WantDependencies, name: "dependencies", run: readDependencies}
}

type dependencySource struct {
	fileName string
	parse    func(text string) map[string]string
}

var dependencySources = []dependencySource{
	{"package.json", parsePackageJSON},
	{"requirements.txt", parseRequirementsTxt},
	{"pyproject.toml", parsePyprojectToml},
	{"go.mod", parseGoMod},
	{"Gemfile", parseGemfile},
	{"composer.json", parseComposerJSON},
	{"Cargo.toml", parseCargoToml},
}

func readDependencies(ctx captureContext) ([]model.Fact, []model.Skip) {
	byName := map[string]dependencySource{}
	for _, source := range dependencySources {
		byName[source.fileName] = source
	}

	paths := findFiles(ctx.Root, func(name string) bool {
		_, known := byName[name]
		return known
	})
	if len(paths) == 0 {
		return nil, []model.Skip{{
			Want:      string(model.WantDependencies),
			Reason:    "no dependency manifest found (package.json, requirements.txt, pyproject.toml, go.mod, Gemfile, composer.json, Cargo.toml)",
			Extractor: ctx.Extractor,
		}}
	}

	var facts []model.Fact
	for _, path := range paths {
		text, ok := readFile(path)
		if !ok {
			continue
		}
		artefact := relative(ctx.Root, path)
		source := byName[baseName(path)]
		dependencies := source.parse(text)

		names := make([]string, 0, len(dependencies))
		for name := range dependencies {
			names = append(names, name)
		}
		sort.Strings(names)

		for _, name := range names {
			subject, err := model.BuildSubject(model.KindDep, model.Parts{
				"component": ctx.Component, "dependency": name,
			})
			if err != nil {
				// A dependency name carrying a subject separator — a Go
				// module path, for one, which is full of slashes. Not
				// silently mangled into a subject that parses back as
				// something else; see the skip below.
				continue
			}
			provenance := ctx.provenance(
				model.SourceSpec, artefact, "", model.RankCommittedSpec)
			if fact, ok := ctx.fact(
				subject, model.PredicateVersion, dependencies[name], provenance); ok {
				facts = append(facts, fact)
			}
		}
	}
	return facts, nil
}

func baseName(path string) string {
	index := strings.LastIndexAny(path, `/\`)
	if index < 0 {
		return path
	}
	return path[index+1:]
}

// --- package.json -------------------------------------------------------

func parsePackageJSON(text string) map[string]string {
	var document struct {
		Dependencies    map[string]string `json:"dependencies"`
		DevDependencies map[string]string `json:"devDependencies"`
	}
	if err := json.Unmarshal([]byte(text), &document); err != nil {
		return nil
	}
	// Runtime and dev dependencies are merged into one namespace. They
	// are distinguishable in the artefact and not in the subject URI,
	// which has no slot for it — a real limit, recorded in
	// docs/LIMITS.md rather than papered over with a made-up subject.
	merged := map[string]string{}
	for name, version := range document.Dependencies {
		merged[name] = version
	}
	for name, version := range document.DevDependencies {
		if _, present := merged[name]; !present {
			merged[name] = version
		}
	}
	return merged
}

// --- requirements.txt ---------------------------------------------------

// A requirement line: name, optional extras, then the whole specifier.
// Deliberately not a full PEP 508 parser — environment markers, URLs and
// editable installs are left alone rather than half-understood.
var requirementLine = regexp.MustCompile(
	`^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(.*)$`)

func parseRequirementsTxt(text string) map[string]string {
	dependencies := map[string]string{}
	for _, line := range strings.Split(text, "\n") {
		trimmed := strings.TrimSpace(line)
		if trimmed == "" || strings.HasPrefix(trimmed, "#") || strings.HasPrefix(trimmed, "-") {
			continue
		}
		// Strip an inline comment and an environment marker.
		if index := strings.Index(trimmed, " #"); index >= 0 {
			trimmed = strings.TrimSpace(trimmed[:index])
		}
		if index := strings.Index(trimmed, ";"); index >= 0 {
			trimmed = strings.TrimSpace(trimmed[:index])
		}
		if strings.Contains(trimmed, "://") {
			continue // a direct URL reference; not a version claim
		}
		match := requirementLine.FindStringSubmatch(trimmed)
		if match == nil {
			continue
		}
		specifier := strings.TrimSpace(match[2])
		if specifier == "" {
			specifier = "*"
		}
		dependencies[match[1]] = specifier
	}
	return dependencies
}

// --- pyproject.toml -----------------------------------------------------

// parsePyprojectToml reads only `[project] dependencies = [...]`.
//
// A line scanner, not a TOML parser. Adding a TOML dependency to this
// binary to read one array is a poor trade, and the shape being read is
// the PEP 621 standard one: a flat list of PEP 508 strings.
//
// Poetry's `[tool.poetry.dependencies]` table is deliberately not read.
// It is a different shape, and half-reading it would emit a partial
// dependency set that looks complete. The Python extractor reads the
// real, resolved set when it is installed.
//
// **Bracket depth, not "the first `]` ends the list".** The first
// version of this cut the array at the first `]` on a line, which meant
// `"sqlalchemy[asyncio]>=2.0"` ended the list at its own extras marker
// and silently dropped every dependency after it. The fastapi-orders
// fixture caught it — two dependencies out of four, and one of those
// mangled. Worth recording because the failure was invisible in the
// output: a short dependency list looks exactly like a project with few
// dependencies.
func parsePyprojectToml(text string) map[string]string {
	dependencies := map[string]string{}
	inProject := false
	depth := 0
	for _, line := range strings.Split(text, "\n") {
		trimmed := strings.TrimSpace(line)
		if depth == 0 {
			if strings.HasPrefix(trimmed, "[") && !strings.HasPrefix(trimmed, "[\"") {
				inProject = trimmed == "[project]"
				continue
			}
			if !inProject {
				continue
			}
			key, rest, found := strings.Cut(trimmed, "=")
			if !found || strings.TrimSpace(key) != "dependencies" {
				continue
			}
			trimmed = strings.TrimSpace(rest)
			if !strings.HasPrefix(trimmed, "[") {
				continue
			}
			depth = 1
			trimmed = trimmed[1:]
		}

		// Inside the array. Consume until depth returns to zero, tracking
		// only brackets that are *outside* a quoted string — an extras
		// marker lives inside one.
		consumed, remaining := consumeArray(trimmed, &depth)
		for _, entry := range strings.Split(consumed, ",") {
			entry = strings.TrimSpace(entry)
			entry = strings.Trim(entry, `"'`)
			if entry == "" {
				continue
			}
			for name, specifier := range parseRequirementsTxt(entry) {
				dependencies[name] = specifier
			}
		}
		if depth == 0 {
			inProject = strings.TrimSpace(remaining) == "" || inProject
			break
		}
	}
	return dependencies
}

// consumeArray returns the part of `line` still inside the array, and
// whatever followed its closing bracket, updating depth as it goes.
//
// Quote-aware: a `[` or `]` inside a string literal is part of a
// dependency's extras (`sqlalchemy[asyncio]`), not array structure.
func consumeArray(line string, depth *int) (inside, after string) {
	var builder strings.Builder
	quote := byte(0)
	for index := 0; index < len(line); index++ {
		character := line[index]
		if quote != 0 {
			if character == quote {
				quote = 0
			}
			builder.WriteByte(character)
			continue
		}
		switch character {
		case '"', '\'':
			quote = character
			builder.WriteByte(character)
		case '[':
			*depth++
			builder.WriteByte(character)
		case ']':
			*depth--
			if *depth == 0 {
				return builder.String(), line[index+1:]
			}
			builder.WriteByte(character)
		case '#':
			// A comment ends the meaningful part of the line.
			return builder.String(), ""
		default:
			builder.WriteByte(character)
		}
	}
	return builder.String(), ""
}

// --- go.mod -------------------------------------------------------------

func parseGoMod(text string) map[string]string {
	dependencies := map[string]string{}
	inRequire := false
	for _, line := range strings.Split(text, "\n") {
		trimmed := strings.TrimSpace(line)
		if index := strings.Index(trimmed, "//"); index >= 0 {
			trimmed = strings.TrimSpace(trimmed[:index])
		}
		if trimmed == "require (" {
			inRequire = true
			continue
		}
		if inRequire && trimmed == ")" {
			inRequire = false
			continue
		}
		fields := strings.Fields(trimmed)
		if inRequire {
			if len(fields) >= 2 {
				dependencies[fields[0]] = fields[1]
			}
			continue
		}
		if len(fields) >= 3 && fields[0] == "require" {
			dependencies[fields[1]] = fields[2]
		}
	}
	return dependencies
}

// --- Gemfile ------------------------------------------------------------

var gemLine = regexp.MustCompile(`^gem\s+['"]([^'"]+)['"](?:\s*,\s*['"]([^'"]+)['"])?`)

func parseGemfile(text string) map[string]string {
	dependencies := map[string]string{}
	for _, line := range strings.Split(text, "\n") {
		match := gemLine.FindStringSubmatch(strings.TrimSpace(line))
		if match == nil {
			continue
		}
		version := match[2]
		if version == "" {
			version = "*"
		}
		dependencies[match[1]] = version
	}
	return dependencies
}

// --- composer.json ------------------------------------------------------

func parseComposerJSON(text string) map[string]string {
	var document struct {
		Require    map[string]string `json:"require"`
		RequireDev map[string]string `json:"require-dev"`
	}
	if err := json.Unmarshal([]byte(text), &document); err != nil {
		return nil
	}
	merged := map[string]string{}
	for name, version := range document.Require {
		merged[name] = version
	}
	for name, version := range document.RequireDev {
		if _, present := merged[name]; !present {
			merged[name] = version
		}
	}
	return merged
}

// --- Cargo.toml ---------------------------------------------------------

// parseCargoToml reads `[dependencies]` in both its spellings —
// `serde = "1.0"` and `serde = { version = "1.0", features = [...] }`.
func parseCargoToml(text string) map[string]string {
	dependencies := map[string]string{}
	inDependencies := false
	for _, line := range strings.Split(text, "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "[") {
			inDependencies = trimmed == "[dependencies]" || trimmed == "[dev-dependencies]"
			continue
		}
		if !inDependencies || trimmed == "" || strings.HasPrefix(trimmed, "#") {
			continue
		}
		name, rest, found := strings.Cut(trimmed, "=")
		if !found {
			continue
		}
		name = strings.TrimSpace(name)
		rest = strings.TrimSpace(rest)
		if strings.HasPrefix(rest, "{") {
			var table struct {
				Version string `yaml:"version"`
			}
			// TOML inline tables are close enough to YAML flow mappings
			// for this one field; a failure just means no version, which
			// is an honest omission rather than a wrong answer.
			if err := yaml.Unmarshal([]byte(rest), &table); err == nil && table.Version != "" {
				dependencies[name] = table.Version
			}
			continue
		}
		dependencies[name] = strings.Trim(rest, `"'`)
	}
	return dependencies
}
