package agent

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"sync"
	"time"
)

// The audit log: append-only, hash-chained, one JSON entry per line.
//
// One entry per task and one per probe the task ran, each written and
// synced before the task's result is handed back. Each entry carries the
// hash of the one before it and its own hash over its content, so an
// entry edited, removed or reordered breaks the chain at that line and
// VerifyAudit names it. What a chain on one machine cannot show is the
// newest entries removed together from the end; part 2 ships every
// entry to the control plane's append-only table, which is what makes
// that visible (docs/LIMITS.md).

// Entry kinds.
const (
	EntryTask  = "task"
	EntryProbe = "probe"
)

// genesis is the previous-hash of the first entry.
const genesis = "0000000000000000000000000000000000000000000000000000000000000000"

// Entry is one line of the audit log.
type Entry struct {
	Seq         int64     `json:"seq"`
	Time        time.Time `json:"time"`
	AgentID     string    `json:"agent_id"`
	TaskID      string    `json:"task_id"`
	Kind        string    `json:"kind"`
	Environment string    `json:"environment,omitempty"`
	// For a probe entry: what ran, on what, under which grants, and the
	// verdict. Grants are what the run exercised (the reading's
	// grants_used), so a refused probe lists none.
	ProbeID string   `json:"probe_id,omitempty"`
	Target  string   `json:"target,omitempty"`
	Grants  []string `json:"grants"`
	Verdict string   `json:"verdict,omitempty"`
	// For a task entry: how it ended, and what it held.
	Outcome string `json:"outcome,omitempty"`
	Reason  string `json:"reason,omitempty"`
	Prev    string `json:"prev"`
	Hash    string `json:"hash"`
}

func (e Entry) digest() string {
	e.Hash = ""
	body, _ := json.Marshal(e)
	sum := sha256.Sum256(append([]byte(e.Prev+"\n"), body...))
	return hex.EncodeToString(sum[:])
}

// AuditLog appends to one file. Safe for concurrent use.
type AuditLog struct {
	mutex sync.Mutex
	path  string
	seq   int64
	last  string
}

// OpenAudit opens (or creates) the log at path. An existing log is
// verified first: an agent does not add to a chain that is already
// broken, because every entry after the break would vouch for it.
func OpenAudit(path string) (*AuditLog, error) {
	log := &AuditLog{path: path, last: genesis}
	file, err := os.Open(path)
	switch {
	case errors.Is(err, os.ErrNotExist):
		return log, nil
	case err != nil:
		return nil, fmt.Errorf("the audit log %s cannot be read: %s", path, reasonOf(err))
	}
	defer file.Close()
	seq, last, err := verifyChain(file)
	if err != nil {
		return nil, fmt.Errorf("the audit log %s fails its chain check, so the agent will not add to it: %w", path, err)
	}
	log.seq, log.last = seq, last
	return log, nil
}

// Append completes an entry's sequence number and chain fields, writes
// it as one line and syncs the file before returning.
func (l *AuditLog) Append(entry Entry) (Entry, error) {
	l.mutex.Lock()
	defer l.mutex.Unlock()
	if entry.Grants == nil {
		entry.Grants = []string{}
	}
	entry.Seq = l.seq + 1
	entry.Prev = l.last
	entry.Hash = entry.digest()
	line, err := json.Marshal(entry)
	if err != nil {
		return Entry{}, err
	}
	file, err := os.OpenFile(l.path, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o600)
	if err != nil {
		return Entry{}, fmt.Errorf("the audit log %s cannot be opened for appending: %s", l.path, reasonOf(err))
	}
	if _, err := file.Write(append(line, '\n')); err != nil {
		file.Close()
		return Entry{}, fmt.Errorf("the audit log %s could not be written", l.path)
	}
	if err := file.Sync(); err != nil {
		file.Close()
		return Entry{}, fmt.Errorf("the audit log %s could not be synced", l.path)
	}
	if err := file.Close(); err != nil {
		return Entry{}, err
	}
	l.seq, l.last = entry.Seq, entry.Hash
	return entry, nil
}

// ErrAuditUnreadable marks a log that could not be read at all, as
// distinct from one that was read and found broken.
var ErrAuditUnreadable = errors.New("the audit log cannot be read")

// VerifyAudit checks a whole log and returns how many entries it holds.
// An error names the first line that breaks the chain; a log that cannot
// be opened wraps ErrAuditUnreadable.
func VerifyAudit(path string) (int64, error) {
	file, err := os.Open(path)
	if err != nil {
		return 0, fmt.Errorf("%w: %s: %s", ErrAuditUnreadable, path, reasonOf(err))
	}
	defer file.Close()
	seq, _, err := verifyChain(file)
	return seq, err
}

// ReadAudit returns every entry, after verifying the chain.
func ReadAudit(path string) ([]Entry, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("%s cannot be read: %s", path, reasonOf(err))
	}
	if _, _, err := verifyChain(bytes.NewReader(data)); err != nil {
		return nil, err
	}
	var entries []Entry
	for _, line := range strings.Split(strings.TrimRight(string(data), "\n"), "\n") {
		if line == "" {
			continue
		}
		var entry Entry
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			return nil, err
		}
		entries = append(entries, entry)
	}
	return entries, nil
}

func verifyChain(reader io.Reader) (int64, string, error) {
	scanner := bufio.NewScanner(reader)
	scanner.Buffer(make([]byte, 0, 64*1024), 16*1024*1024)
	var seq int64
	last := genesis
	line := 0
	for scanner.Scan() {
		line++
		text := scanner.Bytes()
		if len(bytes.TrimSpace(text)) == 0 {
			return 0, "", fmt.Errorf("line %d is blank: entries are never removed, so nothing leaves a gap", line)
		}
		var entry Entry
		if err := json.Unmarshal(text, &entry); err != nil {
			return 0, "", fmt.Errorf("line %d is not an audit entry", line)
		}
		switch {
		case entry.Seq != seq+1:
			return 0, "", fmt.Errorf("line %d is entry %d where entry %d was due: an entry before it was removed or reordered",
				line, entry.Seq, seq+1)
		case entry.Prev != last:
			return 0, "", fmt.Errorf("line %d does not follow the entry before it: an entry was removed, reordered or edited", line)
		case entry.digest() != entry.Hash:
			return 0, "", fmt.Errorf("line %d has been edited: its content no longer matches its hash", line)
		}
		seq, last = entry.Seq, entry.Hash
	}
	if err := scanner.Err(); err != nil {
		return 0, "", fmt.Errorf("the log could not be read to the end")
	}
	return seq, last, nil
}

// LinesAfter returns every entry after seq exactly as the log holds it,
// one JSON line each, and the log's last seq — after verifying the whole
// chain, so nothing broken is ever shipped as though it were the record.
func (l *AuditLog) LinesAfter(seq int64) ([]string, int64, error) {
	l.mutex.Lock()
	defer l.mutex.Unlock()
	data, err := os.ReadFile(l.path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, 0, nil
	}
	if err != nil {
		return nil, 0, fmt.Errorf("the audit log %s cannot be read: %s", l.path, reasonOf(err))
	}
	last, _, err := verifyChain(bytes.NewReader(data))
	if err != nil {
		return nil, 0, fmt.Errorf("the audit log fails its chain check, so it is not shipped: %w", err)
	}
	var lines []string
	for index, line := range strings.Split(strings.TrimRight(string(data), "\n"), "\n") {
		if int64(index+1) > seq && line != "" {
			lines = append(lines, line)
		}
	}
	return lines, last, nil
}
