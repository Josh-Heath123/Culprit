package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/josh-heath123/culprit/cli/internal/capability"
	"github.com/josh-heath123/culprit/cli/internal/check"
	"github.com/josh-heath123/culprit/cli/internal/extract"
	"github.com/josh-heath123/culprit/cli/internal/mcp"
	"github.com/josh-heath123/culprit/cli/internal/model"
	"github.com/josh-heath123/culprit/cli/internal/report"
)

// `culprit mcp` — Phase 35 part 1: the agent surface.
//
// A coding agent starts this binary and speaks MCP to it over stdin and
// stdout. Each tool calls the code its command runs — runDiagnose,
// runVerify, runProbe, check.Run — and answers with the structured result
// that command's --format json prints. Nothing here is a second
// implementation of the walk, a probe or a verdict (D2).
//
// What the server is not given by its caller: grants (the environment's,
// in culprit.yaml, exactly as for the CLI), the vantage (--from, where
// this binary runs, fixed when it starts), the state directory, or any
// write. No tool changes culprit.yaml, an environment or the control
// plane; the binary calls no model, and no response carries prose.

func newMCPCommand() *cobra.Command {
	var server mcpServer
	command := &cobra.Command{
		Use:   "mcp",
		Short: "Serve Culprit's tools to a coding agent over MCP (stdio)",
		Long: `Speaks the Model Context Protocol on stdin and stdout, for a coding agent
that starts this binary as a tool server. Six tools, every one read-only:

  culprit_system_model        components, connections, environments and grants
  culprit_check               culprit check: contradictions in the repository
  culprit_explain_connection  what is known about one connection, and how it can be probed
  culprit_probe               culprit probe: named probes against one subject
  culprit_diagnose            culprit diagnose: a symptom walked to a rooted fault tree
  culprit_verify              culprit verify: a fix measured again and judged

Each answers with the structured result the command's --format json gives.
Grants are the environment's, in culprit.yaml; no argument can add one. The
vantage (--from) and the state directory are this server's, set here, the
same as the commands'. Nothing is changed and nothing is uploaded.

stdout carries protocol messages only; warnings go to stderr.`,
		Args: cobra.NoArgs,
		RunE: func(command *cobra.Command, _ []string) error {
			resolved, err := resolveManifestPath(server.manifestPath)
			if err != nil {
				return err
			}
			manifest, err := extract.LoadManifest(resolved)
			if err != nil {
				return err
			}
			if server.from != "" {
				if _, declared := componentNamed(manifest, server.from); !declared {
					return fmt.Errorf("--from %q is not a component in %s", server.from, resolved)
				}
			}
			server.manifestPath, server.stderr = resolved, command.ErrOrStderr()
			return server.protocol().Run(command.Context(), command.InOrStdin(), command.OutOrStdout())
		},
	}
	command.SilenceUsage = true
	command.Flags().StringVarP(&server.manifestPath, "file", "f", "", "path to culprit.yaml (default: search upward from the working directory)")
	command.Flags().StringVar(&server.from, "from", "", "the component this binary runs inside, if any — the vantage every diagnosis and verification uses")
	command.Flags().StringVar(&server.stateDir, "state-dir", defaultStateDir(), "where diagnoses are kept for verification ($CULPRIT_STATE_DIR)")
	command.Flags().StringVar(&server.agentID, "agent-id", "culprit-mcp", "identifies who took these readings")
	command.Flags().BoolVar(&server.noPlugins, "no-plugins", false, "extract INTENT with the built-in artefact readers only")
	command.Flags().DurationVar(&server.pluginTimeout, "plugin-timeout", 90*time.Second, "how long any one extractor plugin may run")
	command.Flags().DurationVar(&server.timeout, "timeout", 10*time.Second, "per-operation network timeout")
	return command
}

// mcpServer is everything a tool may not be told by its caller.
type mcpServer struct {
	manifestPath  string
	from          string
	stateDir      string
	agentID       string
	noPlugins     bool
	pluginTimeout time.Duration
	timeout       time.Duration
	stderr        io.Writer
	// through, when set, is what probes reach the network through; nil is
	// the real network. Only tests set it.
	through *wire
	// pinned is culprit.yaml's digest when the server started. Every call
	// checks it first: grants are the file's, and a coding agent that can
	// edit the repository must not be able to grant itself a capability
	// between two calls.
	pinned string
}

// manifestDigest is culprit.yaml's SHA-256, or "" when it cannot be read.
func manifestDigest(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

// pinnedTo wraps a handler so it runs only while culprit.yaml is what it
// was when the server started.
func (s *mcpServer) pinnedTo(handler func(context.Context, map[string]any) mcp.Result) func(context.Context, map[string]any) mcp.Result {
	return func(ctx context.Context, arguments map[string]any) mcp.Result {
		if now := manifestDigest(s.manifestPath); s.pinned == "" || now != s.pinned {
			return failed(fmt.Errorf("refused: culprit.yaml has changed since this server started, and its grants " +
				"are fixed for the session. Restart culprit mcp to use the file as it is now"))
		}
		return handler(ctx, arguments)
	}
}

const mcpInstructions = `Culprit diagnoses a running system from a symptom, with read-only probes, and judges whether a fix fixed it. ` +
	`Start with culprit_system_model. Diagnose a failing request with culprit_diagnose; its answer is a fault tree in ` +
	`which every edge cites the readings that established it, and says how to verify. After a change is applied, call ` +
	`culprit_verify with the investigation id and the change named. No tool changes anything, and no argument grants ` +
	`a capability: grants are the environment's, in culprit.yaml.`

func (s *mcpServer) protocol() *mcp.Server {
	if s.pinned == "" {
		s.pinned = manifestDigest(s.manifestPath)
	}
	readOnly := func(title string, openWorld bool) mcp.Annotations {
		return mcp.Annotations{Title: title, ReadOnlyHint: true, DestructiveHint: false, OpenWorldHint: openWorld}
	}
	environment := mcp.Property{Type: mcp.String, Description: "an environment declared under environments: in culprit.yaml; its grants decide what may be probed"}
	return &mcp.Server{
		Name: "culprit", Version: Version, Instructions: mcpInstructions,
		Tools: []mcp.Tool{
			{
				Name: "culprit_system_model", Title: "The system model",
				Description: "The components and connections culprit.yaml declares, each environment's adapter and grants, " +
					"this server's vantage, and the INTENT facts the walk measures against. Reads files only.",
				Input:       mcp.Schema{Properties: map[string]mcp.Property{}},
				Annotations: readOnly("The system model", false),
				Handler:     s.pinnedTo(s.systemModel),
			},
			{
				Name: "culprit_check", Title: "Check the repository",
				Description: "culprit check: every fact the repository states, compared, and every contradiction " +
					"reported with its severity. Reads files only; the same JSON as culprit check --format json.",
				Input: mcp.Schema{Properties: map[string]mcp.Property{
					"components":   {Type: mcp.Strings, Description: "check only these components"},
					"unverifiable": {Type: mcp.Boolean, Description: "also report subjects only one source describes"},
				}},
				Annotations: readOnly("Check the repository", false),
				Handler:     s.pinnedTo(s.check),
			},
			{
				Name: "culprit_explain_connection", Title: "Explain a connection",
				Description: "Everything known about one declared connection: its kind and criticality, the facts and " +
					"contradictions about it and its authentication, and the probes that can measure it — with, " +
					"for an environment, whether its grants allow each. Probes nothing.",
				Input: mcp.Schema{
					Properties: map[string]mcp.Property{
						"from":        {Type: mcp.String, Description: "the calling component"},
						"to":          {Type: mcp.String, Description: "the called component"},
						"environment": environment,
					},
					Required: []string{"from", "to"},
				},
				Annotations: readOnly("Explain a connection", false),
				Handler:     s.pinnedTo(s.explainConnection),
			},
			{
				Name: "culprit_probe", Title: "Probe a subject",
				Description: "culprit probe: the named read-only probes against one subject, under the environment's " +
					"grants. A call naming a probe whose declared capabilities the environment does not grant is refused " +
					"before anything is sent; an item-by-item grant is decided when the probe runs. Readings " +
					"are pass, fail, inconclusive or refused; the same JSON as culprit probe --format json.",
				Input: mcp.Schema{
					Properties: map[string]mcp.Property{
						"target":      {Type: mcp.String, Description: "a subject URI, e.g. connection:order-service->inventory-service"},
						"environment": environment,
						"probes":      {Type: mcp.Strings, Description: "probe ids to run (culprit_explain_connection lists those for a connection)"},
						"inputs":      {Type: mcp.Object, Description: "probe inputs by name, e.g. {\"host\": \"inventory-service\", \"port\": 8002}"},
					},
					Required: []string{"target", "environment", "probes"},
				},
				Annotations: readOnly("Probe a subject", true),
				Handler:     s.pinnedTo(s.probe),
			},
			{
				Name: "culprit_diagnose", Title: "Diagnose a symptom",
				Description: "culprit diagnose: walks the system model from a symptom with read-only probes and returns " +
					"the investigation — a fault tree whose every edge cites its readings, a root, and the " +
					"confidence rubric — and the culprit_verify call that checks a fix. A partial diagnosis says why.",
				Input: mcp.Schema{
					Properties: map[string]mcp.Property{
						"symptom":     {Type: mcp.String, Description: "a subject URI, \"METHOD URL\" (e.g. \"POST http://order-service:8001/orders\") or a component name"},
						"environment": environment,
						"reference":   {Type: mcp.String, Description: "an environment where the symptom does not occur, for the counterfactual"},
					},
					Required: []string{"symptom", "environment"},
				},
				Annotations: readOnly("Diagnose a symptom", true),
				Handler:     s.pinnedTo(s.diagnose),
			},
			{
				Name: "culprit_verify", Title: "Verify a fix",
				Description: "culprit verify: measures every reading of a diagnosis again, twice, compares the " +
					"environment with its record at diagnosis, and judges: verified, not_resolved, regressed, " +
					"changed_underneath or inconclusive. Name what was applied. Culprit never applies a change.",
				Input: mcp.Schema{
					Properties: map[string]mcp.Property{
						"investigation_id": {Type: mcp.String, Description: "the id culprit_diagnose returned"},
						"changes":          {Type: mcp.Strings, Description: "what was applied: image:<component>, config:<component>/<key>, commit:<sha> or action:<what was done>"},
					},
					Required: []string{"investigation_id"},
				},
				Annotations: readOnly("Verify a fix", true),
				Handler:     s.pinnedTo(s.verify),
			},
		},
	}
}

// failed is a call that could not run: a tool result, so the agent reads
// why, not a protocol error.
func failed(err error) mcp.Result {
	return mcp.Result{Structured: map[string]any{"error": err.Error()}, IsError: true}
}

func (s *mcpServer) intent(ctx context.Context, only []string) (check.Report, error) {
	return check.Run(ctx, check.Options{
		ManifestPath: s.manifestPath, Only: only, Now: captureTime(),
		PluginTimeout: s.pluginTimeout, SkipPlugins: s.noPlugins, Version: Version,
	})
}

// ---- culprit_system_model -------------------------------------------------------

type modelComponent struct {
	Name    string `json:"name"`
	Kind    string `json:"kind"`
	Subject string `json:"subject"`
}

type modelConnection struct {
	From        string `json:"from"`
	To          string `json:"to"`
	Kind        string `json:"kind"`
	Criticality string `json:"criticality,omitempty"`
	Subject     string `json:"subject"`
}

type modelEnvironment struct {
	Name    string   `json:"name"`
	Adapter string   `json:"adapter"`
	Grants  []string `json:"grants"`
}

type systemModel struct {
	Components   []modelComponent    `json:"components"`
	Connections  []modelConnection   `json:"connections"`
	Environments []modelEnvironment  `json:"environments"`
	Vantage      string              `json:"vantage"`
	Intent       model.CaptureBundle `json:"intent"`
}

func (s *mcpServer) systemModel(ctx context.Context, _ map[string]any) mcp.Result {
	intent, err := s.intent(ctx, nil)
	if err != nil {
		return failed(err)
	}
	result := systemModel{
		Components: []modelComponent{}, Connections: []modelConnection{}, Environments: []modelEnvironment{},
		Vantage: s.from, Intent: intent.Bundle,
	}
	for _, component := range intent.Manifest.Components {
		subject, err := model.BuildSubject(model.KindComponent, model.Parts{"name": component.Name})
		if err != nil {
			return failed(err)
		}
		result.Components = append(result.Components, modelComponent{Name: component.Name, Kind: component.Kind, Subject: subject})
		for _, connection := range component.Connections {
			entry, err := connectionOf(component.Name, connection)
			if err != nil {
				return failed(err)
			}
			result.Connections = append(result.Connections, entry)
		}
	}
	for _, name := range intent.Manifest.EnvironmentNames() {
		spec := intent.Manifest.Environments[name]
		grants, err := spec.ParsedGrants()
		if err != nil {
			return failed(err)
		}
		names := grants.Names()
		if names == nil {
			names = []string{}
		}
		result.Environments = append(result.Environments, modelEnvironment{Name: name, Adapter: string(spec.Adapter), Grants: names})
	}
	return mcp.Result{Structured: result}
}

func connectionOf(from string, connection extract.ManifestConnection) (modelConnection, error) {
	subject, err := model.BuildSubject(model.KindConnection, model.Parts{"from_component": from, "to_component": connection.To})
	if err != nil {
		return modelConnection{}, err
	}
	return modelConnection{From: from, To: connection.To, Kind: connection.Kind,
		Criticality: connection.Criticality, Subject: subject}, nil
}

// ---- culprit_check ----------------------------------------------------------------

func (s *mcpServer) check(ctx context.Context, arguments map[string]any) mcp.Result {
	result, err := s.intent(ctx, mcp.List(arguments, "components"))
	if err != nil {
		return failed(err)
	}
	report, err := checkReportJSON(result, mcp.Flag(arguments, "unverifiable"))
	if err != nil {
		return failed(err)
	}
	return mcp.Result{Structured: report}
}

// checkReportJSON is exactly what `culprit check --format json` prints.
func checkReportJSON(result check.Report, unverifiable bool) (json.RawMessage, error) {
	var buffer bytes.Buffer
	if err := report.Render(&buffer, "json", report.Input{
		Result: result.Result, Bundle: result.Bundle, Version: Version, Root: result.BaseDir,
		ShowUnverifiable: unverifiable,
	}); err != nil {
		return nil, err
	}
	return json.RawMessage(bytes.TrimSpace(buffer.Bytes())), nil
}

// ---- culprit_explain_connection ----------------------------------------------

type connectionProbe struct {
	ID           string   `json:"id"`
	Capabilities []string `json:"capabilities"`
	Produces     []string `json:"produces"`
	// Granted and Missing are present when an environment is named:
	// whether its grants allow this probe, and if not, what is missing.
	Granted *bool    `json:"granted,omitempty"`
	Missing []string `json:"missing,omitempty"`
}

type connectionExplanation struct {
	Connection  modelConnection   `json:"connection"`
	Subjects    []string          `json:"subjects"`
	Facts       []model.Fact      `json:"facts"`
	Divergences []json.RawMessage `json:"divergences"`
	Probes      []connectionProbe `json:"probes"`
	Environment string            `json:"environment,omitempty"`
}

func (s *mcpServer) explainConnection(ctx context.Context, arguments map[string]any) mcp.Result {
	from, to, environment := mcp.Text(arguments, "from"), mcp.Text(arguments, "to"), mcp.Text(arguments, "environment")
	intent, err := s.intent(ctx, nil)
	if err != nil {
		return failed(err)
	}
	var declared *modelConnection
	if component, ok := componentNamed(intent.Manifest, from); ok {
		for _, connection := range component.Connections {
			if connection.To == to {
				entry, err := connectionOf(from, connection)
				if err != nil {
					return failed(err)
				}
				declared = &entry
			}
		}
	}
	if declared == nil {
		return failed(fmt.Errorf("culprit.yaml declares no connection from %q to %q", from, to))
	}
	var grants *capability.Grants
	if environment != "" {
		parsed, err := grantsFor(intent.Manifest, environment)
		if err != nil {
			return failed(err)
		}
		grants = &parsed
	}

	// Which subjects are this connection's: the connection itself, and
	// every auth relationship along it — decided by parsing, never by
	// matching text.
	about := func(subject string) bool {
		kind, parts, err := model.ParseSubject(subject)
		if err != nil || (kind != model.KindConnection && kind != model.KindAuth) {
			return false
		}
		return parts["from_component"] == from && parts["to_component"] == to
	}
	explanation := connectionExplanation{
		Connection: *declared, Subjects: []string{declared.Subject}, Facts: []model.Fact{},
		Divergences: []json.RawMessage{}, Probes: []connectionProbe{}, Environment: environment,
	}
	seen := map[string]bool{declared.Subject: true}
	for _, fact := range intent.Bundle.Facts {
		if !about(fact.Subject) {
			continue
		}
		explanation.Facts = append(explanation.Facts, fact)
		if !seen[fact.Subject] {
			seen[fact.Subject] = true
			explanation.Subjects = append(explanation.Subjects, fact.Subject)
		}
	}
	// The divergences as culprit check reports them, filtered — the same
	// JSON objects, not a second rendering of them.
	encoded, err := checkReportJSON(intent, false)
	if err != nil {
		return failed(err)
	}
	var checked struct {
		Divergences []json.RawMessage `json:"divergences"`
	}
	if err := json.Unmarshal(encoded, &checked); err != nil {
		return failed(err)
	}
	for _, divergence := range checked.Divergences {
		var subject struct {
			Subject string `json:"subject"`
		}
		if json.Unmarshal(divergence, &subject) == nil && about(subject.Subject) {
			explanation.Divergences = append(explanation.Divergences, divergence)
		}
	}
	// The probes whose readings are about a connection or an auth
	// relationship — what culprit_probe can be asked to run on it.
	manifests := catalogue().Manifests()
	sort.Slice(manifests, func(i, j int) bool { return manifests[i].ID < manifests[j].ID })
	for _, manifest := range manifests {
		var produces []string
		for _, produced := range manifest.Produces {
			// A template is not a subject and does not parse; its kind is
			// what comes before the first colon.
			kind, _, _ := strings.Cut(produced.SubjectTemplate, ":")
			if model.SubjectKind(kind) == model.KindConnection || model.SubjectKind(kind) == model.KindAuth {
				produces = append(produces, produced.SubjectTemplate)
			}
		}
		if len(produces) == 0 {
			continue
		}
		entry := connectionProbe{ID: manifest.ID, Capabilities: manifest.Capabilities, Produces: produces}
		if entry.Capabilities == nil {
			entry.Capabilities = []string{}
		}
		if grants != nil {
			missing := missingCapabilities(*grants, manifest)
			granted := len(missing) == 0
			entry.Granted, entry.Missing = &granted, missing
		}
		explanation.Probes = append(explanation.Probes, entry)
	}
	return mcp.Result{Structured: explanation}
}

// missingCapabilities is what an environment does not grant of what a probe
// declares. An unknown name is missing, never satisfied — as the runner
// treats it.
func missingCapabilities(grants capability.Grants, manifest model.ProbeManifest) []string {
	var missing []string
	for _, name := range manifest.Capabilities {
		if !capability.Known(name) || !grants.Has(capability.Capability(name)) {
			missing = append(missing, name)
		}
	}
	return missing
}

// ---- culprit_probe ------------------------------------------------------------

// reservedInputs are names no probe input may take: a grant is the
// environment's, and an input that looks like one is refused rather than
// passed to a probe that would ignore it.
var reservedInputs = map[string]bool{"grant": true, "grants": true, "capability": true, "capabilities": true, "allow": true}

type probeRefusal struct {
	Probe   string   `json:"probe"`
	Missing []string `json:"missing,omitempty"`
	Reason  string   `json:"reason"`
}

func (s *mcpServer) probe(ctx context.Context, arguments map[string]any) mcp.Result {
	target, environment := mcp.Text(arguments, "target"), mcp.Text(arguments, "environment")
	probes := mcp.List(arguments, "probes")
	if _, _, err := model.ParseSubject(target); err != nil {
		return failed(fmt.Errorf("%q is not a subject URI: %w", target, err))
	}
	if len(probes) == 0 {
		return failed(fmt.Errorf("name at least one probe; culprit_explain_connection lists those for a connection"))
	}
	inputs, err := probeInputs(arguments["inputs"])
	if err != nil {
		return failed(err)
	}
	manifest, err := extract.LoadManifest(s.manifestPath)
	if err != nil {
		return failed(err)
	}
	if _, declared := manifest.Environments[environment]; !declared {
		return failed(fmt.Errorf("environment %q is not declared under environments: in culprit.yaml", environment))
	}
	grants, err := grantsFor(manifest, environment)
	if err != nil {
		return failed(err)
	}
	// Refused before anything is sent: every probe asked for, checked
	// against the environment's grants, and the whole call refused if any
	// one is not granted — an agent learns what is missing, and nothing is
	// dialled.
	var refused []probeRefusal
	for _, id := range probes {
		known, ok := catalogue().Get(id)
		if !ok {
			refused = append(refused, probeRefusal{Probe: id, Reason: "no probe with this id in the catalogue"})
			continue
		}
		if missing := missingCapabilities(grants, known.Manifest()); len(missing) > 0 {
			refused = append(refused, probeRefusal{Probe: id, Missing: missing,
				Reason: "environment " + environment + " does not grant " + strings.Join(missing, ", ")})
		}
	}
	if len(refused) > 0 {
		return mcp.Result{IsError: true, Structured: map[string]any{
			"error":   "refused before anything was sent: grants are the environment's, in culprit.yaml, and no argument can add one",
			"refused": refused,
		}}
	}
	readings, ledger, err := runProbe(ctx, probeInput{
		ManifestPath: s.manifestPath, Environment: environment, Target: target, ProbeIDs: probes,
		Inputs: inputs, AgentID: s.agentID, NoPlugins: s.noPlugins, PluginTimeout: s.pluginTimeout,
		Timeout: s.timeout, Through: s.through,
	})
	if err != nil {
		return failed(err)
	}
	refusals := ledger.Refusals()
	if refusals == nil {
		refusals = []model.Refusal{}
	}
	return mcp.Result{Structured: map[string]any{"readings": readings, "refused": refusals}}
}

// probeInputs is the inputs object as a probe takes it, as `--input`
// gives it: a whole number — written as a number or as a string of digits —
// an int; anything else as JSON decoded it.
func probeInputs(raw any) (map[string]any, error) {
	given, _ := raw.(map[string]any)
	inputs := map[string]any{}
	for name, value := range given {
		if reservedInputs[strings.ToLower(name)] || capability.Known(strings.ToLower(name)) {
			return nil, fmt.Errorf("refused: %q is not a probe input. Grants are the environment's, in culprit.yaml; "+
				"no argument can add one", name)
		}
		inputs[name] = plainNumber(value)
	}
	return inputs, nil
}

func plainNumber(value any) any {
	switch typed := value.(type) {
	case string:
		// The same rule as parseInputs: only a string that is exactly an
		// integer's own spelling becomes one.
		var number int
		if _, err := fmt.Sscanf(typed, "%d", &number); err == nil && fmt.Sprintf("%d", number) == typed {
			return number
		}
		return typed
	case json.Number:
		if whole, err := typed.Int64(); err == nil {
			return int(whole)
		}
		if real, err := typed.Float64(); err == nil {
			return real
		}
		return typed.String()
	case []any:
		list := make([]any, len(typed))
		for index, item := range typed {
			list[index] = plainNumber(item)
		}
		return list
	}
	return value
}

// ---- culprit_diagnose -------------------------------------------------------------

// changeKind is one way to name what was applied, for culprit_verify.
type changeKind struct {
	Kind     string `json:"kind"`
	Form     string `json:"form"`
	Explains string `json:"explains"`
}

var changeKinds = []changeKind{
	{Kind: string(model.ChangeConfig), Form: "config:<component>/<key>", Explains: "that configuration key on that component"},
	{Kind: string(model.ChangeImage), Form: "image:<component>", Explains: "that component's image and packages"},
	{Kind: string(model.ChangeCommit), Form: "commit:<sha>", Explains: "nothing a capture records"},
	{Kind: string(model.ChangeAction), Form: "action:<what was done>", Explains: "nothing a capture records"},
}

type howToVerify struct {
	Tool        string         `json:"tool"`
	Arguments   map[string]any `json:"arguments"`
	ChangeKinds []changeKind   `json:"change_kinds"`
}

type diagnosis struct {
	Investigation model.Investigation `json:"investigation"`
	Verify        howToVerify         `json:"verify"`
}

func (s *mcpServer) diagnose(ctx context.Context, arguments map[string]any) mcp.Result {
	investigation, err := runDiagnose(ctx, diagnoseInput{
		ManifestPath: s.manifestPath, Environment: mcp.Text(arguments, "environment"), From: s.from,
		Reference: mcp.Text(arguments, "reference"), Symptom: mcp.Text(arguments, "symptom"),
		AgentID: s.agentID, StateDir: s.stateDir, NoPlugins: s.noPlugins, PluginTimeout: s.pluginTimeout,
		Timeout: s.timeout, Through: s.through, Stderr: s.stderrOrDiscard(),
		How: func(id string) string { return "culprit_verify with investigation_id " + id },
	})
	if err != nil {
		return failed(err)
	}
	return mcp.Result{Structured: diagnosis{
		Investigation: investigation,
		Verify: howToVerify{
			Tool:        "culprit_verify",
			Arguments:   map[string]any{"investigation_id": investigation.ID, "changes": []string{}},
			ChangeKinds: changeKinds,
		},
	}}
}

// ---- culprit_verify -----------------------------------------------------------------

func (s *mcpServer) verify(ctx context.Context, arguments map[string]any) mcp.Result {
	verification, err := runVerify(ctx, verifyInput{
		ManifestPath: s.manifestPath, StateDir: s.stateDir, From: s.from,
		InvestigationID: mcp.Text(arguments, "investigation_id"), Changes: mcp.List(arguments, "changes"),
		AgentID: s.agentID, NoPlugins: s.noPlugins, PluginTimeout: s.pluginTimeout, Timeout: s.timeout,
		Through: s.through, Stderr: s.stderrOrDiscard(),
	})
	if err != nil {
		return failed(err)
	}
	return mcp.Result{Structured: verification}
}

func (s *mcpServer) stderrOrDiscard() io.Writer {
	if s.stderr != nil {
		return s.stderr
	}
	return os.Stderr
}
