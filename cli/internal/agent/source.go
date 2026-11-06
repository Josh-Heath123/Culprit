package agent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// Source is where tasks come from and where their results go. Part 1's
// is a local directory (DirSource); part 2's is the transport to the
// control plane. The agent's authority does not depend on which.
type Source interface {
	// Next returns the next task, or nil when there is none waiting. A
	// task that arrived but could not be read is returned with
	// Unreadable set, so it is answered and recorded, never silently
	// skipped or retried forever.
	Next(ctx context.Context) (*Incoming, error)
	// Complete hands back a task's result. The agent calls it only after
	// every audit entry for the task is written.
	Complete(ctx context.Context, incoming *Incoming, result Result) error
}

// Incoming is a task as it arrived.
type Incoming struct {
	Task Task
	// Unreadable says why the task could not be decoded, if it could not.
	Unreadable string
	// Handle is the source's own reference: a file name for DirSource, the
	// task id for the transport.
	Handle string
}

// DirSource reads tasks from <Dir>/inbox/*.json, oldest name first,
// writes each result to <Dir>/outbox/<task id>.json and moves the task
// file to <Dir>/done/. Tests, and an operator running tasks by hand,
// write the inbox.
type DirSource struct {
	Dir string
}

func (s DirSource) dir(name string) string { return filepath.Join(s.Dir, name) }

// Prepare creates the three directories.
func (s DirSource) Prepare() error {
	for _, name := range []string{"inbox", "outbox", "done"} {
		if err := os.MkdirAll(s.dir(name), 0o700); err != nil {
			return fmt.Errorf("the task directory %s cannot be created: %s", s.dir(name), reasonOf(err))
		}
	}
	return nil
}

func (s DirSource) Next(context.Context) (*Incoming, error) {
	entries, err := os.ReadDir(s.dir("inbox"))
	if err != nil {
		return nil, fmt.Errorf("the inbox %s cannot be read: %s", s.dir("inbox"), reasonOf(err))
	}
	var names []string
	for _, entry := range entries {
		if entry.Type().IsRegular() && strings.HasSuffix(entry.Name(), ".json") {
			names = append(names, entry.Name())
		}
	}
	if len(names) == 0 {
		return nil, nil
	}
	sort.Strings(names)
	name := names[0]
	incoming := &Incoming{Handle: name}
	data, err := os.ReadFile(filepath.Join(s.dir("inbox"), name))
	if err != nil {
		incoming.Unreadable = "the task file cannot be read: " + reasonOf(err)
		incoming.Task.ID = strings.TrimSuffix(name, ".json")
		return incoming, nil
	}
	stem := strings.TrimSuffix(name, ".json")
	decoder := json.NewDecoder(strings.NewReader(string(data)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&incoming.Task); err != nil {
		incoming.Task = Task{ID: stem}
		incoming.Unreadable = "the task file is not a task (unknown field, or not JSON)"
		return incoming, nil
	}
	// The id is the file's name, so one result answers one task file and
	// a task's id can never name a path or another task's result.
	if incoming.Task.ID != stem {
		incoming.Unreadable = fmt.Sprintf("the task's id %q is not its file name %q", incoming.Task.ID, stem)
		incoming.Task.ID = stem
		return incoming, nil
	}
	// Ids are not reused: a task whose result already exists is answered
	// with a refusal under a new name, and the first result stands.
	if _, err := os.Stat(filepath.Join(s.dir("outbox"), stem+".json")); err == nil {
		incoming.Unreadable = fmt.Sprintf("task %s already has a result; task ids are not reused", stem)
	}
	return incoming, nil
}

func (s DirSource) Complete(_ context.Context, incoming *Incoming, result Result) error {
	id := result.TaskID
	if !taskID.MatchString(id) {
		// A name the task file gave is never trusted as a path.
		id = strings.TrimSuffix(incoming.Handle, ".json")
		if !taskID.MatchString(id) {
			id = "unnamed-task"
		}
	}
	body, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		return err
	}
	final := freeName(s.dir("outbox"), id, ".json")
	temporary := final + ".partial"
	if err := os.WriteFile(temporary, append(body, '\n'), 0o600); err != nil {
		return fmt.Errorf("the result for %s cannot be written: %s", id, reasonOf(err))
	}
	if err := os.Rename(temporary, final); err != nil {
		return fmt.Errorf("the result for %s cannot be written: %s", id, reasonOf(err))
	}
	done := freeName(s.dir("done"), strings.TrimSuffix(incoming.Handle, ".json"), ".json")
	if err := os.Rename(filepath.Join(s.dir("inbox"), incoming.Handle), done); err != nil &&
		!errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("the task file %s cannot be moved out of the inbox: %s", incoming.Handle, reasonOf(err))
	}
	return nil
}

// freeName is dir/base+ext, or dir/base.N+ext for the first N not taken:
// nothing the agent wrote is ever overwritten.
func freeName(dir, base, ext string) string {
	candidate := filepath.Join(dir, base+ext)
	for n := 1; ; n++ {
		if _, err := os.Stat(candidate); errors.Is(err, os.ErrNotExist) {
			return candidate
		}
		candidate = filepath.Join(dir, fmt.Sprintf("%s.%d%s", base, n, ext))
	}
}
