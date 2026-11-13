// Package severity classifies a divergence from the system model
// (Phase 29, §2.5).
//
// **Deterministic, and derived from the graph — never a judgement and
// never an LLM.** §2.5 states the rule plainly: "a divergence on a
// subject that lies on a known request path is `breaks_request_path`;
// one on an unreferenced config key is `cosmetic`. It is never an LLM
// judgement." This package is that sentence, made executable.
//
// The graph is `culprit.yaml`'s components and their connections. An
// edge marked `on_request_path` is the author saying "a request passes
// through here"; a component reachable from an entry point along such
// edges is on the request path, and a fault there breaks requests. That
// is the whole model, and its shallowness is the point: a reader can
// check the answer by looking at their own manifest.
//
// # What it does when it does not know
//
// It returns `unknown`, and `unknown` ranks *above* `cosmetic` (see
// `Severity.Rank`). A tool that quietly files everything it cannot
// classify under "trivial" is a tool that hides its own blind spots,
// and the blind spots here are real: a manifest with no `criticality`
// anywhere gives this package nothing to work with, and it should say
// so rather than guess low.
package severity

import (
	"fmt"
	"sort"

	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Graph is the part of the system model severity needs.
type Graph struct {
	// onRequestPath is the set of components reachable from an entry
	// component along `on_request_path` edges, plus the entry points
	// themselves.
	onRequestPath map[string]bool
	// why records, per component, the path that put it there — so a
	// severity can explain itself instead of being asserted.
	why map[string]string
	// declared is every component in the manifest, used to tell "not on
	// the request path" from "not in the model at all".
	declared map[string]bool
	// referenced is every component some other component connects to.
	referenced map[string]bool
	// owners is, for each schema database, the components whose schema
	// facts are on it: the schema database rule's inverse (Q34).
	owners map[string][]string
}

// entryKinds are component kinds a request enters the system through.
//
// A `frontend` is the obvious one. A `service` with nothing pointing at
// it is also an entry point — that is what an externally-facing API
// looks like in a manifest that does not model the browser.
var entryKinds = map[string]bool{
	"frontend": true,
	"gateway":  true,
}

// BuildGraph walks the manifest's connections.
func BuildGraph(manifest *extract.Manifest) *Graph {
	graph := &Graph{
		onRequestPath: map[string]bool{},
		why:           map[string]string{},
		declared:      map[string]bool{},
		referenced:    map[string]bool{},
		owners:        map[string][]string{},
	}
	if manifest == nil {
		return graph
	}
	for _, component := range manifest.Components {
		database := manifest.SchemaDatabase(component.Name)
		if database != component.Name {
			graph.owners[database] = append(graph.owners[database], component.Name)
		}
	}

	outgoing := map[string][]extract.ManifestConnection{}
	for _, component := range manifest.Components {
		graph.declared[component.Name] = true
		outgoing[component.Name] = component.Connections
		for _, connection := range component.Connections {
			graph.referenced[connection.To] = true
		}
	}

	// Entry points: declared frontends and gateways, plus any component
	// nothing else connects to (an unreferenced service is where traffic
	// arrives, in a manifest that does not model the browser).
	var entries []string
	for _, component := range manifest.Components {
		if entryKinds[component.Kind] ||
			(!graph.referenced[component.Name] && len(component.Connections) > 0) {
			entries = append(entries, component.Name)
		}
	}
	sort.Strings(entries)

	// Breadth-first along on_request_path edges only. A `background`
	// edge is explicitly the author saying "a request does not wait on
	// this", so following it would classify an async consumer as
	// request-breaking — the exact over-reporting `criticality` exists
	// to prevent.
	for _, entry := range entries {
		graph.onRequestPath[entry] = true
		graph.why[entry] = fmt.Sprintf("%s is an entry point", entry)
		queue := []string{entry}
		for len(queue) > 0 {
			current := queue[0]
			queue = queue[1:]
			for _, connection := range outgoing[current] {
				if connection.Criticality != "on_request_path" {
					continue
				}
				if graph.onRequestPath[connection.To] {
					continue
				}
				graph.onRequestPath[connection.To] = true
				graph.why[connection.To] = fmt.Sprintf(
					"%s is on the request path from %s", connection.To, entry)
				queue = append(queue, connection.To)
			}
		}
	}
	return graph
}

// Classifier assigns severities, applying the manifest's overrides last.
type Classifier struct {
	graph     *Graph
	overrides []extract.SeverityOverride
	// referencedConfigKeys is the set of `config:` subjects some source
	// says the code actually reads. A key nothing reads is cosmetic
	// however important its component is — that is §2.5's own example.
	referencedConfigKeys map[string]bool
	// keysWithDefaults is the set of `config:` subjects some source says
	// the code has a fallback for. A key the code defaults cannot break a
	// request by being unset: the request is served, with the default.
	keysWithDefaults map[string]bool
}

// NewClassifier builds one from a manifest and the capture it will judge.
func NewClassifier(manifest *extract.Manifest, bundle model.CaptureBundle) *Classifier {
	classifier := &Classifier{
		graph:                BuildGraph(manifest),
		referencedConfigKeys: map[string]bool{},
		keysWithDefaults:     map[string]bool{},
	}
	if manifest != nil {
		classifier.overrides = manifest.SeverityOverrides
	}
	for _, fact := range bundle.Facts {
		if fact.Predicate == model.PredicateReadBy || fact.Predicate == model.PredicateCalls {
			classifier.referencedConfigKeys[fact.Subject] = true
		}
		if fact.Predicate == model.PredicateDefaultShape {
			classifier.keysWithDefaults[fact.Subject] = true
		}
	}
	return classifier
}

// Classify returns a severity and the reason for it.
//
// The reason is not decoration. A severity a reader cannot trace back to
// their own manifest is a severity they will not trust, and the first
// thing anyone does with a CI tool that fails their build is ask why.
func (c *Classifier) Classify(divergence model.Divergence) (model.Severity, string) {
	for _, override := range c.overrides {
		if override.Matches(divergence.Subject) {
			return model.Severity(override.Severity), fmt.Sprintf(
				"severity_overrides in culprit.yaml: %s", override.Reason)
		}
	}

	kind, parts, err := model.ParseSubject(divergence.Subject)
	if err != nil {
		return model.SeverityUnknown, "the subject could not be parsed"
	}
	component := parts["component"]

	switch kind {
	case model.KindHTTP:
		// A route is the request path, by definition — if the component
		// serving it is on one.
		if c.graph.onRequestPath[component] {
			return model.SeverityBreaksRequestPath, c.graph.why[component]
		}
		if !c.graph.declared[component] {
			return model.SeverityUnknown, fmt.Sprintf(
				"%s is not declared in culprit.yaml, so its place in the system is unknown",
				component)
		}
		return model.SeverityDegrades, fmt.Sprintf(
			"%s is declared but not reachable along an on_request_path edge", component)

	case model.KindConfig:
		// §2.5's own example: an unreferenced config key is cosmetic.
		// Checked before the graph, because a key nothing reads cannot
		// break a request however central its component is.
		if !c.referencedConfigKeys[divergence.Subject] {
			return model.SeverityCosmetic, "no source reports this key being read"
		}
		// Phase 30: a key set in both places, to a different *kind* of
		// value — a DSN in staging and a bare hostname in production, a
		// postgresql URL against a mysql one, or two different granted
		// values. That is worth a finding and it is not, by itself, proof
		// that a request breaks: which side is right is exactly what the
		// comparison cannot say. Only set-versus-unset (and set-but-empty,
		// which breaks a request the same way) goes on to the request-path
		// rules below.
		if !presenceDiffers(divergence) {
			if divergence.Predicate == capturePredicateValue {
				return model.SeverityDegrades,
					"the key is read and set in both, to different values"
			}
			return model.SeverityDegrades,
				"the key is read and set in both, but to a different kind of value"
		}
		// A key the code has a fallback for cannot break a request by
		// being unset — the request is served, with the default. It may
		// well be served *wrongly*, which is why this is `degrades` and
		// not `cosmetic`.
		//
		// Culprit found this on its own repository: `INGEST_RATE_LIMIT`
		// is read by the ingest gateway and missing from
		// `api/.env.example`, which is a real documentation gap and is
		// emphatically not a broken request path, because the code reads
		// it with a default of "600/minute". Ranking it alongside a
		// missing database URL would be the kind of over-reporting that
		// gets a tool's default threshold turned off.
		if c.keysWithDefaults[divergence.Subject] {
			return model.SeverityDegrades,
				"the key is read, but the code supplies a default, so an unset " +
					"key does not break the request path"
		}
		if c.graph.onRequestPath[component] {
			return model.SeverityBreaksRequestPath, fmt.Sprintf(
				"%s, and the key is read", c.graph.why[component])
		}
		if !c.graph.declared[component] {
			return model.SeverityUnknown, fmt.Sprintf(
				"%s is not declared in culprit.yaml", component)
		}
		return model.SeverityDegrades, fmt.Sprintf(
			"the key is read, but %s is not on the request path", component)

	case model.KindSchema:
		// A schema disagreement means the code expects a column the
		// migrations do not create: the query fails at runtime, on
		// whatever path uses it. Without knowing which component owns
		// the database this stays `degrades` rather than being inflated.
		database := parts["database"]
		for _, owner := range c.graph.owners[database] {
			if c.graph.onRequestPath[owner] {
				return model.SeverityBreaksRequestPath, fmt.Sprintf(
					"%s backs %s, which is on the request path", database, owner)
			}
		}
		return model.SeverityDegrades, "a schema mismatch fails the queries that use it"

	case model.KindDep:
		// Two environments running different installed versions of one
		// package is the textbook "works in staging" cause, and more than
		// cosmetic. It is still not proof a request breaks.
		if divergence.Kind == model.KindEnvVsEnv {
			return model.SeverityDegrades,
				"the two environments have different versions of this package installed"
		}
		// A dependency-version disagreement is real but rarely breaks a
		// request by itself.
		return model.SeverityCosmetic, "a declared dependency version, not a runtime path"

	case model.KindImage:
		// Phase 30. Two environments running different builds of one
		// component, or a running image that is not the one declared. It
		// explains a great many "works in staging" reports and breaks
		// nothing by itself, so it is `degrades` whatever the graph says.
		if divergence.Kind == model.KindEnvVsEnv {
			return model.SeverityDegrades, fmt.Sprintf(
				"the two environments run different builds of %s", component)
		}
		return model.SeverityDegrades, fmt.Sprintf(
			"%s is running an image other than the one declared", component)

	case model.KindComponent:
		// Phase 30: facts about a component as deployed — its live
		// migration version, and whether its endpoint resolves, accepts a
		// connection and presents a valid certificate.
		name := parts["name"]
		if !c.graph.declared[name] {
			return model.SeverityUnknown, fmt.Sprintf(
				"%s is not declared in culprit.yaml, so its place in the system is unknown", name)
		}
		if divergence.Predicate == capturePredicateTLS {
			// Which side is right is not something a comparison can say — a
			// self-signed staging certificate against a valid production
			// one is usually intended — so a certificate difference is
			// never ranked as a broken path on its own.
			return model.SeverityDegrades,
				"the certificate differs in class between the two sides"
		}
		if c.graph.onRequestPath[name] {
			return model.SeverityBreaksRequestPath, fmt.Sprintf(
				"%s, and this is a fact about it as deployed", c.graph.why[name])
		}
		return model.SeverityDegrades, fmt.Sprintf(
			"%s is declared but not reachable along an on_request_path edge", name)

	default:
		return model.SeverityUnknown, "no severity rule covers this subject kind"
	}
}

// The capture predicates severity has an opinion about. Spelled here
// rather than imported: internal/capture links the network stack, and
// severity sits inside `culprit check`'s pipeline, which must not.
const (
	capturePredicateValue = "value"
	capturePredicateTLS   = "tls_certificate"
)

// presenceDiffers reports whether a config finding is about whether the
// key is *set* — present against absent, or present-but-empty against
// populated — rather than about what it is set to.
//
// Everything that is not a shape or a granted value comparison is a
// presence question: an absence finding (`read_by`, `exists`) says one
// side lacks the key entirely.
func presenceDiffers(divergence model.Divergence) bool {
	left, right := divergence.Left.ValueShape, divergence.Right.ValueShape
	if left != nil && right != nil {
		if left.Present != right.Present {
			return true
		}
		return (left.LengthClass == model.LengthEmpty) != (right.LengthClass == model.LengthEmpty)
	}
	return divergence.Predicate != capturePredicateValue
}

// Apply classifies every divergence in place.
func (c *Classifier) Apply(divergences []model.Divergence) {
	for index := range divergences {
		level, reason := c.Classify(divergences[index])
		divergences[index].Severity = level
		divergences[index].SeverityReason = reason
	}
}

// OnRequestPath reports whether a component is on a request path.
// Exported for the report, which says so next to each finding.
func (g *Graph) OnRequestPath(component string) bool { return g.onRequestPath[component] }
