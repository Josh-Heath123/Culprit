// Package agent is `culprit agent` (docs/DIAGNOSTIC_PLAN.md Phase 33): a
// long-lived process that takes tasks — run a named probe, or walk from a
// symptom — from a source, runs them under the grants its own
// configuration gives, and writes every task and every probe to an
// append-only, hash-chained audit log before it returns a result.
//
// # The authority rule
//
// The agent is the authority on its own capabilities, not whoever sends
// it tasks. Its grants are what this file's configuration says, re-read
// before every task, intersected with whatever allowance the task
// carries. An allowance can withhold a grant; it can never add one. A
// task needing a grant the agent does not hold is refused before
// anything is dialled, and the refusal is a reading and an audit entry.
//
// This package opens no socket and links no networking package
// (TestTheNetworkBoundaryIsAnAllowlist): it reads files, writes files and
// decides. Running a probe is the Executor's job, which cmd/culprit
// supplies.
package agent

import (
	"bytes"
	"errors"
	"fmt"
	"net/netip"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"

	"github.com/josh-heath123/culprit/cli/internal/capability"
)

// yamlErrorLine finds the line number in a yaml.v3 syntax error.
var yamlErrorLine = regexp.MustCompile(`line (\d+)`)

// ConfigVersion is the only configuration format this binary reads.
const ConfigVersion = 1

// Config is the agent's local configuration — a file the operator writes
// and nothing else edits. Example:
//
//	version: 1
//	agent_id: prod-eu-1
//	manifest: ./culprit.yaml
//	environments:
//	  production:
//	    grants:
//	      net.dns.resolve: true
//	      net.tcp.connect: true
//	      config.inspect.values: [order-service/INVENTORY_TOKEN]
//
// `manifest` is the system model and the environments' adapters and
// endpoints. The grants written in that culprit.yaml are ignored: it is
// a repository file, and the agent's authority comes only from here.
type Config struct {
	Path         string
	AgentID      string
	Manifest     string // resolved against the configuration's directory
	Environments map[string]capability.Grants
	// ControlPlane is the control plane's API root, when the agent takes
	// its tasks from one (Phase 33 part 2): the only address
	// internal/transport will dial. Empty for an agent that reads a local
	// task directory.
	ControlPlane string
	// AllowPlainHTTP is control_plane.allow_plain_http: the operator's
	// explicit consent to reach a non-loopback control plane over plain
	// http. The agent reports it at every start; no shipped recipe sets it.
	AllowPlainHTTP bool
	// Key is the agent's Ed25519 private key file, resolved against the
	// configuration's directory. `culprit agent init` writes it.
	Key string
}

// GrantNames is every environment's grants by name: what the agent
// reports holding when it pairs, and all an operator may then allow.
func (c Config) GrantNames() map[string][]string {
	names := map[string][]string{}
	for environment, grants := range c.Environments {
		names[environment] = grants.Names()
	}
	return names
}

// ConfigError is a configuration the agent refuses to run under. It
// names the file and line, because a grant that does not parse is a
// permission the operator believes they either gave or withheld.
type ConfigError struct {
	Path    string
	Line    int
	Message string
}

func (e *ConfigError) Error() string {
	if e.Line > 0 {
		return fmt.Sprintf("%s:%d: %s", e.Path, e.Line, e.Message)
	}
	return fmt.Sprintf("%s: %s", e.Path, e.Message)
}

// LoadConfig reads and validates the configuration. The agent calls it
// before every task, so a grant removed from the file takes effect on the
// next task with no restart.
func LoadConfig(path string) (Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Config{}, &ConfigError{Path: path, Message: "cannot be read: " + reasonOf(err)}
	}
	return ParseConfig(path, data)
}

func reasonOf(err error) string {
	switch {
	case errors.Is(err, os.ErrNotExist):
		return "no such file"
	case errors.Is(err, os.ErrPermission):
		return "permission denied"
	}
	return "read error"
}

// ParseConfig validates a configuration's bytes. Every refusal names its
// line.
func ParseConfig(path string, data []byte) (Config, error) {
	fail := func(line int, format string, args ...any) (Config, error) {
		return Config{}, &ConfigError{Path: path, Line: line, Message: fmt.Sprintf(format, args...)}
	}
	var document yaml.Node
	decoder := yaml.NewDecoder(bytes.NewReader(data))
	if err := decoder.Decode(&document); err != nil {
		// The parser's own message can quote the file's text, which may
		// hold a secret pasted in by mistake; only its line number is kept.
		line := 0
		if match := yamlErrorLine.FindStringSubmatch(err.Error()); match != nil {
			line, _ = strconv.Atoi(match[1])
		}
		return fail(line, "is not valid YAML")
	}
	if len(document.Content) != 1 || document.Content[0].Kind != yaml.MappingNode {
		return fail(document.Line, "must be a mapping of version, agent_id, manifest and environments")
	}
	root := document.Content[0]

	config := Config{Path: path, Environments: map[string]capability.Grants{}}
	version := 0
	seen := map[string]bool{}
	for index := 0; index+1 < len(root.Content); index += 2 {
		key, value := root.Content[index], root.Content[index+1]
		if seen[key.Value] {
			return fail(key.Line, "%s is given twice", key.Value)
		}
		seen[key.Value] = true
		switch key.Value {
		case "version":
			if value.Kind != yaml.ScalarNode || value.Value != fmt.Sprint(ConfigVersion) {
				return fail(value.Line, "version must be %d", ConfigVersion)
			}
			version = ConfigVersion
		case "agent_id":
			if value.Kind != yaml.ScalarNode || strings.TrimSpace(value.Value) == "" {
				return fail(value.Line, "agent_id must be a non-empty name")
			}
			config.AgentID = strings.TrimSpace(value.Value)
		case "manifest":
			if value.Kind != yaml.ScalarNode || strings.TrimSpace(value.Value) == "" {
				return fail(value.Line, "manifest must be the path to a culprit.yaml")
			}
			manifest := strings.TrimSpace(value.Value)
			if !filepath.IsAbs(manifest) {
				manifest = filepath.Join(filepath.Dir(path), manifest)
			}
			config.Manifest = manifest
		case "control_plane":
			address, allowPlain, err := controlPlane(value)
			if err != nil {
				return fail(value.Line, "%s", err.Error())
			}
			config.ControlPlane, config.AllowPlainHTTP = address, allowPlain
		case "key":
			if value.Kind != yaml.ScalarNode || strings.TrimSpace(value.Value) == "" {
				return fail(value.Line, "key must be the path to the agent's key file")
			}
			keyPath := strings.TrimSpace(value.Value)
			if !filepath.IsAbs(keyPath) {
				keyPath = filepath.Join(filepath.Dir(path), keyPath)
			}
			config.Key = keyPath
		case "environments":
			if value.Kind != yaml.MappingNode {
				return fail(value.Line, "environments must map each environment name to its grants")
			}
			for envIndex := 0; envIndex+1 < len(value.Content); envIndex += 2 {
				nameNode, envNode := value.Content[envIndex], value.Content[envIndex+1]
				name := strings.TrimSpace(nameNode.Value)
				if name == "" || strings.Contains(name, "*") || strings.EqualFold(name, "all") {
					return fail(nameNode.Line, "environments.%s: name each environment exactly; "+
						"a wildcard or `all` is not an environment", nameNode.Value)
				}
				if _, duplicate := config.Environments[name]; duplicate {
					return fail(nameNode.Line, "environments.%s is given twice", name)
				}
				grants, err := parseEnvironment(path, name, envNode)
				if err != nil {
					return Config{}, err
				}
				config.Environments[name] = grants
			}
		default:
			return fail(key.Line, "%s is not a configuration key "+
				"(version, agent_id, manifest, environments, control_plane, key)", key.Value)
		}
	}
	switch {
	case version == 0:
		return fail(root.Line, "version: %d is required", ConfigVersion)
	case config.AgentID == "":
		return fail(root.Line, "agent_id is required")
	case config.Manifest == "":
		return fail(root.Line, "manifest is required: the culprit.yaml that describes the system")
	case len(config.Environments) == 0:
		return fail(root.Line, "environments is required: an agent with no environment can run nothing")
	case config.ControlPlane != "" && config.Key == "":
		return fail(root.Line, "an agent with a control_plane needs key: the file its signing key is in")
	}
	return config, nil
}

// parseEnvironment reads one environment's grants. The checks the shared
// capability parser makes (no *.write, allowlists named per item) still
// apply; before it, every grant line is checked here so that a refusal
// names its line: a wildcard, `all`, or a name that is not a capability.
func parseEnvironment(path, name string, node *yaml.Node) (capability.Grants, error) {
	fail := func(line int, format string, args ...any) (capability.Grants, error) {
		return capability.Grants{}, &ConfigError{Path: path, Line: line, Message: fmt.Sprintf(format, args...)}
	}
	if node.Kind != yaml.MappingNode {
		return fail(node.Line, "environments.%s must be a mapping with grants:", name)
	}
	var grantsNode *yaml.Node
	for index := 0; index+1 < len(node.Content); index += 2 {
		key := node.Content[index]
		if key.Value != "grants" {
			return fail(key.Line, "environments.%s.%s is not a key (grants)", name, key.Value)
		}
		grantsNode = node.Content[index+1]
	}
	if grantsNode == nil {
		return fail(node.Line, "environments.%s has no grants:", name)
	}
	if grantsNode.Kind != yaml.MappingNode {
		return fail(grantsNode.Line, "environments.%s.grants must map each capability to true, false or a list", name)
	}

	raw := map[string]capability.Raw{}
	lines := map[string]int{}
	for index := 0; index+1 < len(grantsNode.Content); index += 2 {
		key, value := grantsNode.Content[index], grantsNode.Content[index+1]
		grant := strings.TrimSpace(key.Value)
		where := fmt.Sprintf("environments.%s.grants.%s", name, key.Value)
		switch {
		case strings.Contains(grant, "*"):
			return fail(key.Line, "%s: a wildcard is not a grant; list each capability by name", where)
		case strings.EqualFold(grant, "all"):
			return fail(key.Line, "%s: there is no `all`; list each capability by name", where)
		case strings.HasSuffix(grant, ".write"):
			return fail(key.Line, "%s: no write capability exists; Culprit never changes what it reads", where)
		case !capability.Known(grant):
			return fail(key.Line, "%s: not a capability (docs/PERMISSIONS.md lists them); "+
				"a typo here is a permission you believe you gave and did not", where)
		}
		if _, duplicate := raw[grant]; duplicate {
			return fail(key.Line, "%s is given twice", where)
		}
		entry, err := rawGrant(value)
		if err != nil {
			return fail(value.Line, "%s: %s", where, err.Error())
		}
		raw[grant] = entry
		lines[grant] = key.Line
	}
	grants, err := capability.Parse(raw)
	if err != nil {
		// capability.Parse names the grant; find its line.
		line := 0
		names := make([]string, 0, len(lines))
		for grant := range lines {
			names = append(names, grant)
		}
		sort.Strings(names)
		for _, grant := range names {
			if strings.Contains(err.Error(), "grants."+grant+":") {
				line = lines[grant]
				break
			}
		}
		return fail(line, "environments.%s.%s", name, err.Error())
	}
	return grants, nil
}

// rawGrant is a grant's value: a bool, or a list of named items. A
// scalar `all` or `*`, or any item containing `*`, is refused here — the
// capability parser would refuse an item wildcard too, but not say where.
func rawGrant(value *yaml.Node) (capability.Raw, error) {
	switch value.Kind {
	case yaml.ScalarNode:
		text := strings.TrimSpace(value.Value)
		if text == "*" || strings.EqualFold(text, "all") {
			return capability.Raw{}, fmt.Errorf("`%s` grants nothing by name; write true, false or a list of items", text)
		}
		var enabled bool
		if err := value.Decode(&enabled); err != nil {
			return capability.Raw{}, fmt.Errorf("expected true, false or a list of items")
		}
		return capability.Raw{Enabled: &enabled}, nil
	case yaml.SequenceNode:
		items := make([]string, 0, len(value.Content))
		for _, item := range value.Content {
			text := strings.TrimSpace(item.Value)
			if item.Kind != yaml.ScalarNode {
				return capability.Raw{}, fmt.Errorf("each item must be a name")
			}
			if strings.Contains(text, "*") || strings.EqualFold(text, "all") {
				return capability.Raw{}, fmt.Errorf("item %q: name each item exactly; wildcards and `all` are not items", text)
			}
			items = append(items, text)
		}
		return capability.Raw{Items: items}, nil
	}
	return capability.Raw{}, fmt.Errorf("expected true, false or a list of items")
}

// controlPlane reads `control_plane: {url: ..., allow_plain_http: ...}`:
// an https URL with a host, no credentials in it, no query and no
// fragment. The URL's path is the API root every request is relative to
// (".../api" behind the dashboard's proxy).
//
// Plain http is refused (Phase 33 part 3): the signature stops a forged or
// replayed request, but not someone on the path reading the tasks and the
// readings. It is allowed to a loopback address, which never leaves the
// machine, or when the operator writes allow_plain_http: true — which the
// agent reports at every start, and which no shipped recipe sets.
func controlPlane(node *yaml.Node) (string, bool, error) {
	if node.Kind != yaml.MappingNode {
		return "", false, fmt.Errorf("control_plane must be a mapping with url:")
	}
	address, allowPlain := "", false
	for index := 0; index+1 < len(node.Content); index += 2 {
		key, value := node.Content[index], node.Content[index+1]
		switch key.Value {
		case "url":
			address = strings.TrimSpace(value.Value)
		case "allow_plain_http":
			if value.Kind != yaml.ScalarNode || (value.Value != "true" && value.Value != "false") {
				return "", false, fmt.Errorf("control_plane.allow_plain_http must be true or false")
			}
			allowPlain = value.Value == "true"
		default:
			return "", false, fmt.Errorf("control_plane.%s is not a key (url, allow_plain_http)", key.Value)
		}
	}
	parsed, err := url.Parse(address)
	switch {
	case address == "" || err != nil:
		return "", false, fmt.Errorf("control_plane.url must be the control plane's API root, e.g. https://culprit.example.com/api")
	case parsed.Scheme != "https" && parsed.Scheme != "http":
		return "", false, fmt.Errorf("control_plane.url must be https")
	case parsed.Host == "" || parsed.Hostname() == "":
		return "", false, fmt.Errorf("control_plane.url names no host")
	case parsed.User != nil:
		return "", false, fmt.Errorf("control_plane.url must not carry credentials: the agent signs with its key")
	case parsed.RawQuery != "" || parsed.Fragment != "":
		return "", false, fmt.Errorf("control_plane.url must not have a query or fragment")
	case parsed.Scheme == "http" && !allowPlain && !IsLoopback(parsed.Hostname()):
		return "", false, fmt.Errorf("control_plane.url is plain http to %s: use https, "+
			"or set control_plane.allow_plain_http: true to send tasks and readings unencrypted", parsed.Hostname())
	}
	return strings.TrimRight(parsed.String(), "/"), allowPlain, nil
}

// IsLoopback reports whether host names this machine only: `localhost`, or
// a loopback IP literal (127.0.0.0/8, ::1). A name that merely starts like
// one, such as 127.0.0.1.example.com, is not.
func IsLoopback(host string) bool {
	if strings.EqualFold(host, "localhost") {
		return true
	}
	// net/netip, not net: this package may not link the network (D8).
	addr, err := netip.ParseAddr(host)
	return err == nil && addr.IsLoopback()
}
