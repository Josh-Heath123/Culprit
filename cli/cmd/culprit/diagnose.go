package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/josh-heath123/culprit/cli/internal/capability"
	"github.com/josh-heath123/culprit/cli/internal/capture"
	"github.com/josh-heath123/culprit/cli/internal/check"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/isolate"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/probe"
	"github.com/josh-heath123/culprit/cli/internal/report"
)

// partialDiagnosisError: the walk ran and could not finish — a hypothesis
// was refused, unplaceable or out of budget. Not a failure of the command;
// its answer, which is already printed. Exit status 1.
type partialDiagnosisError struct{ root string }

func (e *partialDiagnosisError) Error() string {
	return "the diagnosis is partial; the deepest subject established is " + e.root
}

func newDiagnoseCommand() *cobra.Command {
	var (
		manifestPath  string
		environment   string
		from          string
		reference     string
		format        string
		outputPath    string
		agentID       string
		noPlugins     bool
		pluginTimeout time.Duration
		timeout       time.Duration
	)
	command := &cobra.Command{
		Use:   "diagnose <symptom>",
		Short: "Walk the system model from a symptom to its root cause",
		Long: `Walks the system model from a symptom, choosing each probe by what it rules
out, bisecting down the request path, and prints a fault tree in which every
edge cites the readings that established it.

A symptom is a subject URI (http:orders/POST /orders), a failing endpoint
("POST http://orders.internal:8080/orders") or a component name.

Probes run from wherever this binary runs. Name the component it runs inside
with --from: edges out of that component, the tokens it presents and its own
configuration can only be probed from there, and the tree records every
branch it could not reach as unexplored rather than guessing.

Nothing is changed and nothing is uploaded. --format json writes the
investigation for POST /investigations.

Exit codes: 0 a complete diagnosis, 1 a partial one (it says why), 2 the
command could not run.`,
		Args: cobra.ExactArgs(1),
		RunE: func(command *cobra.Command, args []string) error {
			if environment == "" {
				return fmt.Errorf("--env is required: a diagnosis is always of one environment")
			}
			resolved, err := resolveManifestPath(manifestPath)
			if err != nil {
				return err
			}
			manifest, err := extract.LoadManifest(resolved)
			if err != nil {
				return err
			}
			spec, ok := manifest.Environments[environment]
			if !ok {
				return fmt.Errorf("environment %q is not declared under environments: in %s", environment, resolved)
			}
			if from != "" {
				if _, declared := componentNamed(manifest, from); !declared {
					return fmt.Errorf("--from %q is not a component in %s", from, resolved)
				}
			}

			intent, err := check.Run(command.Context(), check.Options{
				ManifestPath: resolved, Now: captureTime(), PluginTimeout: pluginTimeout,
				SkipPlugins: noPlugins, Version: Version,
			})
			if err != nil {
				return err
			}
			facts := intent.Bundle.Facts

			symptom, entry, err := parseSymptom(args[0], manifest, spec)
			if err != nil {
				return err
			}

			catalogue := probe.BuiltIn()
			runner, err := newWalkRunner(manifest, resolved, environment, agentID, timeout, catalogue, facts)
			if err != nil {
				return err
			}
			options := isolate.Options{Environment: environment}
			options.MaxProbes, options.MaxWallClock = manifest.IsolationBudget(environment)
			if reference != "" {
				referenceSpec, declared := manifest.Environments[reference]
				if !declared {
					return fmt.Errorf("--reference %q is not declared under environments:", reference)
				}
				referenceRunner, err := newWalkRunner(manifest, resolved, reference, agentID, timeout, catalogue, facts)
				if err != nil {
					return err
				}
				options.Reference, options.ReferenceName = referenceRunner, reference
				options.ReferencePlacement = newPlacement(manifest, referenceSpec, from, facts)
			}

			components, connections := walkModel(manifest)
			walk := isolate.New(components, connections, facts, catalogue.Manifests(), runner,
				newPlacement(manifest, spec, from, facts), options)

			opened := captureTime()
			investigation, err := walk.Diagnose(command.Context(), symptom, entry)
			if err != nil {
				return err
			}
			closed := time.Now().UTC()
			investigation.ID, investigation.OpenedAt, investigation.ClosedAt = newInvestigationID(), opened, &closed
			if err := investigation.Validate(); err != nil {
				return fmt.Errorf("the walk produced an investigation the model rejects: %w", err)
			}

			if err := writeInvestigation(command, format, outputPath, investigation); err != nil {
				return err
			}
			if investigation.Diagnosis != nil && !investigation.Diagnosis.Complete {
				return &partialDiagnosisError{root: investigation.Diagnosis.RootSubject}
			}
			return nil
		},
	}
	command.SilenceUsage = true
	command.Flags().StringVarP(&manifestPath, "file", "f", "", "path to culprit.yaml (default: search upward from the working directory)")
	command.Flags().StringVar(&environment, "env", "", "the environment to diagnose, as declared under environments:")
	command.Flags().StringVar(&from, "from", "", "the component this binary runs inside, if any — where edge, token and config probes can be placed")
	command.Flags().StringVar(&reference, "reference", "", "an environment where the symptom does not occur, for the counterfactual criterion")
	command.Flags().StringVar(&format, "format", "text", "text|json")
	command.Flags().StringVarP(&outputPath, "output", "o", "", "write to this file instead of stdout")
	command.Flags().StringVar(&agentID, "agent-id", "culprit-cli", "identifies who took these readings")
	command.Flags().BoolVar(&noPlugins, "no-plugins", false, "extract INTENT with the built-in artefact readers only")
	command.Flags().DurationVar(&pluginTimeout, "plugin-timeout", 90*time.Second, "how long any one extractor plugin may run")
	command.Flags().DurationVar(&timeout, "timeout", 10*time.Second, "per-operation network timeout")
	return command
}

// ---- the model the walk walks ---------------------------------------------

func walkModel(manifest *extract.Manifest) ([]isolate.Component, []isolate.Connection) {
	var components []isolate.Component
	var connections []isolate.Connection
	for _, component := range manifest.Components {
		components = append(components, isolate.Component{Name: component.Name, Kind: component.Kind})
		for _, connection := range component.Connections {
			connections = append(connections, isolate.Connection{
				From: component.Name, To: connection.To, Kind: connection.Kind,
				OnRequestPath: connection.Criticality == "on_request_path",
			})
		}
	}
	return components, connections
}

func componentNamed(manifest *extract.Manifest, name string) (extract.ManifestComponent, bool) {
	for _, component := range manifest.Components {
		if component.Name == name {
			return component, true
		}
	}
	return extract.ManifestComponent{}, false
}

// ---- the symptom --------------------------------------------------------------

var httpMethods = map[string]bool{
	"GET": true, "HEAD": true, "POST": true, "PUT": true, "PATCH": true, "DELETE": true, "OPTIONS": true,
}

// parseSymptom accepts a subject URI, "METHOD URL" or a component name
// (Phase 32: not a trace id or an error signature — resolving either needs
// telemetry, which the binary cannot read before Phase 33).
func parseSymptom(raw string, manifest *extract.Manifest, spec extract.EnvironmentSpec) (model.Symptom, string, error) {
	raw = strings.TrimSpace(raw)
	if fields := strings.Fields(raw); len(fields) == 2 && httpMethods[strings.ToUpper(fields[0])] &&
		(strings.HasPrefix(fields[1], "http://") || strings.HasPrefix(fields[1], "https://")) {
		parsed, err := url.Parse(fields[1])
		if err != nil {
			return model.Symptom{}, "", fmt.Errorf("%q is not a URL: %w", fields[1], err)
		}
		entry, ok := componentServing(parsed, spec)
		if !ok {
			return model.Symptom{}, "", fmt.Errorf(
				"no component in this environment declares an endpoint at %s:%s; "+
					"name the component instead", parsed.Hostname(), portOf(parsed))
		}
		path := parsed.EscapedPath()
		if path == "" {
			path = "/"
		}
		subject, err := model.BuildSubject(model.KindHTTP, model.Parts{
			"component": entry, "method": strings.ToUpper(fields[0]), "path": path})
		if err != nil {
			return model.Symptom{}, "", err
		}
		// Scheme, host, port and path only: a query string, a fragment or
		// userinfo can carry a credential, and the investigation is
		// written out and, from Phase 32 part 2, uploaded.
		shown := url.URL{Scheme: parsed.Scheme, Host: parsed.Host, Path: parsed.Path}
		return model.Symptom{Kind: model.SymptomEndpoint, Subject: subject, Source: "culprit diagnose",
			Description: strings.ToUpper(fields[0]) + " " + shown.String()}, entry, nil
	}

	if kind, parts, err := model.ParseSubject(raw); err == nil {
		entry := ""
		switch kind {
		case model.KindComponent:
			entry = parts["name"]
		case model.KindHTTP, model.KindConfig, model.KindDep, model.KindImage:
			entry = parts["component"]
		case model.KindConnection, model.KindAuth:
			entry = parts["from_component"]
		}
		if _, declared := componentNamed(manifest, entry); entry == "" || !declared {
			return model.Symptom{}, "", fmt.Errorf(
				"%s names no component declared in culprit.yaml to walk from", raw)
		}
		// Rebuilt, not stored as typed: subjects join by equality, so a
		// non-canonical spelling would match nothing downstream.
		canonical, err := model.BuildSubject(kind, parts)
		if err != nil {
			return model.Symptom{}, "", err
		}
		return model.Symptom{Kind: model.SymptomSubject, Subject: canonical, Source: "culprit diagnose"}, entry, nil
	}

	if _, declared := componentNamed(manifest, raw); declared {
		subject, err := model.BuildSubject(model.KindComponent, model.Parts{"name": raw})
		if err != nil {
			return model.Symptom{}, "", err
		}
		return model.Symptom{Kind: model.SymptomComponent, Subject: subject, Source: "culprit diagnose"}, raw, nil
	}
	return model.Symptom{}, "", fmt.Errorf(
		"%q is not a subject URI, a \"METHOD URL\" or a component in culprit.yaml", raw)
}

func componentServing(target *url.URL, spec extract.EnvironmentSpec) (string, bool) {
	port := portOf(target)
	matches := func(endpoint extract.EndpointSpec) bool {
		return strings.EqualFold(endpoint.Host, target.Hostname()) && strconv.Itoa(endpoint.Port) == port
	}
	for name, endpoint := range spec.Endpoints {
		if matches(endpoint) {
			return name, true
		}
	}
	for name, settings := range spec.Components {
		if endpoint := settings.Endpoint; endpoint != nil && matches(*endpoint) {
			return name, true
		}
	}
	return "", false
}

func portOf(target *url.URL) string {
	if port := target.Port(); port != "" {
		return port
	}
	if target.Scheme == "https" {
		return "443"
	}
	return "80"
}

// ---- running probes for the walk ------------------------------------------------

// walkRunner adapts internal/probe to isolate.Runner. Every reading still
// goes through probe.Runner: the capability ledger, the timeout, the
// redaction — the walk gets no shortcut around any of them.
type walkRunner struct {
	runner      *probe.Runner
	environment string
}

func (r walkRunner) Run(ctx context.Context, request isolate.Request) model.Reading {
	readings := r.runner.Run(ctx, []probe.Request{{
		ProbeID: request.ProbeID, Target: request.Target,
		Environment: r.environment, Inputs: request.Inputs,
	}})
	return readings[0]
}

func newWalkRunner(manifest *extract.Manifest, manifestPath, environment, agentID string,
	timeout time.Duration, catalogue *probe.Catalogue, facts []model.Fact,
) (walkRunner, error) {
	grants, err := grantsFor(manifest, environment)
	if err != nil {
		return walkRunner{}, err
	}
	ledger := capability.NewLedger(grants)
	sources := &probe.Sources{
		Environment: environment, Spec: manifest.Environments[environment],
		ManifestDir: filepath.Dir(manifestPath), Grants: grants, Ledger: ledger,
		Runner: capture.ExecRunner{Timeout: timeout}, Reader: capture.PostgresReader{Timeout: timeout},
	}
	deps := probe.Deps{
		Network: probe.NewRealNetwork(timeout), HTTP: probe.NewRealHTTPClient(timeout), Now: time.Now,
		Database: sources.Database(), Config: sources.Config(), Packages: sources.Packages(),
		Secrets: sources.Secrets(),
	}
	return walkRunner{
		environment: environment,
		runner: probe.NewRunner(probe.Options{
			Catalogue: catalogue, Ledger: ledger, AgentID: agentID,
			Overrides: overridesFrom(manifest), Deps: deps,
			Expectations: probe.NewExpectations(facts),
		}),
	}, nil
}

// ---- where each probe points ------------------------------------------------------

// placement is isolate.Placement for one environment, from one vantage.
type placement struct {
	spec  extract.EnvironmentSpec
	from  string
	facts []model.Fact
}

func newPlacement(manifest *extract.Manifest, spec extract.EnvironmentSpec, from string, facts []model.Fact) placement {
	return placement{spec: spec, from: from, facts: facts}
}

func (p placement) Vantage() string { return p.from }

func (p placement) Applicable(h model.Hypothesis) bool {
	_, parts, err := model.ParseSubject(h.Subject)
	if err != nil {
		return false
	}
	switch h.Kind {
	case model.HypothesisTLSInvalid:
		endpoint := p.endpoint(parts["to_component"])
		return endpoint != nil && endpoint.TLS
	case model.HypothesisAuthAudience:
		// An edge is authenticated if something says so: a token is named
		// for it, or an INTENT fact declares the audience it expects.
		_, named := p.spec.Components[parts["from_component"]].Tokens[parts["to_component"]]
		_, declared := p.expectedAudience(h.Subject)
		return named || declared
	case model.HypothesisAuthRejected:
		// Needs a protected URL on the callee to present the token to,
		// which culprit.yaml does not yet say (docs/LIMITS.md).
		return false
	}
	return true
}

func (p placement) Inputs(manifest model.ProbeManifest, h model.Hypothesis) (map[string]any, string) {
	_, parts, err := model.ParseSubject(h.Subject)
	if err != nil {
		return nil, "the hypothesis subject does not parse"
	}
	switch h.Kind {
	case model.HypothesisComponentFails:
		name := parts["name"]
		endpoint := p.endpoint(name)
		if endpoint == nil {
			return nil, fmt.Sprintf("no endpoint is declared for %s in this environment", name)
		}
		if endpoint.HealthPath == "" {
			return nil, fmt.Sprintf("%s's endpoint declares no health_path to send a request to", name)
		}
		return map[string]any{"url": endpointURL(*endpoint, endpoint.HealthPath)}, ""

	case model.HypothesisConnectionUnreachable, model.HypothesisTLSInvalid:
		if reason := p.mustRunAt(parts["from_component"], "a connection from it"); reason != "" {
			return nil, reason
		}
		endpoint := p.endpoint(parts["to_component"])
		if endpoint == nil {
			return nil, fmt.Sprintf("no endpoint is declared for %s in this environment", parts["to_component"])
		}
		inputs := map[string]any{"host": endpoint.Host}
		if manifest.ID != "probe.net.dns_resolve" {
			inputs["port"] = endpoint.Port
		}
		return inputs, ""

	case model.HypothesisDatabaseUnreachable:
		if reason := p.mustRunAt(parts["from_component"], "its database connection"); reason != "" {
			return nil, reason
		}
		return map[string]any{}, ""

	case model.HypothesisAuthAudience:
		from, to := parts["from_component"], parts["to_component"]
		if p.spec.Adapter == extract.AdapterProcess {
			// The process adapter reads the agent's own environment, which
			// holds the caller's token only when the agent runs inside it.
			if reason := p.mustRunAt(from, "the token it presents"); reason != "" {
				return nil, reason
			}
		}
		variable, named := p.spec.Components[from].Tokens[to]
		if !named {
			return nil, fmt.Sprintf("no token variable is named for %s -> %s (environments.*.components.%s.tokens)", from, to, from)
		}
		audience, declared := p.expectedAudience(h.Subject)
		if !declared {
			return nil, fmt.Sprintf("nothing declares the audience %s expects (an invariant on %s)", to, h.Subject)
		}
		// The variable's name, never its value: the probe reads the token
		// through the environment's source, and only under
		// config.read.values for <caller>/<variable> (Phase 32 part 2).
		return map[string]any{"token_env": variable, "expect_audience": audience}, ""

	case model.HypothesisContractMismatch:
		if manifest.ID != "probe.http.route_conformance" {
			return nil, "the walk does not resolve response schemas"
		}
		endpoint := p.endpoint(parts["component"])
		if endpoint == nil {
			return nil, fmt.Sprintf("no endpoint is declared for %s in this environment", parts["component"])
		}
		return map[string]any{"base_url": endpointURL(*endpoint, "")}, ""

	case model.HypothesisConfigMissing:
		if p.spec.Adapter == extract.AdapterProcess {
			if reason := p.mustRunAt(parts["component"], "its configuration"); reason != "" {
				return nil, reason
			}
		}
		return map[string]any{}, ""
	}
	return nil, "the walk has no way yet to place a probe that tests for this"
}

// mustRunAt is the vantage rule (Phase 31.1, Phase 32 "Added 2026-11-03"):
// what a component sees, and what it holds, can only be read from inside it.
func (p placement) mustRunAt(component, what string) string {
	if p.from == component {
		return ""
	}
	here := "outside every component"
	if p.from != "" {
		here = "inside " + p.from
	}
	return fmt.Sprintf("this agent runs %s; %s of %s can only be probed from inside %s (--from %s)",
		here, what, component, component, component)
}

func (p placement) endpoint(component string) *extract.EndpointSpec {
	if endpoint, ok := p.spec.Endpoints[component]; ok {
		return &endpoint
	}
	settings, ok := p.spec.Components[component]
	if !ok {
		return nil
	}
	return settings.Endpoint
}

// expectedAudience is an INTENT fact on the auth subject saying which
// audience the callee expects — a culprit.yaml invariant, or an extractor.
func (p placement) expectedAudience(subject string) (string, bool) {
	for _, fact := range p.facts {
		if fact.Plane != model.PlaneIntent || fact.Subject != subject || fact.Predicate != "audience" {
			continue
		}
		if text, ok := fact.Value.(string); ok && text != "" {
			return text, true
		}
	}
	return "", false
}

func endpointURL(endpoint extract.EndpointSpec, path string) string {
	scheme := "http"
	if endpoint.TLS {
		scheme = "https"
	}
	return fmt.Sprintf("%s://%s:%d%s", scheme, endpoint.Host, endpoint.Port, path)
}

// ---- output ---------------------------------------------------------------------------

func writeInvestigation(command *cobra.Command, format, outputPath string, investigation model.Investigation) error {
	writer := command.OutOrStdout()
	if outputPath != "" {
		file, err := os.Create(outputPath)
		if err != nil {
			return err
		}
		defer file.Close()
		writer = file
	}
	switch format {
	case "json":
		encoder := json.NewEncoder(writer)
		encoder.SetIndent("", "  ")
		return encoder.Encode(investigation)
	case "text":
		return report.RenderInvestigation(writer, investigation)
	}
	return fmt.Errorf("unknown --format %q; expected text or json", format)
}

func newInvestigationID() string {
	buffer := make([]byte, 8)
	if _, err := rand.Read(buffer); err != nil {
		return "inv-" + strconv.FormatInt(time.Now().UnixNano(), 16)
	}
	return "inv-" + hex.EncodeToString(buffer)
}
