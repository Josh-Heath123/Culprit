package extract

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The OpenAPI / Swagger reader.
//
// A committed OpenAPI document is confidence rank 80 (§2.4, "committed
// machine-readable spec") — below runtime introspection, because a
// checked-in openapi.json can be stale, and above anything static.
// That ordering is the whole reason both exist: when the committed
// document and the running app disagree, Phase 29 reports an
// intent_conflict, which is very often itself the bug.
//
// Both OpenAPI 3.x (`paths` with `requestBody`) and Swagger 2.0
// (`paths` with `parameters[in=body]`) are read, because a real
// repository has whichever its framework emitted five years ago.

// httpMethods are the keys inside a path item that are operations. Every
// other key (`parameters`, `summary`, `$ref`, `servers`) is not.
var httpMethods = []string{"get", "put", "post", "delete", "options", "head", "patch", "trace"}

type openAPIDocument struct {
	OpenAPI string                            `yaml:"openapi" json:"openapi"`
	Swagger string                            `yaml:"swagger" json:"swagger"`
	Paths   map[string]map[string]interface{} `yaml:"paths" json:"paths"`
}

func openAPIReader() reader {
	return reader{
		want: model.WantHTTPRoutes,
		name: "openapi",
		run:  readOpenAPI,
	}
}

func isOpenAPIFileName(name string) bool {
	lower := strings.ToLower(name)
	base := strings.TrimSuffix(strings.TrimSuffix(strings.TrimSuffix(
		lower, ".json"), ".yaml"), ".yml")
	if base == lower {
		return false // not one of the three extensions
	}
	return base == "openapi" || base == "swagger" || base == "openapi.schema" ||
		strings.HasSuffix(base, ".openapi") || base == "api"
}

func readOpenAPI(ctx captureContext) ([]model.Fact, []model.Skip) {
	paths := findFiles(ctx.Root, isOpenAPIFileName)
	var facts []model.Fact
	var documents int

	for _, path := range paths {
		text, ok := readFile(path)
		if !ok {
			continue
		}
		document, ok := parseOpenAPI(text)
		if !ok || len(document.Paths) == 0 {
			// A file called `api.yaml` that is not an OpenAPI document
			// is not an error and not a skip — it is simply not this
			// reader's business. Reporting it would fill every report
			// with noise about files that were never claims about HTTP.
			continue
		}
		documents++
		facts = append(facts, openAPIFacts(ctx, relative(ctx.Root, path), document)...)
	}

	if documents == 0 {
		return nil, []model.Skip{{
			Want:      string(model.WantHTTPRoutes),
			Reason:    "no OpenAPI or Swagger document found under " + relative(ctx.Root, ctx.Root),
			Extractor: ctx.Extractor,
		}}
	}
	return facts, nil
}

// parseOpenAPI accepts JSON or YAML. YAML is a superset of JSON, so one
// parser would do — but json.Unmarshal gives far better errors on a
// malformed .json file, and this reader meets both constantly.
func parseOpenAPI(text string) (openAPIDocument, bool) {
	var document openAPIDocument
	trimmed := strings.TrimSpace(text)
	if strings.HasPrefix(trimmed, "{") {
		if err := json.Unmarshal([]byte(text), &document); err != nil {
			return document, false
		}
	} else if err := yaml.Unmarshal([]byte(text), &document); err != nil {
		return document, false
	}
	if document.OpenAPI == "" && document.Swagger == "" {
		return document, false
	}
	return document, true
}

func openAPIFacts(ctx captureContext, artefact string, document openAPIDocument) []model.Fact {
	// Sorted, not map order: acceptance criterion 2 is that two runs
	// over an unchanged tree produce byte-identical output, and Go
	// randomises map iteration on purpose.
	routes := make([]string, 0, len(document.Paths))
	for route := range document.Paths {
		routes = append(routes, route)
	}
	sort.Strings(routes)

	var facts []model.Fact
	for _, route := range routes {
		item := document.Paths[route]
		for _, method := range httpMethods {
			operation, present := item[method]
			if !present {
				continue
			}
			subject, err := model.BuildSubject(model.KindHTTP, model.Parts{
				"component": ctx.Component,
				"method":    method,
				"path":      route,
			})
			if err != nil {
				// A path the subject builder refuses is reported by not
				// being emitted, rather than by a subject that parses
				// back into something else. See subjects.go.
				continue
			}
			locator := fmt.Sprintf("$.paths.%s.%s", route, method)
			provenance := ctx.provenance(
				model.SourceSpec, artefact, locator, model.RankCommittedSpec)

			// The route exists. `value` is the *original* path, not the
			// canonical one: the subject already carries the canonical
			// form, and a report that says "/orders/{id}" is far more
			// use to a human than one that says "/orders/{}".
			if fact, ok := ctx.fact(subject, model.PredicateExists,
				map[string]any{"path": route, "method": strings.ToUpper(method)},
				provenance); ok {
				facts = append(facts, fact)
			}

			details, _ := operation.(map[string]interface{})
			facts = append(facts, operationFacts(ctx, subject, locator, artefact, details)...)
		}
	}
	return facts
}

// operationFacts turns one operation into the aspect facts Phase 29 will
// compare: what it accepts and what it returns.
//
// Only *shape-level* claims, deliberately: the set of response status
// codes, and whether a request body is required and what content types
// it takes. Not the full JSON Schema — D6 says Culprit models
// interfaces, not implementations, and a whole schema tree in a fact
// value makes every trivial field reordering read as a divergence.
func operationFacts(
	ctx captureContext, subject, locator, artefact string, operation map[string]interface{},
) []model.Fact {
	if operation == nil {
		return nil
	}
	provenance := ctx.provenance(model.SourceSpec, artefact, locator, model.RankCommittedSpec)
	var facts []model.Fact

	if responses, ok := operation["responses"].(map[string]interface{}); ok {
		codes := make([]string, 0, len(responses))
		for code := range responses {
			codes = append(codes, code)
		}
		sort.Strings(codes)
		if fact, ok := ctx.fact(
			subject, model.PredicateStatusCodes, codes, provenance); ok {
			facts = append(facts, fact)
		}
	}

	body, contentTypes, required := requestBody(operation)
	if body {
		aspect, err := aspectSubject(subject, "request.body")
		if err == nil {
			value := map[string]any{"required": required}
			if len(contentTypes) > 0 {
				value["content_types"] = contentTypes
			}
			if fact, ok := ctx.fact(
				aspect, model.PredicateRequestSchema, value, provenance); ok {
				facts = append(facts, fact)
			}
		}
	}
	return facts
}

// requestBody reads the OpenAPI 3 and Swagger 2 spellings of the same
// thing, and reports whether there is one at all.
func requestBody(operation map[string]interface{}) (present bool, contentTypes []string, required bool) {
	if body, ok := operation["requestBody"].(map[string]interface{}); ok {
		present = true
		required, _ = body["required"].(bool)
		if content, ok := body["content"].(map[string]interface{}); ok {
			for contentType := range content {
				contentTypes = append(contentTypes, contentType)
			}
			sort.Strings(contentTypes)
		}
		return present, contentTypes, required
	}
	// Swagger 2.0: a `parameters` entry with `in: body`.
	parameters, ok := operation["parameters"].([]interface{})
	if !ok {
		return false, nil, false
	}
	for _, entry := range parameters {
		parameter, ok := entry.(map[string]interface{})
		if !ok {
			continue
		}
		if location, _ := parameter["in"].(string); location == "body" {
			present = true
			required, _ = parameter["required"].(bool)
		}
	}
	return present, nil, required
}

// aspectSubject re-builds a subject with an aspect attached, going back
// through the builder rather than concatenating a "#".
//
// This is the rule from .claude/rules/model.md applied where it is least
// convenient and most necessary: a hand-appended aspect is exactly how
// two sources end up producing subjects that differ by a character and
// never compare.
func aspectSubject(subject, aspect string) (string, error) {
	kind, parts, err := model.ParseSubject(subject)
	if err != nil {
		return "", err
	}
	parts["aspect"] = aspect
	return model.BuildSubject(kind, parts)
}
