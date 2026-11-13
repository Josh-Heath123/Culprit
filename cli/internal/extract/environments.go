package extract

import (
	"fmt"
	"regexp"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"

	"github.com/josh-heath123/culprit/cli/internal/capability"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The `environments:` section (Phase 30 field 10): per-environment
// adapter config and grants.
//
//	environments:
//	  production:
//	    adapter: compose            # compose | kubernetes | process | exec
//	    compose:
//	      project: shop-prod
//	    grants:
//	      config.read.names: true
//	      deploy.metadata.read: true
//	      db.metadata.read: true
//	    components:
//	      orders-api:
//	        workload: orders-api     # compose service / k8s deployment
//	        database:
//	          dsn_env: PROD_ORDERS_DB_URL
//
// Parsed here because the manifest is loaded here; *acted on* only by
// internal/capture. `culprit check` ignores the section entirely — it
// reads no environment, and must not start to because a manifest grew a
// block describing one.
//
// # No values, still
//
// `culprit.yaml` names things and never carries their values. That rule
// is sharpest here, because this is the section that describes how to
// reach a production database — the natural place to paste a connection
// string. So a database is reached through `dsn_env`, the *name* of a
// variable in the environment `culprit` itself runs in, and a value in
// that field that looks like a DSN is refused outright. The Python
// loader applies its credential check to the whole file; this is the Go
// side refusing the one field in it most likely to receive one.

// Adapter names. A closed set: an unknown adapter is a validation error,
// never a fallback, because "I captured nothing because I did not
// recognise how you asked" must not look like "I captured nothing
// because there was nothing there".
const (
	AdapterCompose    = "compose"
	AdapterKubernetes = "kubernetes"
	AdapterProcess    = "process"
	AdapterExec       = "exec"
)

// EnvironmentSpec is one environment.
type EnvironmentSpec struct {
	Adapter    string                          `yaml:"adapter"`
	Compose    ComposeSpec                     `yaml:"compose"`
	Kubernetes KubernetesSpec                  `yaml:"kubernetes"`
	Exec       map[string][]string             `yaml:"exec"`
	Grants     map[string]yaml.Node            `yaml:"grants"`
	Components map[string]EnvironmentComponent `yaml:"components"`
	// Endpoints are where the isolation walk sends requests to each
	// component, as seen from wherever `culprit diagnose` runs (Phase 32).
	// Separate from components: on purpose. That map is what a capture
	// reads, and under the process adapter it can name only the one
	// component culprit runs inside; the walk needs to reach all of them.
	// A component's own endpoint: is used when it has no entry here.
	Endpoints map[string]EndpointSpec `yaml:"endpoints"`
}

// ComposeSpec locates a Compose project.
type ComposeSpec struct {
	// Project is `docker compose -p`. Empty uses Compose's own default
	// (the directory name), which is rarely what a real deployment uses,
	// so it is worth setting.
	Project string `yaml:"project"`
	// Files are `docker compose -f`, relative to culprit.yaml.
	Files []string `yaml:"files"`
}

// KubernetesSpec locates a cluster and namespace. Both empty means
// kubectl's own current context and namespace.
type KubernetesSpec struct {
	Context   string `yaml:"context"`
	Namespace string `yaml:"namespace"`
}

// EnvironmentComponent says where one component runs in this environment
// and what to look at.
type EnvironmentComponent struct {
	// Workload is the Compose service or Kubernetes Deployment. Defaults
	// to the component's own name.
	Workload string `yaml:"workload"`
	// Container picks one container in a multi-container Pod. Defaults
	// to the first.
	Container string `yaml:"container"`
	// EnvCommand names an `exec:` entry whose output is this component's
	// environment as NUL-delimited KEY=VALUE pairs (`env -0`) or a JSON
	// object — never lines; see capture.execAdapter. Required by the exec
	// adapter and meaningless to the others.
	EnvCommand string `yaml:"env_command"`
	// Packages names an `exec:` entry whose output lists installed
	// packages (`pip freeze` or `npm ls --json` format).
	Packages string        `yaml:"packages"`
	Database *DatabaseSpec `yaml:"database"`
	Endpoint *EndpointSpec `yaml:"endpoint"`
	// Tokens maps a component this one calls to the *name* of a variable,
	// in the environment of the agent running at this component, holding
	// the bearer token this component presents to it. Never the token.
	// The isolation walk reads it to ask probe.auth.token_shape whether
	// the token carries the audience the callee expects (Phase 32).
	Tokens map[string]string `yaml:"tokens"`
}

// DatabaseSpec is how to reach a component's database for metadata.
type DatabaseSpec struct {
	// DSNEnv is the *name* of a variable in culprit's own environment
	// holding the connection string. Never the connection string.
	DSNEnv string `yaml:"dsn_env"`
	// Name is the `database` part of every `schema:` subject this
	// produces. Defaults to `<component>-db`, which is what the Python
	// extractor uses on the INTENT side — so the default is what makes
	// the two planes' schema subjects meet.
	Name string `yaml:"name"`
}

// EndpointSpec is one network endpoint to check reachability of.
type EndpointSpec struct {
	Host string `yaml:"host"`
	Port int    `yaml:"port"`
	// TLS also inspects the certificate the endpoint presents.
	TLS bool `yaml:"tls"`
	// HealthPath is the path the isolation walk requests to ask "does a
	// request entering at this component succeed?" (Phase 32). The walk
	// bisects on the answer, so it should exercise what the component
	// calls on the request path; a shallow health check that answers 200
	// without touching its dependencies makes the walk trust a pass it
	// should not (docs/LIMITS.md).
	HealthPath string `yaml:"health_path"`
}

var (
	envVarName = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)
	// A connection string with inline credentials, or anything else the
	// shape classifier calls a secret. The same two tests the value
	// classifier uses, so "this looks like a credential" means one thing
	// throughout the binary.
	credentialLike = func(text string) bool {
		format := model.ClassifyFormat(text)
		return format == model.FormatDSN || format == model.FormatSecret
	}
)

// EnvironmentNames returns the declared environments in a stable order.
func (m *Manifest) EnvironmentNames() []string {
	names := make([]string, 0, len(m.Environments))
	for name := range m.Environments {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// ParsedGrants decodes one environment's grants into a capability set.
func (e EnvironmentSpec) ParsedGrants() (capability.Grants, error) {
	raw := map[string]capability.Raw{}
	for name, node := range e.Grants {
		node := node
		switch node.Kind {
		case yaml.ScalarNode:
			var enabled bool
			if err := node.Decode(&enabled); err != nil {
				return capability.Grants{}, fmt.Errorf("grants.%s: expected true, false or a list", name)
			}
			raw[name] = capability.Raw{Enabled: &enabled}
		case yaml.SequenceNode:
			var items []string
			if err := node.Decode(&items); err != nil {
				return capability.Grants{}, fmt.Errorf("grants.%s: expected a list of names", name)
			}
			raw[name] = capability.Raw{Items: items}
		default:
			return capability.Grants{}, fmt.Errorf("grants.%s: expected true, false or a list", name)
		}
	}
	return capability.Parse(raw)
}

// WorkloadFor returns the workload name for a component, defaulting to
// the component's own name.
func (c EnvironmentComponent) WorkloadFor(component string) string {
	if strings.TrimSpace(c.Workload) != "" {
		return c.Workload
	}
	return component
}

// DatabaseName returns the schema-subject database name: the name given,
// which validateEnvironments holds equal to the schema database rule (Q34),
// or, when none is given, the rule's own.
func (d DatabaseSpec) DatabaseName(m *Manifest, component string) string {
	if strings.TrimSpace(d.Name) != "" {
		return d.Name
	}
	return m.SchemaDatabase(component)
}

func (m *Manifest) validateEnvironments() error {
	declared := map[string]bool{}
	for _, component := range m.Components {
		declared[component.Name] = true
	}

	for _, name := range m.EnvironmentNames() {
		spec := m.Environments[name]
		where := "environments." + name
		if strings.TrimSpace(name) == "" || strings.ContainsAny(name, " /\\") {
			return fmt.Errorf("%s: an environment name may not be blank or contain spaces or slashes", where)
		}

		switch spec.Adapter {
		case AdapterCompose, AdapterKubernetes, AdapterProcess, AdapterExec:
		case "":
			return fmt.Errorf("%s.adapter: required (compose, kubernetes, process or exec)", where)
		default:
			return fmt.Errorf("%s.adapter: %q is not an adapter (compose, kubernetes, process or exec)",
				where, spec.Adapter)
		}

		grants, err := spec.ParsedGrants()
		if err != nil {
			return fmt.Errorf("%s.%w", where, err)
		}

		for command, argv := range spec.Exec {
			if len(argv) == 0 || strings.TrimSpace(argv[0]) == "" {
				return fmt.Errorf("%s.exec.%s: an empty command", where, command)
			}
			for _, argument := range argv {
				if credentialLike(argument) {
					return fmt.Errorf("%s.exec.%s: an argument looks like a credential. "+
						"culprit.yaml is a committed file; pass credentials through the "+
						"environment the command runs in, never on its command line", where, command)
				}
			}
			// An exec entry nothing is allowed to run is almost always a
			// grant somebody forgot. Said at load time, rather than as a
			// refusal at capture time that reads like the tool's fault.
			if !grants.Allows(capability.ProcessExecAllowlist, command) {
				return fmt.Errorf("%s.exec.%s: declared but not in grants.process.exec.allowlist, "+
					"so it can never run. Add it to the allowlist or remove it", where, command)
			}
		}

		if len(spec.Components) == 0 {
			return fmt.Errorf("%s.components: name at least one component to capture", where)
		}
		if spec.Adapter == AdapterProcess && len(spec.Components) != 1 {
			// A process has one environment. Attributing it to two
			// components would put one workload's keys on another's
			// subjects — the confidently-wrong attribution the extraction
			// side already refuses to make (see ExtractConfig).
			return fmt.Errorf("%s: the process adapter captures the environment culprit itself "+
				"runs in, which belongs to exactly one component; name one", where)
		}

		componentNames := make([]string, 0, len(spec.Components))
		for component := range spec.Components {
			componentNames = append(componentNames, component)
		}
		sort.Strings(componentNames)
		for _, component := range componentNames {
			settings := spec.Components[component]
			at := where + ".components." + component
			if !declared[component] {
				return fmt.Errorf("%s: no component named %s is declared in this file", at, component)
			}
			for _, reference := range []struct{ field, command string }{
				{"env_command", settings.EnvCommand},
				{"packages", settings.Packages},
			} {
				if reference.command == "" {
					continue
				}
				if _, ok := spec.Exec[reference.command]; !ok {
					return fmt.Errorf("%s.%s: names %s, which is not declared under %s.exec",
						at, reference.field, reference.command, where)
				}
			}
			if spec.Adapter == AdapterExec && settings.EnvCommand == "" {
				return fmt.Errorf("%s.env_command: the exec adapter reads a component's "+
					"environment from a command; name one from %s.exec", at, where)
			}
			if database := settings.Database; database != nil {
				if !envVarName.MatchString(database.DSNEnv) {
					// The message never repeats the field's content: if it
					// is not a variable name, the likeliest thing it is
					// is the connection string itself.
					return fmt.Errorf("%s.database.dsn_env: must be the *name* of an environment "+
						"variable holding the connection string, never the connection string", at)
				}
				// Q34: the name, where given, is the one the model derives,
				// or the live schema would be on a database the migrations
				// and the budgets are not.
				if named := strings.TrimSpace(database.Name); named != "" {
					if derived := m.SchemaDatabase(component); named != derived {
						return fmt.Errorf("%s.database.name: %q, but %s's schema database is %q "+
							"(the database it connects to by its one sql edge, else %s-db); "+
							"give that name or leave name out", at, named, component, derived, component)
					}
				}
			}
			if endpoint := settings.Endpoint; endpoint != nil {
				if err := validateEndpoint(at+".endpoint", *endpoint); err != nil {
					return err
				}
			}
			for callee, variable := range settings.Tokens {
				if _, declared := m.componentNamed(callee); !declared {
					return fmt.Errorf("%s.tokens: %q is not a component in this file", at, callee)
				}
				if !envVarName.MatchString(variable) {
					// As for dsn_env, never echoed: if it is not a variable
					// name, the likeliest thing it is is the token.
					return fmt.Errorf("%s.tokens.%s: must be the *name* of an environment "+
						"variable holding the token, never the token", at, callee)
				}
			}
		}
		for component, endpoint := range spec.Endpoints {
			at := fmt.Sprintf("environments.%s.endpoints.%s", name, component)
			if _, declared := m.componentNamed(component); !declared {
				return fmt.Errorf("%s: not a component in this file", at)
			}
			if err := validateEndpoint(at, endpoint); err != nil {
				return err
			}
		}
	}
	return nil
}

func validateEndpoint(at string, endpoint EndpointSpec) error {
	host := strings.TrimSpace(endpoint.Host)
	if host == "" || strings.ContainsAny(host, "/@: ") {
		return fmt.Errorf("%s.host: a bare hostname, with no scheme, port or credentials", at)
	}
	if endpoint.Port < 1 || endpoint.Port > 65535 {
		return fmt.Errorf("%s.port: 1 to 65535", at)
	}
	if path := endpoint.HealthPath; path != "" &&
		(!strings.HasPrefix(path, "/") || strings.ContainsAny(path, " @?#")) {
		return fmt.Errorf("%s.health_path: a path such as /health, with no query string "+
			"or credentials", at)
	}
	return nil
}
