// Package isolate is the isolation walk (docs/DIAGNOSTIC_PLAN.md Phase 32):
// given a symptom, it builds the hypothesis space from the system model,
// chooses probes by what they discriminate, bisects down the request path,
// and assembles a fault tree in which every edge cites the readings that
// established it.
//
// It is deterministic and links no network package. Probes are run through
// the Runner interface that cmd/culprit supplies; where a probe must point
// (a URL, a host, a token) comes from the Placement interface, because
// that is knowledge about an environment and this package knows only the
// model. "internal/isolate does not import internal/probe" is the plan's
// rule, and TestTheNetworkBoundaryIsAnAllowlist holds it.
//
// # The premise the bisection rests on
//
// A request entering at component X exercises X and everything X calls on
// the request path. So if the probe for "a request at X fails" passes, X
// and everything below it is ruled out by that one reading; if it fails,
// the fault is at X or below. That premise is what makes a six-hop chain
// cost O(log n) probes instead of n. It holds for a probe that sends a
// real request through X. It does not hold for a shallow health check that
// answers 200 without touching X's dependencies — docs/LIMITS.md says so,
// and the entry component is never "ruled out" by its own probe passing,
// because the symptom is the evidence that it fails.
package isolate

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Hypothesis kinds are model.Hypothesis* — the vocabulary
// ProbeManifest.Discriminates speaks, shared with internal/probe.
const (
	KindComponentFails        = model.HypothesisComponentFails
	KindConnectionUnreachable = model.HypothesisConnectionUnreachable
	KindDatabaseUnreachable   = model.HypothesisDatabaseUnreachable
	KindTLSInvalid            = model.HypothesisTLSInvalid
	KindAuthAudience          = model.HypothesisAuthAudience
	KindAuthRejected          = model.HypothesisAuthRejected
	KindContractMismatch      = model.HypothesisContractMismatch
	KindConfigMissing         = model.HypothesisConfigMissing
)

// localOrder is the order boundary hypotheses are tested in, cheapest and
// most fundamental first: a connection that cannot be opened explains
// everything above it, so it is asked before the audience of a token.
var localOrder = []string{
	KindConnectionUnreachable, KindDatabaseUnreachable, KindTLSInvalid,
	KindAuthAudience, KindAuthRejected, KindContractMismatch, KindConfigMissing,
}

// Component is a node of the system model.
type Component struct {
	Name string
	Kind string
}

// Connection is a typed, directed edge of the system model.
type Connection struct {
	From, To      string
	Kind          string
	OnRequestPath bool
}

// Request is what the walk asks a Runner to run.
type Request struct {
	ProbeID string
	Target  string
	Inputs  map[string]any
}

// Runner runs one probe and returns its reading. cmd/culprit adapts
// internal/probe to this; tests count executions through it.
type Runner interface {
	Run(ctx context.Context, request Request) model.Reading
}

// Placement knows the environment: where each probe has to point, and
// whether it can be placed at all from where this agent runs.
type Placement interface {
	// Applicable reports whether a hypothesis makes sense in this
	// environment at all (a TLS hypothesis for an endpoint served in
	// plain text does not). An inapplicable hypothesis is not generated.
	Applicable(hypothesis model.Hypothesis) bool
	// Inputs returns the inputs for running manifest against hypothesis,
	// or a reason it cannot be placed — "this agent runs on the host; the
	// connection orders->db is only visible from inside orders".
	Inputs(manifest model.ProbeManifest, hypothesis model.Hypothesis) (map[string]any, string)
	// Vantage is the component this agent runs inside, or "" when it runs
	// outside every component. A request this agent sends to B crosses
	// the edge Vantage -> B when there is one, so a failure there does not
	// yet say whether B is broken or the edge is.
	Vantage() string
}

// Options bound a walk (`isolation:` in culprit.yaml).
type Options struct {
	Environment string
	// MaxProbes is the most probes one investigation may run, counting the
	// reproduction and counterfactual runs. Zero means DefaultMaxProbes.
	MaxProbes int
	// MaxWallClock bounds the whole walk. Zero means DefaultMaxWallClock.
	MaxWallClock time.Duration
	// Reference, when set, runs the root's probe in a reference
	// environment for the counterfactual criterion (§2.9).
	Reference          Runner
	ReferenceName      string
	ReferencePlacement Placement
	Now                func() time.Time
}

// Defaults for `isolation:` when culprit.yaml says nothing.
const (
	DefaultMaxProbes    = 40
	DefaultMaxWallClock = 2 * time.Minute
)

// Walk is one investigation in progress.
type Walk struct {
	options   Options
	manifests []model.ProbeManifest
	runner    Runner
	placement Placement
	facts     []model.Fact

	components map[string]Component
	// declared is every on-request-path edge, as culprit.yaml lists them.
	declared map[string][]Connection
	// children is the request-path tree rooted at the entry: each
	// component's edges to components first reached through it. A model
	// may declare an edge back up the path (the demo's inventory-service
	// -> order-service); a request entering at the entry does not travel
	// it, and following it turned "a pass at inventory rules out what is
	// below inventory" into "rules out the whole system" (found by the
	// fault library's first run).
	children map[string][]Connection

	started    time.Time
	probesRun  int
	readings   []model.InvestigationReading
	hypotheses []model.Hypothesis
	index      map[string]int // hypothesis key -> position
}

// New prepares a walk. facts are the INTENT facts `culprit check` extracts;
// the walk reads routes callers declare (`calls`) and config components
// require (`required`) from them.
func New(components []Component, connections []Connection, facts []model.Fact,
	manifests []model.ProbeManifest, runner Runner, placement Placement, options Options,
) *Walk {
	if options.MaxProbes <= 0 {
		options.MaxProbes = DefaultMaxProbes
	}
	if options.MaxWallClock <= 0 {
		options.MaxWallClock = DefaultMaxWallClock
	}
	if options.Now == nil {
		options.Now = time.Now
	}
	walk := &Walk{
		options: options, manifests: manifests, runner: runner, placement: placement,
		facts: facts, components: map[string]Component{}, declared: map[string][]Connection{},
		children: map[string][]Connection{}, index: map[string]int{},
	}
	for _, component := range components {
		walk.components[component.Name] = component
	}
	for _, connection := range connections {
		if connection.OnRequestPath {
			walk.declared[connection.From] = append(walk.declared[connection.From], connection)
		}
	}
	for name := range walk.declared {
		sort.Slice(walk.declared[name], func(i, j int) bool {
			return walk.declared[name][i].To < walk.declared[name][j].To
		})
	}
	return walk
}

// ProbesRun is how many probes the walk executed — what the O(log n)
// criterion counts.
func (w *Walk) ProbesRun() int { return w.probesRun }

// located is where the walk has pinned the failure so far.
type located struct {
	// path runs from the entry component down to the deepest component
	// shown to fail, with the reading that showed each one failing (the
	// entry's is "" — the symptom is its evidence).
	path []string
	fail map[string]string
	// root and rootReading, when a boundary hypothesis was supported.
	root        string
	rootReading string
	rootRequest *Request
	// blockers name why the walk stopped short of a root.
	partial []string
}

// Diagnose runs the walk from a symptom on entry. The Investigation it
// returns has no id or timestamps of its own; cmd/culprit stamps those.
func (w *Walk) Diagnose(ctx context.Context, symptom model.Symptom, entry string) (model.Investigation, error) {
	if _, ok := w.components[entry]; !ok {
		return model.Investigation{}, fmt.Errorf(
			"%q is not a component in culprit.yaml, so there is no model to walk from it", entry)
	}
	w.started = w.options.Now()
	w.buildTree(entry)
	w.buildHypotheses(entry)

	found := &located{fail: map[string]string{}}
	w.locate(ctx, entry, "", found)

	inv := model.Investigation{
		Environment: w.options.Environment,
		Symptom:     symptom,
		Hypotheses:  w.hypotheses,
		Readings:    w.readings,
	}
	inv.FaultTree, inv.Diagnosis = w.assemble(ctx, symptom, found)
	inv.Hypotheses = w.hypotheses // reproduction may have added readings
	inv.Readings = w.readings
	inv.Symptom.Attestation = w.attest(symptom)
	return inv, nil
}

// attest says what establishes the symptom happened (§2.8, amended): a
// failing reading on the symptom's own subject if the walk took one, and
// otherwise the report it came from — never "reproduced" by inference.
func (w *Walk) attest(symptom model.Symptom) model.Attestation {
	for _, item := range w.readings {
		if item.Reading.Target == symptom.Subject && item.Reading.Verdict == model.VerdictFail {
			return model.Attestation{Kind: model.AttestedReproduced, Reading: item.ID}
		}
	}
	reportedBy := symptom.Source
	if reportedBy == "" {
		reportedBy = "the caller"
	}
	return model.Attestation{Kind: model.AttestedReported, ReportedBy: reportedBy}
}

// ---- the hypothesis space -------------------------------------------------

// buildTree keeps, breadth first from entry, only the edges that reach a
// component for the first time. Deterministic: declared edges are sorted.
func (w *Walk) buildTree(entry string) {
	w.children = map[string][]Connection{}
	reached := map[string]bool{entry: true}
	queue := []string{entry}
	for len(queue) > 0 {
		name := queue[0]
		queue = queue[1:]
		for _, edge := range w.declared[name] {
			if reached[edge.To] {
				continue
			}
			reached[edge.To] = true
			w.children[name] = append(w.children[name], edge)
			queue = append(queue, edge.To)
		}
	}
}

func (w *Walk) buildHypotheses(entry string) {
	seen := map[string]bool{}
	var visit func(name string)
	visit = func(name string) {
		if seen[name] {
			return
		}
		seen[name] = true
		component := w.components[name]
		if component.Kind != "database" {
			w.addHypothesis(KindComponentFails, model.MustBuildSubject(model.KindComponent, model.Parts{"name": name}))
		}
		for _, key := range w.requiredConfig(name) {
			w.addHypothesis(KindConfigMissing, key)
		}
		for _, edge := range w.children[name] {
			connection := model.MustBuildSubject(model.KindConnection, model.Parts{"from_component": edge.From, "to_component": edge.To})
			if w.components[edge.To].Kind == "database" {
				w.addHypothesis(KindDatabaseUnreachable, connection)
			} else {
				w.addHypothesis(KindConnectionUnreachable, connection)
				w.addHypothesis(KindTLSInvalid, connection)
				audience := model.MustBuildSubject(model.KindAuth, model.Parts{"from_component": edge.From, "to_component": edge.To, "aspect": "audience"})
				w.addHypothesis(KindAuthAudience, audience)
				propagation := model.MustBuildSubject(model.KindAuth, model.Parts{"from_component": edge.From, "to_component": edge.To, "aspect": "propagation"})
				w.addHypothesis(KindAuthRejected, propagation)
				for _, route := range w.declaredRoutes(edge.To) {
					w.addHypothesis(KindContractMismatch, route)
				}
			}
			visit(edge.To)
		}
	}
	visit(entry)
}

func (w *Walk) addHypothesis(kind, subject string) {
	key := kind + " " + subject
	if _, exists := w.index[key]; exists {
		return
	}
	hypothesis := model.Hypothesis{
		ID: fmt.Sprintf("h%d", len(w.hypotheses)+1), Kind: kind, Subject: subject,
		Status: model.HypothesisOpen,
	}
	if w.placement != nil && !w.placement.Applicable(hypothesis) {
		return
	}
	w.index[key] = len(w.hypotheses)
	w.hypotheses = append(w.hypotheses, hypothesis)
}

func (w *Walk) hypothesis(kind, subject string) *model.Hypothesis {
	position, ok := w.index[kind+" "+subject]
	if !ok {
		return nil
	}
	return &w.hypotheses[position]
}

// declaredRoutes are the routes on callee that some source says are called.
func (w *Walk) declaredRoutes(callee string) []string {
	set := map[string]bool{}
	for _, fact := range w.facts {
		if fact.Predicate != model.PredicateCalls {
			continue
		}
		kind, parts, err := model.ParseSubject(fact.Subject)
		if err != nil || kind != model.KindHTTP || parts["component"] != callee {
			continue
		}
		set[fact.Subject] = true
	}
	return sortedKeys(set)
}

// requiredConfig are the config keys a component's code requires.
func (w *Walk) requiredConfig(component string) []string {
	set := map[string]bool{}
	for _, fact := range w.facts {
		if fact.Predicate != model.PredicateRequired || fact.Value != true {
			continue
		}
		kind, parts, err := model.ParseSubject(fact.Subject)
		if err != nil || kind != model.KindConfig || parts["component"] != component {
			continue
		}
		set[fact.Subject] = true
	}
	return sortedKeys(set)
}

// ---- running one discriminating probe ---------------------------------------

// test runs the cheapest placeable probe that discriminates h, and moves h
// accordingly. It returns the reading id and the request it ran, or "" if
// nothing could be run.
func (w *Walk) test(ctx context.Context, h *model.Hypothesis) (string, *Request) {
	if h == nil {
		return "", nil
	}
	if reason := w.outOfBudget(); reason != "" {
		w.markUnexplored(h, reason, "")
		return "", nil
	}
	var reasons []string
	for _, manifest := range w.discriminators(h.Kind) {
		inputs, reason := w.placement.Inputs(manifest, *h)
		if reason != "" {
			reasons = append(reasons, fmt.Sprintf("%s: %s", manifest.ID, reason))
			continue
		}
		request := Request{ProbeID: manifest.ID, Target: h.Subject, Inputs: inputs}
		id := w.run(ctx, request)
		reading := w.readingByID(id)
		switch reading.Verdict {
		case model.VerdictPass:
			h.Status, h.Reason = model.HypothesisRuledOut, ""
			h.Readings = append(h.Readings, id)
		case model.VerdictFail:
			h.Status, h.Reason = model.HypothesisSupported, ""
			h.Readings = append(h.Readings, id)
		default:
			w.markUnexplored(h, fmt.Sprintf("%s was %s: %s", manifest.ID, reading.Verdict, reading.Reason), id)
		}
		return id, &request
	}
	if len(reasons) == 0 {
		reasons = append(reasons, "no probe in the catalogue discriminates "+h.Kind)
	}
	w.markUnexplored(h, "no probe could be placed: "+strings.Join(reasons, "; "), "")
	return "", nil
}

func (w *Walk) markUnexplored(h *model.Hypothesis, reason, readingID string) {
	h.Status, h.Reason = model.HypothesisUnexplored, reason
	if readingID != "" {
		h.Readings = append(h.Readings, readingID)
	}
}

// discriminators are the manifests that rule out kind, cheapest first.
func (w *Walk) discriminators(kind string) []model.ProbeManifest {
	var matches []model.ProbeManifest
	for _, manifest := range w.manifests {
		for _, discriminated := range manifest.Discriminates {
			if discriminated == kind {
				matches = append(matches, manifest)
				break
			}
		}
	}
	rank := map[model.Cost]int{model.CostCheap: 0, "": 0, model.CostMetered: 1, model.CostIntrusive: 2}
	sort.SliceStable(matches, func(i, j int) bool {
		if rank[matches[i].Cost] != rank[matches[j].Cost] {
			return rank[matches[i].Cost] < rank[matches[j].Cost]
		}
		return matches[i].ID < matches[j].ID
	})
	return matches
}

func (w *Walk) run(ctx context.Context, request Request) string {
	w.probesRun++
	reading := w.runner.Run(ctx, request)
	id := fmt.Sprintf("r%d", len(w.readings)+1)
	w.readings = append(w.readings, model.InvestigationReading{ID: id, Reading: reading})
	return id
}

func (w *Walk) readingByID(id string) model.Reading {
	for _, item := range w.readings {
		if item.ID == id {
			return item.Reading
		}
	}
	return model.Reading{}
}

func (w *Walk) outOfBudget() string {
	if w.probesRun >= w.options.MaxProbes {
		return fmt.Sprintf("the probe budget (%d per investigation) ran out", w.options.MaxProbes)
	}
	if w.options.Now().Sub(w.started) >= w.options.MaxWallClock {
		return fmt.Sprintf("the wall-clock budget (%s) ran out", w.options.MaxWallClock)
	}
	return ""
}

// ---- the walk ---------------------------------------------------------------

// fails tests "a request at component fails". It returns the verdict as
// fail/pass/unknown and the reading id.
func (w *Walk) fails(ctx context.Context, component string) (string, string) {
	subject := model.MustBuildSubject(model.KindComponent, model.Parts{"name": component})
	h := w.hypothesis(KindComponentFails, subject)
	if h == nil {
		return "unknown", ""
	}
	id, _ := w.test(ctx, h)
	switch h.Status {
	case model.HypothesisSupported:
		return "fail", id
	case model.HypothesisRuledOut:
		// One pass rules out everything the request at this component
		// exercised: the component and everything below it.
		w.ruleOutBelow(component, id)
		return "pass", id
	}
	return "unknown", id
}

func (w *Walk) ruleOutBelow(component, readingID string) {
	below := map[string]bool{}
	var collect func(name string)
	collect = func(name string) {
		if below[name] {
			return
		}
		below[name] = true
		for _, edge := range w.children[name] {
			collect(edge.To)
		}
	}
	collect(component)
	for position := range w.hypotheses {
		h := &w.hypotheses[position]
		if h.Status != model.HypothesisOpen || !subjectWithin(h.Subject, below, component) {
			continue
		}
		h.Status = model.HypothesisRuledOut
		h.Readings = append(h.Readings, readingID)
	}
}

// subjectWithin reports whether a hypothesis subject concerns only the
// components in set. An edge leaving the set's root from above is not.
func subjectWithin(subject string, set map[string]bool, root string) bool {
	kind, parts, err := model.ParseSubject(subject)
	if err != nil {
		return false
	}
	switch kind {
	case model.KindComponent:
		return set[parts["name"]]
	case model.KindConnection, model.KindAuth:
		return set[parts["from_component"]] && set[parts["to_component"]]
	case model.KindConfig:
		return set[parts["component"]]
	case model.KindHTTP:
		// A route on a component below the one that passed was exercised by
		// that request; a route on the passing component itself was not
		// necessarily — the probe asked one path, not every one.
		return set[parts["component"]] && parts["component"] != root
	}
	return false
}

// locate pins the failure at or below component, which is known (or, for
// the entry, asserted) to fail.
func (w *Walk) locate(ctx context.Context, component, failReading string, found *located) {
	found.path = append(found.path, component)
	found.fail[component] = failReading

	// The longest single-child chain below component: bisected, not walked.
	chain := []string{component}
	for {
		kids := w.children[chain[len(chain)-1]]
		if len(kids) != 1 || w.components[kids[0].To].Kind == "database" {
			break
		}
		chain = append(chain, kids[0].To)
	}

	// Invariant: chain[low] fails; high is the first index known to pass,
	// or len(chain) when nothing below has been seen to pass.
	low, high := 0, len(chain)
	for high-low > 1 {
		middle := (low + high) / 2
		verdict, id := w.fails(ctx, chain[middle])
		if verdict == "fail" && w.edgeIsTheCause(ctx, chain[middle-1], chain[middle], found) {
			for k := low + 1; k < middle; k++ {
				found.path = append(found.path, chain[k])
				found.fail[chain[k]] = id
			}
			return
		}
		switch verdict {
		case "fail":
			for k := low + 1; k <= middle; k++ {
				// Every component between two failing points fails too:
				// a request through it reaches the deeper failure.
				found.path = append(found.path, chain[k])
				found.fail[chain[k]] = id
			}
			low = middle
		case "pass":
			high = middle
		default:
			found.partial = append(found.partial, fmt.Sprintf(
				"whether a request at %s fails could not be established", chain[middle]))
			w.boundary(ctx, chain[low], chain[low+1:], found)
			return
		}
	}

	deepest := chain[low]
	if high < len(chain) {
		// The next component down answers when asked directly: the fault
		// is at deepest itself, or on its edge to that component.
		w.boundary(ctx, deepest, []string{chain[high]}, found)
		return
	}
	kids := w.children[deepest]
	var services, databases []string
	for _, edge := range kids {
		if w.components[edge.To].Kind == "database" {
			databases = append(databases, edge.To)
		} else {
			services = append(services, edge.To)
		}
	}
	for _, child := range services {
		verdict, id := w.fails(ctx, child)
		if verdict == "fail" {
			if w.edgeIsTheCause(ctx, deepest, child, found) {
				return
			}
			w.locate(ctx, child, id, found)
			return
		}
		if verdict == "unknown" {
			found.partial = append(found.partial, fmt.Sprintf(
				"whether a request at %s fails could not be established", child))
		}
	}
	w.boundary(ctx, deepest, append(services, databases...), found)
}

// edgeIsTheCause is asked when a request from this agent to child failed.
// If the agent runs inside parent, that request crossed the edge
// parent -> child, so the edge is tested before the walk descends into a
// child that may be perfectly healthy (Phase 31.1's partition: inventory
// answered everyone but order-service). When the agent runs anywhere
// else, the request did not cross that edge and the failure is child's.
func (w *Walk) edgeIsTheCause(ctx context.Context, parent, child string, found *located) bool {
	if w.placement == nil || w.placement.Vantage() != parent {
		return false
	}
	edge := model.MustBuildSubject(model.KindConnection, model.Parts{"from_component": parent, "to_component": child})
	h := w.hypothesis(KindConnectionUnreachable, edge)
	if h == nil || h.Status != model.HypothesisOpen {
		return false
	}
	id, request := w.test(ctx, h)
	if h.Status != model.HypothesisSupported {
		return false
	}
	found.root, found.rootReading, found.rootRequest = edge, id, request
	return true
}

// boundary tests the hypotheses local to component and its edges to
// below: the failure is here, and these are the ways it could be.
func (w *Walk) boundary(ctx context.Context, component string, below []string, found *located) {
	var candidates []*model.Hypothesis
	for _, kind := range localOrder {
		for position := range w.hypotheses {
			h := &w.hypotheses[position]
			if h.Kind != kind || h.Status != model.HypothesisOpen || !w.local(h.Subject, component, below) {
				continue
			}
			candidates = append(candidates, h)
		}
	}
	for _, h := range candidates {
		id, request := w.test(ctx, h)
		if h.Status == model.HypothesisSupported && found.root == "" {
			found.root, found.rootReading, found.rootRequest = h.Subject, id, request
		}
	}
	for _, h := range candidates {
		if h.Status == model.HypothesisUnexplored {
			found.partial = append(found.partial, h.Kind+" on "+h.Subject+": "+h.Reason)
		}
	}
}

// local reports whether subject is a boundary subject of component: one
// of its own config keys, or an edge from it to one of below.
func (w *Walk) local(subject, component string, below []string) bool {
	kind, parts, err := model.ParseSubject(subject)
	if err != nil {
		return false
	}
	isBelow := func(name string) bool {
		for _, candidate := range below {
			if candidate == name {
				return true
			}
		}
		return false
	}
	switch kind {
	case model.KindConfig:
		return parts["component"] == component
	case model.KindConnection, model.KindAuth:
		return parts["from_component"] == component && isBelow(parts["to_component"])
	case model.KindHTTP:
		return isBelow(parts["component"])
	}
	return false
}

// ---- the tree -----------------------------------------------------------------

func (w *Walk) assemble(ctx context.Context, symptom model.Symptom, found *located) ([]model.FaultEdge, *model.Diagnosis) {
	var tree []model.FaultEdge
	add := func(from, to string, relation model.Relation, ids ...string) {
		var cited []string
		seen := map[string]bool{}
		for _, id := range ids {
			// One reading can establish two hops (a request at c3 failing
			// shows c1..c3 fail); it is cited once.
			if id != "" && !seen[id] {
				seen[id] = true
				cited = append(cited, id)
			}
		}
		if len(cited) == 0 || from == to {
			return // an edge no reading established is not drawn
		}
		edge, err := model.NewFaultEdge(from, to, relation, cited...)
		if err == nil {
			tree = append(tree, edge)
		}
	}
	componentSubject := func(name string) string {
		return model.MustBuildSubject(model.KindComponent, model.Parts{"name": name})
	}

	entry := found.path[0]
	deepest := found.path[len(found.path)-1]

	// The reading that establishes the entry fails. The symptom is an
	// assertion, and a write endpoint cannot be replayed read-only, so
	// when nothing re-observed it, the cause's reading is what
	// establishes that the entry fails: it shows the request cannot
	// succeed.
	entryEvidence := found.fail[entry]
	if entryEvidence == "" {
		if len(found.path) > 1 {
			entryEvidence = found.fail[found.path[1]]
		} else {
			entryEvidence = found.rootReading
		}
	}
	add(symptom.Subject, componentSubject(entry), model.RelationSymptomOf, entryEvidence)
	for index := len(found.path) - 1; index > 0; index-- {
		child, parent := found.path[index], found.path[index-1]
		add(componentSubject(child), componentSubject(parent), model.RelationPropagatesTo,
			found.fail[child], found.fail[parent])
	}
	if found.root != "" {
		add(componentSubject(deepest), found.root, model.RelationCausedBy, found.rootReading)
	}

	root := componentSubject(deepest)
	if found.root != "" {
		root = found.root
	}
	diagnosis := &model.Diagnosis{
		RootSubject: root,
		Confidence:  w.rubric(ctx, found),
	}
	switch {
	case found.root != "":
		diagnosis.Statement = fmt.Sprintf(
			"%s fails because of %s; the readings rule out the alternatives they reached.",
			deepest, found.root)
		diagnosis.Remediation = remediation(found.root)
		diagnosis.Complete = len(found.partial) == 0
	case len(found.partial) == 0 && found.fail[deepest] != "":
		diagnosis.Statement = fmt.Sprintf(
			"The failure is in %s: a request there fails, every request below it succeeds, "+
				"and no edge from it failed a probe. What inside %s fails was not established.",
			deepest, deepest)
		diagnosis.Complete = true
	case len(found.partial) == 0:
		// Nothing tested failed. That is an exclusion, not a finding: the
		// cause is inside the entry, or is something no read-only probe
		// can see — added latency is one (docs/LIMITS.md).
		diagnosis.Statement = fmt.Sprintf(
			"Nothing the walk tested failed: every component below %s answers and every edge "+
				"from it passes. The cause is inside %s, or is something no read-only probe "+
				"observes, such as added latency.", deepest, deepest)
	default:
		diagnosis.Statement = fmt.Sprintf(
			"The failure is localised to %s, and the walk could not finish: %s.",
			deepest, strings.Join(found.partial, "; "))
	}
	if !diagnosis.Complete && len(found.partial) > 0 && found.root != "" {
		diagnosis.Statement += " Not every alternative was tested: " + strings.Join(found.partial, "; ") + "."
	}
	if diagnosis.Complete && !treeReaches(tree, root) {
		diagnosis.Complete = false
	}
	return tree, diagnosis
}

func treeReaches(tree []model.FaultEdge, subject string) bool {
	for _, edge := range tree {
		if edge.FromSubject == subject || edge.ToSubject == subject {
			return true
		}
	}
	return false
}

// rubric is §2.9, computed from readings, never estimated.
func (w *Walk) rubric(ctx context.Context, found *located) model.ConfidenceRubric {
	rubric := model.ConfidenceRubric{
		Verified: model.Criterion{Reason: "verification needs a change and the loop that checks it, which is Phase 34"},
	}

	// The reading the diagnosis rests on, and the request behind it.
	var basis string
	var request *Request
	if found.root != "" {
		basis, request = found.rootReading, found.rootRequest
	} else if len(found.path) > 1 {
		deepest := found.path[len(found.path)-1]
		basis = found.fail[deepest]
		request = w.requestFor(basis)
	}

	switch {
	case request == nil:
		rubric.Reproduced.Reason = "no failing probe established the diagnosis, so there was nothing to run again"
	case w.outOfBudget() != "":
		rubric.Reproduced.Reason = "not run again: " + w.outOfBudget()
	default:
		again := w.run(ctx, *request)
		if w.readingByID(again).Verdict == model.VerdictFail {
			rubric.Reproduced = model.Criterion{Holds: true, Reason: fmt.Sprintf(
				"%s failed again when run a second time (%s, then %s)", request.ProbeID, basis, again)}
		} else {
			rubric.Reproduced.Reason = fmt.Sprintf(
				"%s did not fail on a second run (%s): the fault may be intermittent", request.ProbeID, again)
		}
	}

	var ruledOut []string
	for _, h := range w.hypotheses {
		if h.Status == model.HypothesisRuledOut {
			ruledOut = append(ruledOut, h.ID)
		}
	}
	if len(ruledOut) > 0 {
		rubric.Discriminated = model.Criterion{Holds: true, Reason: fmt.Sprintf(
			"%d competing hypotheses were ruled out by readings (%s)", len(ruledOut), strings.Join(ruledOut, ", "))}
	} else {
		rubric.Discriminated.Reason = "no reading ruled out a competing hypothesis"
	}

	switch {
	case w.options.Reference == nil:
		rubric.Counterfactual.Reason = "no reference environment was named (--reference)"
	case request == nil:
		rubric.Counterfactual.Reason = "no failing probe to repeat in " + w.options.ReferenceName
	default:
		rubric.Counterfactual = w.counterfactual(ctx, *request)
	}
	return rubric
}

func (w *Walk) counterfactual(ctx context.Context, request Request) model.Criterion {
	h := w.hypothesisFor(request.Target)
	if h == nil || w.options.ReferencePlacement == nil {
		return model.Criterion{Reason: "the root's probe cannot be placed in " + w.options.ReferenceName}
	}
	var manifest model.ProbeManifest
	for _, candidate := range w.manifests {
		if candidate.ID == request.ProbeID {
			manifest = candidate
		}
	}
	inputs, reason := w.options.ReferencePlacement.Inputs(manifest, *h)
	if reason != "" {
		return model.Criterion{Reason: fmt.Sprintf("%s cannot be placed in %s: %s", request.ProbeID, w.options.ReferenceName, reason)}
	}
	if budget := w.outOfBudget(); budget != "" {
		return model.Criterion{Reason: "not run: " + budget}
	}
	w.probesRun++
	reading := w.options.Reference.Run(ctx, Request{ProbeID: request.ProbeID, Target: request.Target, Inputs: inputs})
	id := fmt.Sprintf("r%d", len(w.readings)+1)
	w.readings = append(w.readings, model.InvestigationReading{ID: id, Reading: reading})
	if reading.Verdict == model.VerdictPass {
		return model.Criterion{Holds: true, Reason: fmt.Sprintf(
			"%s passes in %s (%s) where it fails here", request.ProbeID, w.options.ReferenceName, id)}
	}
	return model.Criterion{Reason: fmt.Sprintf(
		"%s was %s in %s too (%s), so the reference does not separate the cause", request.ProbeID, reading.Verdict, w.options.ReferenceName, id)}
}

func (w *Walk) hypothesisFor(subject string) *model.Hypothesis {
	for position := range w.hypotheses {
		if w.hypotheses[position].Subject == subject {
			return &w.hypotheses[position]
		}
	}
	return nil
}

// requestFor rebuilds the request behind a component_fails reading.
func (w *Walk) requestFor(readingID string) *Request {
	reading := w.readingByID(readingID)
	if reading.ProbeID == "" {
		return nil
	}
	h := w.hypothesisFor(reading.Target)
	if h == nil {
		return nil
	}
	for _, manifest := range w.manifests {
		if manifest.ID != reading.ProbeID {
			continue
		}
		inputs, reason := w.placement.Inputs(manifest, *h)
		if reason != "" {
			return nil
		}
		return &Request{ProbeID: manifest.ID, Target: reading.Target, Inputs: inputs}
	}
	return nil
}

// remediation says what to change. Culprit recommends; it never applies
// a change (Phase 32 field 17).
func remediation(root string) string {
	kind, parts, err := model.ParseSubject(root)
	if err != nil {
		return ""
	}
	switch kind {
	case model.KindAuth:
		if parts["aspect"] == "audience" {
			return fmt.Sprintf("Make the audience %s presents to %s match the one %s expects.",
				parts["from_component"], parts["to_component"], parts["to_component"])
		}
		return fmt.Sprintf("Check the credentials %s sends to %s are ones %s accepts.",
			parts["from_component"], parts["to_component"], parts["to_component"])
	case model.KindConnection:
		return fmt.Sprintf("Restore the network path from %s to %s.", parts["from_component"], parts["to_component"])
	case model.KindConfig:
		return fmt.Sprintf("Set %s for %s.", parts["key"], parts["component"])
	case model.KindHTTP:
		return fmt.Sprintf("Serve %s %s on %s, or stop calling it.", parts["method"], parts["path"], parts["component"])
	}
	return ""
}

func sortedKeys(set map[string]bool) []string {
	keys := make([]string, 0, len(set))
	for key := range set {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}
