package capture

import (
	"context"
	"encoding/json"
	"fmt"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/extract"
)

// Adapters: how to find one component's running workload in one kind of
// environment, and read its environment variables and image.
//
// Four, per field 4: Docker/Compose, Kubernetes, plain process, and a
// generic `exec` adapter for anything else. Each answers the same two
// questions and knows nothing about what the answers are used for.
//
// # Environment values pass through here, and stop here
//
// `docker inspect` returns a container's environment *with values*, and
// so does a Deployment spec with literal `value:` entries. There is no
// way to ask either for names alone. So the adapter hands the caller a
// map of real values, and the caller (capture.go) immediately reduces
// each one to a ValueShape — keeping the literal only for a key on the
// `config.read.values` allowlist — and drops the map. Nothing in this
// file logs, formats or returns a value in an error.

// Workload is what an adapter found for one component.
type Workload struct {
	// Env is the workload's environment. Values are real; see above.
	Env map[string]EnvValue
	// Complete is false when the adapter knows the environment has keys
	// it could not enumerate — a Kubernetes `envFrom` whose ConfigMap or
	// Secret could not be read. An incomplete environment is still
	// reported, but must not be used to conclude that a key is *absent*.
	Complete bool
	// Incomplete says why, in the adapter's own closed words.
	Incomplete []string
	// Artefact names what was read, for provenance: "compose:orders-api".
	Artefact string
	// Replicas counts how many instances were found; only the first, in a
	// stable order, is read. Said in the report when it is more than one.
	Replicas int
}

// EnvValue is one environment variable as the adapter saw it.
type EnvValue struct {
	// Value is the literal, when the adapter could see it.
	Value string
	// Known is false when the key is set by reference — a Kubernetes
	// `valueFrom` or a Secret's key — so the key exists but its value was
	// not visible to this adapter. Shaped as UnknownShape, not guessed.
	Known bool
}

// Image is what an adapter found out about a workload's image.
type Image struct {
	// Reference is the image as configured: "ghcr.io/acme/orders:1.4".
	Reference string
	// Digest is a registry content digest ("sha256:..."), when known.
	Digest string
	// ID is a local image id, for images that were built rather than
	// pulled and so have no registry digest. Reported separately from
	// Digest: comparing a registry digest in one environment with a local
	// id in another would report a difference between two ways of naming
	// the same image.
	ID string
}

// Adapter is one kind of environment.
type Adapter interface {
	Name() string
	Workload(ctx context.Context, component string, settings extract.EnvironmentComponent) (Workload, error)
	Image(ctx context.Context, component string, settings extract.EnvironmentComponent) (Image, error)
}

// ErrNoImage is an adapter's honest answer to "which image" when the
// environment it reads has no such concept — a plain process.
var ErrNoImage = fmt.Errorf("this adapter has no notion of an image")

// NewAdapter builds the adapter an environment names.
func NewAdapter(
	spec extract.EnvironmentSpec, manifestDir string, runner Runner, environ func() []string,
) (Adapter, error) {
	switch spec.Adapter {
	case extract.AdapterCompose:
		return composeAdapter{spec: spec.Compose, dir: manifestDir, runner: runner}, nil
	case extract.AdapterKubernetes:
		return kubernetesAdapter{spec: spec.Kubernetes, runner: runner}, nil
	case extract.AdapterProcess:
		return processAdapter{environ: environ}, nil
	case extract.AdapterExec:
		return execAdapter{commands: spec.Exec, runner: runner}, nil
	}
	return nil, fmt.Errorf("unknown adapter %q", spec.Adapter)
}

// --- Docker / Compose -------------------------------------------------

type composeAdapter struct {
	spec   extract.ComposeSpec
	dir    string
	runner Runner
}

func (a composeAdapter) Name() string { return extract.AdapterCompose }

func (a composeAdapter) base() []string {
	argv := []string{"docker", "compose"}
	if a.spec.Project != "" {
		argv = append(argv, "-p", a.spec.Project)
	}
	for _, file := range a.spec.Files {
		// An absolute path is used as written. Joining it onto the manifest
		// directory produced `.../demo/C:\Users\...` on Windows and
		// `/repo/etc/...` for `/etc/...` elsewhere. (Phase 30 phase audit.)
		path := filepath.FromSlash(file)
		if !filepath.IsAbs(path) {
			path = filepath.Join(a.dir, path)
		}
		argv = append(argv, "-f", path)
	}
	return argv
}

// dockerInspect is the subset of `docker inspect` this reads.
type dockerInspect struct {
	ID     string `json:"Id"`
	Name   string `json:"Name"`
	Image  string `json:"Image"`
	Config struct {
		Env   []string `json:"Env"`
		Image string   `json:"Image"`
	} `json:"Config"`
}

type dockerImageInspect struct {
	ID          string   `json:"Id"`
	RepoDigests []string `json:"RepoDigests"`
}

// container finds a service's first running container, in name order so
// the choice is stable across runs.
func (a composeAdapter) container(ctx context.Context, service string) (dockerInspect, int, error) {
	out, err := a.runner.Run(ctx, append(a.base(), "ps", "-q", service))
	if err != nil {
		return dockerInspect{}, 0, err
	}
	ids := strings.Fields(string(out))
	if len(ids) == 0 {
		return dockerInspect{}, 0, errNotRunning
	}
	sort.Strings(ids)
	inspected, err := a.runner.Run(ctx, append([]string{"docker", "inspect"}, ids...))
	if err != nil {
		return dockerInspect{}, 0, err
	}
	var containers []dockerInspect
	if err := json.Unmarshal(inspected, &containers); err != nil || len(containers) == 0 {
		return dockerInspect{}, 0, errUnreadable
	}
	sort.Slice(containers, func(i, j int) bool { return containers[i].Name < containers[j].Name })
	return containers[0], len(containers), nil
}

func (a composeAdapter) Workload(
	ctx context.Context, component string, settings extract.EnvironmentComponent,
) (Workload, error) {
	service := settings.WorkloadFor(component)
	container, replicas, err := a.container(ctx, service)
	if err != nil {
		return Workload{}, err
	}
	return Workload{
		Env:      parseEnvList(container.Config.Env),
		Complete: true,
		Artefact: "compose:" + service,
		Replicas: replicas,
	}, nil
}

func (a composeAdapter) Image(
	ctx context.Context, component string, settings extract.EnvironmentComponent,
) (Image, error) {
	container, _, err := a.container(ctx, settings.WorkloadFor(component))
	if err != nil {
		return Image{}, err
	}
	image := Image{Reference: container.Config.Image, ID: container.Image}
	out, err := a.runner.Run(ctx, []string{"docker", "image", "inspect", container.Image})
	if err != nil {
		// The reference and the id are still true; only the registry
		// digest is unknown.
		return image, nil
	}
	var images []dockerImageInspect
	if json.Unmarshal(out, &images) == nil && len(images) > 0 {
		image.Digest = firstDigest(images[0].RepoDigests)
	}
	return image, nil
}

// firstDigest takes "repo@sha256:..." entries and returns the digest of
// the first in sorted order, so the choice is stable.
func firstDigest(repoDigests []string) string {
	sorted := append([]string(nil), repoDigests...)
	sort.Strings(sorted)
	for _, entry := range sorted {
		if _, digest, found := strings.Cut(entry, "@"); found && strings.HasPrefix(digest, "sha256:") {
			return digest
		}
	}
	return ""
}

// --- Kubernetes -------------------------------------------------------

type kubernetesAdapter struct {
	spec   extract.KubernetesSpec
	runner Runner
}

func (a kubernetesAdapter) Name() string { return extract.AdapterKubernetes }

func (a kubernetesAdapter) base() []string {
	argv := []string{"kubectl"}
	if a.spec.Context != "" {
		argv = append(argv, "--context", a.spec.Context)
	}
	if a.spec.Namespace != "" {
		argv = append(argv, "-n", a.spec.Namespace)
	}
	return argv
}

type kubeEnvVar struct {
	Name      string          `json:"name"`
	Value     *string         `json:"value"`
	ValueFrom json.RawMessage `json:"valueFrom"`
}

type kubeEnvFrom struct {
	Prefix       string `json:"prefix"`
	ConfigMapRef *struct {
		Name string `json:"name"`
	} `json:"configMapRef"`
	SecretRef *struct {
		Name string `json:"name"`
	} `json:"secretRef"`
}

type kubeContainer struct {
	Name    string        `json:"name"`
	Image   string        `json:"image"`
	Env     []kubeEnvVar  `json:"env"`
	EnvFrom []kubeEnvFrom `json:"envFrom"`
}

type kubeDeployment struct {
	Spec struct {
		Selector struct {
			MatchLabels map[string]string `json:"matchLabels"`
		} `json:"selector"`
		Template struct {
			Spec struct {
				Containers []kubeContainer `json:"containers"`
			} `json:"spec"`
		} `json:"template"`
	} `json:"spec"`
}

func (a kubernetesAdapter) deployment(
	ctx context.Context, component string, settings extract.EnvironmentComponent,
) (kubeDeployment, kubeContainer, error) {
	name := settings.WorkloadFor(component)
	out, err := a.runner.Run(ctx, append(a.base(), "get", "deployment", name, "-o", "json"))
	if err != nil {
		return kubeDeployment{}, kubeContainer{}, err
	}
	var deployment kubeDeployment
	if err := json.Unmarshal(out, &deployment); err != nil {
		return kubeDeployment{}, kubeContainer{}, errUnreadable
	}
	containers := deployment.Spec.Template.Spec.Containers
	if len(containers) == 0 {
		return kubeDeployment{}, kubeContainer{}, errUnreadable
	}
	if settings.Container == "" {
		return deployment, containers[0], nil
	}
	for _, container := range containers {
		if container.Name == settings.Container {
			return deployment, container, nil
		}
	}
	return kubeDeployment{}, kubeContainer{}, errNoSuchContainer
}

func (a kubernetesAdapter) Workload(
	ctx context.Context, component string, settings extract.EnvironmentComponent,
) (Workload, error) {
	_, container, err := a.deployment(ctx, component, settings)
	if err != nil {
		return Workload{}, err
	}
	workload := Workload{
		Env:      map[string]EnvValue{},
		Complete: true,
		Artefact: "kubernetes:deployment/" + settings.WorkloadFor(component),
		Replicas: 1,
	}

	// envFrom first, then env: Kubernetes gives `env` precedence over
	// `envFrom` when a key appears in both, and applying them in that
	// order reproduces it.
	for _, source := range container.EnvFrom {
		switch {
		case source.ConfigMapRef != nil:
			out, err := a.runner.Run(ctx, append(a.base(),
				"get", "configmap", source.ConfigMapRef.Name, "-o", "json"))
			var configMap struct {
				Data map[string]string `json:"data"`
			}
			if err != nil || json.Unmarshal(out, &configMap) != nil {
				workload.Complete = false
				workload.Incomplete = append(workload.Incomplete,
					"the keys of a ConfigMap it loads with envFrom could not be read")
				continue
			}
			for key, value := range configMap.Data {
				workload.Env[source.Prefix+key] = EnvValue{Value: value, Known: true}
			}
		case source.SecretRef != nil:
			// Keys only, never data. The template prints each key name on
			// its own line, so the Secret's values reach kubectl (which
			// has to fetch the object) but never this process. Every key
			// is therefore known to exist and has an unknown shape.
			out, err := a.runner.Run(ctx, append(a.base(),
				"get", "secret", source.SecretRef.Name,
				"-o", `go-template={{range $key, $_ := .data}}{{$key}}{{"\n"}}{{end}}`))
			if err != nil {
				workload.Complete = false
				workload.Incomplete = append(workload.Incomplete,
					"the keys of a Secret it loads with envFrom could not be listed")
				continue
			}
			for _, key := range strings.Fields(string(out)) {
				workload.Env[source.Prefix+key] = EnvValue{Known: false}
			}
		}
	}
	for _, variable := range container.Env {
		if variable.Value != nil {
			workload.Env[variable.Name] = EnvValue{Value: *variable.Value, Known: true}
			continue
		}
		// valueFrom: a secretKeyRef, configMapKeyRef or fieldRef. The key
		// is set; its value is decided at runtime, out of this spec.
		workload.Env[variable.Name] = EnvValue{Known: len(variable.ValueFrom) == 0}
	}
	return workload, nil
}

func (a kubernetesAdapter) Image(
	ctx context.Context, component string, settings extract.EnvironmentComponent,
) (Image, error) {
	deployment, container, err := a.deployment(ctx, component, settings)
	if err != nil {
		return Image{}, err
	}
	image := Image{Reference: container.Image}

	labels := deployment.Spec.Selector.MatchLabels
	if len(labels) == 0 {
		return image, nil
	}
	selector := make([]string, 0, len(labels))
	for key, value := range labels {
		selector = append(selector, key+"="+value)
	}
	sort.Strings(selector)
	out, err := a.runner.Run(ctx, append(a.base(),
		"get", "pods", "-l", strings.Join(selector, ","), "-o", "json"))
	if err != nil {
		return image, nil
	}
	var pods struct {
		Items []struct {
			Metadata struct {
				Name string `json:"name"`
			} `json:"metadata"`
			Status struct {
				ContainerStatuses []struct {
					Name    string `json:"name"`
					ImageID string `json:"imageID"`
				} `json:"containerStatuses"`
			} `json:"status"`
		} `json:"items"`
	}
	if json.Unmarshal(out, &pods) != nil {
		return image, nil
	}
	sort.Slice(pods.Items, func(i, j int) bool {
		return pods.Items[i].Metadata.Name < pods.Items[j].Metadata.Name
	})
	for _, pod := range pods.Items {
		for _, status := range pod.Status.ContainerStatuses {
			if status.Name != container.Name {
				continue
			}
			// "docker-pullable://repo@sha256:..." or "repo@sha256:...".
			if _, digest, found := strings.Cut(status.ImageID, "@"); found {
				image.Digest = digest
				return image, nil
			}
		}
	}
	return image, nil
}

// --- plain process ----------------------------------------------------

// processAdapter reads the environment `culprit` itself is running in.
//
// For "run the capture inside the workload": a CI job with production's
// variables loaded, a `docker run --env-file`, a sidecar. It is the
// simplest adapter and the one with the least ambiguity, because there
// is exactly one environment and it is this one.
type processAdapter struct {
	environ func() []string
}

func (a processAdapter) Name() string { return extract.AdapterProcess }

func (a processAdapter) Workload(
	_ context.Context, _ string, _ extract.EnvironmentComponent,
) (Workload, error) {
	return Workload{
		Env:      parseEnvList(a.environ()),
		Complete: true,
		Artefact: "process",
		Replicas: 1,
	}, nil
}

func (a processAdapter) Image(context.Context, string, extract.EnvironmentComponent) (Image, error) {
	return Image{}, ErrNoImage
}

// --- generic exec -----------------------------------------------------

// execAdapter reads a component's environment from a command the user
// declared — `env -0`, `ssh host env -0`, `heroku config --json`, whatever
// reaches the environment in question.
//
// # NUL-delimited or JSON, never lines
//
// The first version read KEY=VALUE *lines*, the format `printenv` prints,
// and the invariant audit showed why that is unsafe rather than merely
// fragile: a multi-line value — a PEM private key, a whole `.env` file
// held in one variable — prints across several lines, and any of those
// lines containing `=` became a "key". The last line of a base64 key
// block (`QUJDREVGRw==`) is a perfectly valid-looking variable name, so
// no rule about which characters a name may hold can tell it apart. A
// fragment of a secret would have become a subject, and subjects are
// never masked: it would have gone into the sealed envelope, every report
// format, and `configured_facts.subject`.
//
// The only fix is a format where a value cannot pose as a name. So the
// output must be either NUL-delimited KEY=VALUE pairs — `env -0`,
// `printenv -0`; NUL cannot appear inside an environment variable — or a
// JSON object of string values. Anything else is refused with a reason,
// and nothing from it is kept.
type execAdapter struct {
	commands map[string][]string
	runner   Runner
}

func (a execAdapter) Name() string { return extract.AdapterExec }

// errNotNULOrJSON is the refusal for line-delimited output. Fixed text:
// the output itself is never quoted.
var errNotNULOrJSON = fmt.Errorf(
	"the command's output was neither NUL-delimited KEY=VALUE pairs (env -0) nor a " +
		"JSON object of strings; line-delimited output is refused, because a multi-line " +
		"value cannot be told apart from a variable name")

func (a execAdapter) Workload(
	ctx context.Context, _ string, settings extract.EnvironmentComponent,
) (Workload, error) {
	argv := a.commands[settings.EnvCommand]
	out, err := a.runner.Run(ctx, argv)
	if err != nil {
		return Workload{}, err
	}
	workload := Workload{Complete: true, Artefact: "exec:" + settings.EnvCommand, Replicas: 1}
	trimmed := strings.TrimSpace(string(out))
	switch {
	case strings.HasPrefix(trimmed, "{"):
		var object map[string]string
		if json.Unmarshal([]byte(trimmed), &object) != nil {
			return Workload{}, errNotNULOrJSON
		}
		workload.Env = map[string]EnvValue{}
		for key, value := range object {
			if envName.MatchString(key) {
				workload.Env[key] = EnvValue{Value: value, Known: true}
			} else {
				workload.Complete = false
			}
		}
	case strings.Contains(string(out), "\x00"):
		var rejected int
		workload.Env, rejected = parseEnvEntries(strings.Split(string(out), "\x00"))
		workload.Complete = rejected == 0
	default:
		return Workload{}, errNotNULOrJSON
	}
	if !workload.Complete {
		workload.Incomplete = append(workload.Incomplete,
			"some entries of the command's output were not valid KEY=VALUE assignments")
	}
	return workload, nil
}

func (a execAdapter) Image(context.Context, string, extract.EnvironmentComponent) (Image, error) {
	return Image{}, ErrNoImage
}

// --- shared -----------------------------------------------------------

var (
	errNotRunning      = fmt.Errorf("no running container was found for it")
	errUnreadable      = fmt.Errorf("the adapter's output was not in the expected shape")
	errNoSuchContainer = fmt.Errorf("the named container is not in the Deployment")
)

// envName is what an environment variable name may be. Applied to every
// adapter's keys as defence in depth — for the exec adapter it is not
// enough on its own (see execAdapter), which is why that adapter refuses
// line-delimited output outright.
var envName = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)

// parseEnvList reads "KEY=VALUE" entries whose delimiting is unambiguous —
// `docker inspect`'s JSON array, `os.Environ()`, NUL-separated output —
// and drops anything whose key is not a variable name.
func parseEnvList(entries []string) map[string]EnvValue {
	env, _ := parseEnvEntries(entries)
	return env
}

// parseEnvEntries is parseEnvList, also counting the non-empty entries it
// refused. Windows' `=C:=C:\...` drive entries are among those, correctly.
func parseEnvEntries(entries []string) (map[string]EnvValue, int) {
	env := map[string]EnvValue{}
	rejected := 0
	for _, entry := range entries {
		if strings.TrimSpace(entry) == "" {
			continue
		}
		key, value, found := strings.Cut(entry, "=")
		if !found || !envName.MatchString(key) {
			rejected++
			continue
		}
		env[key] = EnvValue{Value: value, Known: true}
	}
	return env, rejected
}
