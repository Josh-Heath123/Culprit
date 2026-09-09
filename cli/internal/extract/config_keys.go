package extract

import (
	"path/filepath"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Config-key readers: `.env.example` and compose/k8s YAML.
//
// This is the reader where the config-value rule has teeth, so it is
// worth being explicit about what it does with what it reads.
//
// A `.env.example` is a *committed* file and its right-hand sides are
// placeholders by convention — but only by convention. People commit
// real values to them constantly, which is exactly why this reader
// classifies rather than copies: it calls model.ShapeOfString on the
// value and keeps only the ValueShape, a four-field closed struct with
// nowhere to put the string it just looked at. The value itself never
// leaves this function's stack.
//
// The same reader is therefore safe to point at a real `.env`, which
// Phase 30 will do for CONFIGURED capture. Nothing about it needs to
// change for that; only the plane does.

func dotenvReader() reader {
	return reader{want: model.WantConfigKeys, name: "dotenv", run: readDotenv}
}

// dotenvNames are the files read. A bare `.env` is deliberately absent:
// on the INTENT plane, "what keys does this system expect" is a claim a
// committed example file makes, and a developer's local `.env` is not a
// claim about anything. Reading it would also mean walking into a file
// full of real secrets on the strength of a comment promising we only
// keep the shape — a promise better kept by not opening it.
var dotenvNames = map[string]bool{
	".env.example":  true,
	".env.sample":   true,
	".env.template": true,
	".env.dist":     true,
	"env.example":   true,
}

func readDotenv(ctx captureContext) ([]model.Fact, []model.Skip) {
	paths := findFiles(ctx.Root, func(name string) bool { return dotenvNames[name] })
	if len(paths) == 0 {
		return nil, []model.Skip{{
			Want:      string(model.WantConfigKeys),
			Reason:    "no .env.example (or .sample/.template/.dist) found",
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
		for index, line := range strings.Split(text, "\n") {
			key, value, ok := parseDotenvLine(line)
			if !ok {
				continue
			}
			provenance := ctx.provenance(
				model.SourceSpec, artefact, lineLocator(index+1), model.RankCommittedSpec)
			// The shape, never the value. `value` goes out of scope here
			// and is not referenced again.
			shape := model.ShapeOfString(value)
			if fact, ok := ctx.configFact(key, shape, provenance); ok {
				facts = append(facts, fact)
			}
			// Separately: the key is expected to exist at all. A
			// `.env.example` entry is a declaration that the system
			// reads this key, which is the claim Phase 29 compares
			// against an environment that does not set it.
			subject, err := model.BuildSubject(model.KindConfig, model.Parts{
				"component": ctx.Component, "key": key,
			})
			if err != nil {
				continue
			}
			if fact, ok := ctx.fact(subject, model.PredicateExists, true, provenance); ok {
				facts = append(facts, fact)
			}
		}
	}
	return facts, nil
}

// parseDotenvLine reads one KEY=value line. Comments, blanks and
// anything without an `=` are skipped.
func parseDotenvLine(line string) (key, value string, ok bool) {
	trimmed := strings.TrimSpace(line)
	if trimmed == "" || strings.HasPrefix(trimmed, "#") {
		return "", "", false
	}
	trimmed = strings.TrimPrefix(trimmed, "export ")
	key, value, found := strings.Cut(trimmed, "=")
	if !found {
		return "", "", false
	}
	key = strings.TrimSpace(key)
	if key == "" || strings.ContainsAny(key, " \t/#") {
		return "", "", false
	}
	value = strings.TrimSpace(value)
	value = strings.Trim(value, `"'`)
	return key, value, true
}

func lineLocator(line int) string {
	return "L" + itoa(line)
}

func itoa(value int) string {
	if value == 0 {
		return "0"
	}
	var digits []byte
	for value > 0 {
		digits = append([]byte{byte('0' + value%10)}, digits...)
		value /= 10
	}
	return string(digits)
}

// --- compose / k8s -----------------------------------------------------

func composeReader() reader {
	return reader{want: model.WantConfigKeys, name: "compose", run: readCompose}
}

func isComposeFileName(name string) bool {
	lower := strings.ToLower(name)
	return lower == "docker-compose.yml" || lower == "docker-compose.yaml" ||
		lower == "compose.yml" || lower == "compose.yaml" ||
		strings.HasPrefix(lower, "docker-compose.") &&
			(strings.HasSuffix(lower, ".yml") || strings.HasSuffix(lower, ".yaml"))
}

type composeFile struct {
	Services map[string]composeService `yaml:"services"`
}

type composeService struct {
	Image string `yaml:"image"`
	// Compose accepts both a mapping and a list of "KEY=value" strings.
	// yaml.Node rather than a concrete type so both parse, and the
	// awkwardness lives in one place instead of failing on half the
	// compose files in the world.
	Environment yaml.Node `yaml:"environment"`
}

func readCompose(ctx captureContext) ([]model.Fact, []model.Skip) {
	paths := findFiles(ctx.Root, isComposeFileName)
	if len(paths) == 0 {
		return nil, []model.Skip{{
			Want:      string(model.WantConfigKeys),
			Reason:    "no docker-compose file found",
			Extractor: ctx.Extractor,
		}}
	}

	var facts []model.Fact
	for _, path := range paths {
		text, ok := readFile(path)
		if !ok {
			continue
		}
		var file composeFile
		if err := yaml.Unmarshal([]byte(text), &file); err != nil {
			continue
		}
		artefact := relative(ctx.Root, path)

		names := make([]string, 0, len(file.Services))
		for name := range file.Services {
			names = append(names, name)
		}
		sort.Strings(names)

		for _, name := range names {
			service := file.Services[name]
			// Compose services are only read for the component being
			// extracted. A compose file describes several components,
			// and attributing `postgres`'s environment keys to
			// `orders-api` would be a confidently wrong fact — worse
			// than no fact at all.
			if model.CanonicalComponent(name) != model.CanonicalComponent(ctx.Component) {
				continue
			}
			locator := "$.services." + name
			provenance := ctx.provenance(
				model.SourceSpec, artefact, locator, model.RankCommittedSpec)

			if service.Image != "" {
				subject, err := model.BuildSubject(model.KindImage, model.Parts{
					"component": ctx.Component,
				})
				if err == nil {
					if fact, ok := ctx.fact(
						subject, model.PredicateExists, service.Image, provenance); ok {
						facts = append(facts, fact)
					}
				}
			}

			for _, key := range composeEnvironmentKeys(&service.Environment) {
				subject, err := model.BuildSubject(model.KindConfig, model.Parts{
					"component": ctx.Component, "key": key,
				})
				if err != nil {
					continue
				}
				if fact, ok := ctx.fact(
					subject, model.PredicateExists, true, provenance); ok {
					facts = append(facts, fact)
				}
			}
		}
	}
	return facts, nil
}

// composeEnvironmentKeys reads keys out of either compose spelling,
// returning names only.
//
// Values are not read at all here, not even to classify them: a compose
// file's environment values are frequently `${DATABASE_URL}`
// interpolations whose shape would be the shape of the interpolation
// syntax rather than of anything real, and a shape that describes the
// wrong thing is worse than no shape.
func composeEnvironmentKeys(node *yaml.Node) []string {
	if node == nil || node.Kind == 0 {
		return nil
	}
	var keys []string
	switch node.Kind {
	case yaml.MappingNode:
		for index := 0; index+1 < len(node.Content); index += 2 {
			keys = append(keys, node.Content[index].Value)
		}
	case yaml.SequenceNode:
		for _, entry := range node.Content {
			key, _, found := strings.Cut(entry.Value, "=")
			if !found {
				key = entry.Value
			}
			if key != "" {
				keys = append(keys, key)
			}
		}
	}
	sort.Strings(keys)
	return keys
}

// --- alembic migration head -------------------------------------------

func migrationHeadReader() reader {
	return reader{want: model.WantDBSchema, name: "migration-head", run: readMigrationHead}
}

// readMigrationHead computes the Alembic head from the versions
// directory alone, with no alembic installed and no database.
//
// The head is the revision no other revision points at with
// down_revision. That is exactly how Alembic defines it, and computing
// it from the files means this works in a CI checkout with nothing set
// up — which is the whole point of artefact readers.
//
// More than one head is not an error here: Alembic genuinely supports
// branched heads, and reporting all of them is the honest answer. Two
// heads where a project expects one is a finding Phase 29 can make,
// and it can only make it if this reader does not silently pick one.
func readMigrationHead(ctx captureContext) ([]model.Fact, []model.Skip) {
	dirs := findMigrationDirs(ctx.Root)
	if len(dirs) == 0 {
		return nil, []model.Skip{{
			Want:      string(model.WantDBSchema),
			Reason:    "no alembic versions/ directory found; migration head unknown",
			Extractor: ctx.Extractor,
		}}
	}

	var facts []model.Fact
	for _, dir := range dirs {
		revisions, downRevisions := readAlembicRevisions(dir)
		if len(revisions) == 0 {
			continue
		}
		heads := make([]string, 0, 1)
		for revision := range revisions {
			if !downRevisions[revision] {
				heads = append(heads, revision)
			}
		}
		sort.Strings(heads)

		subject, err := model.BuildSubject(model.KindComponent, model.Parts{"name": ctx.Component})
		if err != nil {
			continue
		}
		provenance := ctx.provenance(
			model.SourceSpec, relative(ctx.Root, dir), "", model.RankCommittedSpec)
		if fact, ok := ctx.fact(subject, model.PredicateMigrationHead, heads, provenance); ok {
			facts = append(facts, fact)
		}
	}
	if len(facts) == 0 {
		return nil, []model.Skip{{
			Want:      string(model.WantDBSchema),
			Reason:    "an alembic versions/ directory was found but held no readable revisions",
			Extractor: ctx.Extractor,
		}}
	}
	return facts, nil
}

func findMigrationDirs(root string) []string {
	seen := map[string]bool{}
	var dirs []string
	for _, path := range findFiles(root, func(name string) bool {
		return strings.HasSuffix(name, ".py")
	}) {
		dir := filepath.Dir(path)
		if filepath.Base(dir) != "versions" || seen[dir] {
			continue
		}
		seen[dir] = true
		dirs = append(dirs, dir)
	}
	sort.Strings(dirs)
	return dirs
}

// readAlembicRevisions pulls `revision` and `down_revision` out of each
// migration file by line scan.
//
// A line scan, not a Python parse: this binary does not parse
// application code (D3), and an Alembic revision header is a fixed,
// generated shape — `revision: str = "abc123"` — not something a project
// writes freehand. When the shape is not that, the file contributes
// nothing rather than a guess.
func readAlembicRevisions(dir string) (revisions map[string]bool, downRevisions map[string]bool) {
	revisions = map[string]bool{}
	downRevisions = map[string]bool{}
	for _, path := range findFiles(dir, func(name string) bool {
		return strings.HasSuffix(name, ".py") && name != "__init__.py"
	}) {
		text, ok := readFile(path)
		if !ok {
			continue
		}
		for _, line := range strings.Split(text, "\n") {
			trimmed := strings.TrimSpace(line)
			if value, ok := alembicHeaderValue(trimmed, "revision"); ok {
				revisions[value] = true
			}
			if value, ok := alembicHeaderValue(trimmed, "down_revision"); ok {
				downRevisions[value] = true
			}
		}
	}
	return revisions, downRevisions
}

func alembicHeaderValue(line, name string) (string, bool) {
	if !strings.HasPrefix(line, name) {
		return "", false
	}
	rest := strings.TrimPrefix(line, name)
	// `revision: str = "x"` or `revision = "x"`. Anything else is not the
	// generated header and is left alone. Guarding on the next character
	// stops `revision_map = ...` matching `revision`.
	if rest == "" || (rest[0] != ':' && rest[0] != ' ' && rest[0] != '=') {
		return "", false
	}
	_, after, found := strings.Cut(rest, "=")
	if !found {
		return "", false
	}
	value := strings.TrimSpace(after)
	if !strings.HasPrefix(value, `"`) && !strings.HasPrefix(value, `'`) {
		return "", false // None, or a computed value
	}
	value = strings.Trim(value, `"'`)
	if value == "" {
		return "", false
	}
	return value, true
}
