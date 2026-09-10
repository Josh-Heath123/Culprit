package capture

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os/exec"
	"time"
)

// Running the commands an adapter is built on — `docker`, `kubectl`, and
// the user's own allowlisted commands.
//
// # Why commands, and not the Docker SDK and client-go
//
// Field 11 names "client-go for Kubernetes, Docker SDK. Both optional
// build tags so the binary stays small when unused." This package runs
// the `docker` and `kubectl` CLIs instead, and the reasoning is recorded
// as a plan correction rather than left implicit:
//
//   - **The released binary could capture nothing.** Behind build tags,
//     the binary a stranger downloads either carries both SDKs (and is no
//     longer small) or carries neither (and cannot read a Compose project
//     or a cluster). The CLIs are already on every machine that can reach
//     those environments.
//   - **Authentication is the user's, unchanged.** `kubectl` already knows
//     the user's contexts, exec credential plugins, OIDC, and cloud IAM
//     glue; `docker` already knows `DOCKER_HOST` and contexts. Reproducing
//     that inside this binary is a large surface that exists only to be
//     slightly wrong.
//   - **No HTTP client enters the binary.** Both SDKs are HTTP clients.
//     `cmd/culprit`'s own test asserts `net/http` is not linked, because
//     the binary has nothing it should be talking to over HTTP — and that
//     stays true.
//
// The cost is real and is in docs/LIMITS.md: capture needs `docker` or
// `kubectl` on PATH, and the output of `docker inspect` / `kubectl get -o
// json` is a contract this package now depends on.
//
// # What leaves this file
//
// Standing invariant 11: error text is output. A failing command's stderr
// is **never** read into a reason, a skip, or a log line — `docker
// inspect` of a misconfigured container can print its environment, and
// `kubectl` echoes the object it failed on. A failure is reported as one
// of four closed kinds, naming only argv[0], which comes from this
// binary or from `culprit.yaml` and never from the environment.

// Runner runs one command. An interface so the adapters can be tested
// against recorded output with no Docker and no cluster.
type Runner interface {
	Run(ctx context.Context, argv []string) ([]byte, error)
}

// RunErrorKind is why a command did not produce output. A closed set.
type RunErrorKind string

const (
	RunNotFound RunErrorKind = "is not installed or not on PATH"
	RunFailed   RunErrorKind = "exited with an error"
	RunTimedOut RunErrorKind = "timed out"
	RunOverflow RunErrorKind = "produced more output than culprit reads"
)

// RunError is a command failure reduced to what is safe to print.
type RunError struct {
	Command string
	Kind    RunErrorKind
}

func (e *RunError) Error() string { return fmt.Sprintf("%s %s", e.Command, e.Kind) }

// maxCommandOutput bounds what is read from one command. `docker inspect`
// of one container is a few kilobytes and `kubectl get deployment -o
// json` a few tens; a megabyte-scale answer is something going wrong.
var maxCommandOutput = 8 << 20

// ExecRunner runs real commands. No shell, ever: argv is executed exactly
// as written, so nothing in `culprit.yaml` is interpreted.
type ExecRunner struct {
	Timeout time.Duration
}

// Run executes argv and returns stdout.
func (r ExecRunner) Run(parent context.Context, argv []string) ([]byte, error) {
	if len(argv) == 0 {
		return nil, &RunError{Command: "(empty)", Kind: RunFailed}
	}
	timeout := r.Timeout
	if timeout == 0 {
		timeout = 30 * time.Second
	}
	ctx, cancel := context.WithTimeout(parent, timeout)
	defer cancel()

	command := exec.CommandContext(ctx, argv[0], argv[1:]...)
	stdout := &boundedWriter{limit: maxCommandOutput}
	command.Stdout = stdout
	// Stderr is discarded, deliberately and entirely. See the file comment.
	command.Stderr = nil

	err := command.Run()
	switch {
	case ctx.Err() == context.DeadlineExceeded:
		return nil, &RunError{Command: argv[0], Kind: RunTimedOut}
	case err != nil:
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			return nil, &RunError{Command: argv[0], Kind: RunFailed}
		}
		return nil, &RunError{Command: argv[0], Kind: RunNotFound}
	case stdout.overflowed:
		return nil, &RunError{Command: argv[0], Kind: RunOverflow}
	}
	return stdout.buffer.Bytes(), nil
}

type boundedWriter struct {
	buffer     bytes.Buffer
	limit      int
	overflowed bool
}

func (w *boundedWriter) Write(data []byte) (int, error) {
	remaining := w.limit - w.buffer.Len()
	if len(data) > remaining {
		w.overflowed = true
		if remaining > 0 {
			w.buffer.Write(data[:remaining])
		}
		return len(data), nil
	}
	return w.buffer.Write(data)
}
