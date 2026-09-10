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

// DatabaseName returns the schema-subject database name.
func (d DatabaseSpec) DatabaseName(component string) string {
	if strings.TrimSpace(d.Name) != "" {
		return d.Name
	}
	return component + "-db"
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
			}
			if endpoint := settings.Endpoint; endpoint != nil {
				host := strings.TrimSpace(endpoint.Host)
				if host == "" || strings.ContainsAny(host, "/@: ") {
					return fmt.Errorf("%s.endpoint.host: a bare hostname, with no scheme, "+
						"port or credentials", at)
				}
				if endpoint.Port < 1 || endpoint.Port > 65535 {
					return fmt.Errorf("%s.endpoint.port: 1 to 65535", at)
				}
			}
		}
	}
	return nil
}
