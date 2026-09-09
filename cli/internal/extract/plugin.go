package extract

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os/exec"
	"strings"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Running an extractor plugin (D3, field 7).
//
// One JSON object in on stdin, one JSON object out on stdout. That is
// the entire interface, and it is this dull deliberately: introspecting
// a FastAPI app means importing it, which means running inside that
// project's own virtualenv, which no library call from a Go binary can
// do. Accepting that turns "we must write a static analyser per
// language" into "each ecosystem contributes a small extractor in its
// own language" — which is also the extension point third parties use.
//
// **The failure policy is the important part.** A non-zero exit,
// unparseable stdout, a missing binary or a timeout all degrade to
// `skipped` entries with a reason, and the run continues. It is never an
// error. Acceptance criterion 4 is exactly this: with no extractor
// installed, `culprit intent` still emits artefact-derived facts and
// reports precisely what it skipped and why.
//
// The opposite policy — failing the run — would make installing the
// Python extractor a precondition for getting any value at all, which is
// the adoption cliff D2 and D3 were both written to avoid.

// DefaultPluginTimeout bounds one extractor run.
//
// Generous, because an extractor legitimately imports a whole
// application: a cold Django import with a hundred models is not fast.
// Bounded all the same, because an extractor that hangs — waiting on a
// database connection its settings module opens at import time, which
// happens — must not hang CI. The timeout produces a Skip naming the
// timeout, so the report says what happened rather than showing a gap.
const DefaultPluginTimeout = 90 * time.Second

// maxPluginOutput caps how much stdout is read from one extractor.
//
// A defence against a runaway or malicious extractor filling memory, and
// against the more mundane case of an extractor that prints a whole
// dependency tree. Exceeding it is a Skip, not a truncated parse: half a
// JSON document parsed as if it were whole is how a partial fact set
// silently becomes a complete-looking one.
//
// A var rather than a const so the overflow path can be exercised
// end-to-end at a sane size. An untested limit is a limit nobody knows
// works, and this one guards a memory bound.
var maxPluginOutput = 64 << 20 // 64 MiB

// PluginResult is what one extractor run produced.
type PluginResult struct {
	// Name is the manifest's name for the extractor, used in messages
	// before the extractor has identified itself.
	Name    string
	Facts   []model.Fact
	Skipped []model.Skip
}

// RunPlugin executes one extractor and interprets its answer.
func RunPlugin(
	parent context.Context, spec ExtractorSpec, request model.ExtractorRequest, timeout time.Duration,
) PluginResult {
	wants := make([]string, 0, len(request.Want))
	for _, want := range request.Want {
		wants = append(wants, string(want))
	}
	label := spec.Name
	if label == "" {
		label = strings.Join(spec.Command, " ")
	}

	fail := func(reason string) PluginResult {
		return PluginResult{
			Name:    spec.Name,
			Skipped: model.SkipsFromFailure(label, wants, reason),
		}
	}

	payload, err := json.Marshal(request)
	if err != nil {
		return fail("could not encode the extractor request: " + err.Error())
	}

	ctx, cancel := context.WithTimeout(parent, timeout)
	defer cancel()

	// No shell, ever. spec.Command is argv — see ExtractorSpec.Command.
	command := exec.CommandContext(ctx, spec.Command[0], spec.Command[1:]...)
	command.Dir = request.Root
	command.Stdin = bytes.NewReader(payload)
	// A *bounded* writer, not a plain bytes.Buffer. Reading everything and
	// then checking its size is not a defence against a runaway
	// extractor: by the time the check runs the memory is already
	// allocated. This refuses the write instead, so the cap is a cap.
	stdout := &boundedBuffer{limit: maxPluginOutput}
	var stderr bytes.Buffer
	command.Stdout = stdout
	command.Stderr = &stderr

	runErr := command.Run()

	if ctx.Err() == context.DeadlineExceeded {
		return fail(fmt.Sprintf("extractor %q timed out after %s", label, timeout))
	}
	if runErr != nil {
		var exitErr *exec.ExitError
		if errors.As(runErr, &exitErr) {
			return fail(fmt.Sprintf("extractor %q exited %d: %s",
				label, exitErr.ExitCode(), firstLine(stderr.String())))
		}
		// Almost always "executable file not found in $PATH" — the
		// common, expected case, and the one criterion 4 is about.
		return fail(fmt.Sprintf("extractor %q could not be run: %s", label, runErr))
	}
	if stdout.overflowed {
		return fail(fmt.Sprintf("extractor %q produced more than %d bytes of output",
			label, maxPluginOutput))
	}

	var response model.ExtractorResponse
	decoder := json.NewDecoder(bytes.NewReader(stdout.Bytes()))
	if err := decoder.Decode(&response); err != nil {
		return fail(fmt.Sprintf("extractor %q produced output that is not one JSON object: %s",
			label, err))
	}
	if response.Protocol != model.ExtractorProtocolVersion {
		return fail(fmt.Sprintf(
			"extractor %q speaks protocol %d; this build speaks %d",
			label, response.Protocol, model.ExtractorProtocolVersion))
	}
	if response.Extractor == "" {
		return fail(fmt.Sprintf("extractor %q did not identify itself (no `extractor` field)", label))
	}

	// Facts are validated here rather than trusted. An extractor is a
	// third-party program running in someone else's virtualenv; a fact
	// that carries an ungranted config literal, or an environment on an
	// INTENT fact, is dropped and reported, not stored. This is the one
	// place the config-value guarantee meets untrusted input.
	valid := make([]model.Fact, 0, len(response.Facts))
	rejected := 0
	for _, fact := range response.Facts {
		if err := fact.Validate(); err != nil {
			rejected++
			continue
		}
		valid = append(valid, fact)
	}

	skipped := response.Skipped
	if skipped == nil {
		// Same reason as the orchestrator's: nil marshals to `null`, and
		// every consumer of this list expects an array.
		skipped = []model.Skip{}
	}
	for index := range skipped {
		if skipped[index].Extractor == "" {
			skipped[index].Extractor = response.Extractor
		}
	}
	if rejected > 0 {
		skipped = append(skipped, model.Skip{
			Want:      "*",
			Reason:    fmt.Sprintf("%d fact(s) from %q were rejected as invalid and not stored", rejected, response.Extractor),
			Extractor: response.Extractor,
		})
	}

	return PluginResult{Name: spec.Name, Facts: valid, Skipped: skipped}
}

func firstLine(text string) string {
	text = strings.TrimSpace(text)
	if index := strings.IndexAny(text, "\r\n"); index >= 0 {
		text = text[:index]
	}
	const limit = 200
	if len(text) > limit {
		return text[:limit] + "…"
	}
	if text == "" {
		return "(no stderr output)"
	}
	return text
}

// boundedBuffer accumulates up to `limit` bytes and then stops, recording
// that it did.
//
// It never returns an error to the child process. Failing the write would
// send it SIGPIPE mid-run and turn a well-defined "produced too much
// output" into whatever that extractor happens to do when its stdout
// breaks — usually a stack trace, sometimes a hang. Discarding the excess
// and reporting the overflow keeps the failure legible.
//
// The truncated content is deliberately never parsed: half a JSON
// document read as if it were whole is how a partial fact set silently
// becomes a complete-looking one.
type boundedBuffer struct {
	buffer     bytes.Buffer
	limit      int
	overflowed bool
}

func (b *boundedBuffer) Write(data []byte) (int, error) {
	remaining := b.limit - b.buffer.Len()
	if remaining <= 0 {
		b.overflowed = true
		return len(data), nil
	}
	if len(data) > remaining {
		b.overflowed = true
		b.buffer.Write(data[:remaining])
		return len(data), nil
	}
	return b.buffer.Write(data)
}

func (b *boundedBuffer) Bytes() []byte { return b.buffer.Bytes() }
