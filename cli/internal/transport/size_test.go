// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package transport

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/agent"
	"github.com/josh-heath123/culprit/cli/internal/model"
)

// The agent under the control plane's body cap (F44-043, as Q49 ruled): it
// ships its audit backlog and its readings in batches sized by bytes, under
// half the cap; an entry that alone is over the cap is kept locally and the
// agent carries on; a 413 is never met with the same request.

// capped is a control plane that refuses any body over limit with a 413,
// as api/app/body_limits.py does, and records every body it was sent.
type capped struct {
	mutex    sync.Mutex
	limit    int
	entries  []string // the audit chain it holds
	readings int
	bodies   []string // sha256 of every POST body, in order
	refused  map[string]bool
	sizes    []int
}

func (c *capped) handler(t *testing.T) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		c.mutex.Lock()
		defer c.mutex.Unlock()
		body, _ := io.ReadAll(r.Body)
		if r.Method == http.MethodPost {
			sum := fmt.Sprintf("%x", sha256.Sum256(body))
			if c.refused[sum] {
				t.Errorf("%s: a body refused with 413 was sent again unchanged", r.URL.Path)
			}
			c.bodies = append(c.bodies, sum)
			c.sizes = append(c.sizes, len(body))
			if len(body) > c.limit {
				c.refused[sum] = true
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(http.StatusRequestEntityTooLarge)
				_, _ = fmt.Fprintf(w, `{"detail": "over this route's limit of %d bytes (bulk)"}`, c.limit)
				return
			}
		}
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.URL.Path == "/agents/me/audit/head":
			_, _ = fmt.Fprintf(w, `{"seq":%d,"hash":"%s"}`, len(c.entries), strings.Repeat("0", 64))
		case r.URL.Path == "/agents/me/audit":
			var batch struct{ Entries []string }
			if err := json.Unmarshal(body, &batch); err != nil {
				t.Errorf("an audit batch that is not JSON: %v", err)
			}
			for index, line := range batch.Entries {
				var entry agent.Entry
				_ = json.Unmarshal([]byte(line), &entry)
				if entry.Seq != int64(len(c.entries)+1) {
					t.Errorf("entry %d of a batch has seq %d; the chain holds %d", index, entry.Seq, len(c.entries))
				}
				c.entries = append(c.entries, line)
			}
			_, _ = fmt.Fprintf(w, `{"seq":%d,"hash":"%s"}`, len(c.entries), strings.Repeat("0", 64))
		case r.URL.Path == "/readings":
			var batch struct{ Readings []model.Reading }
			_ = json.Unmarshal(body, &batch)
			c.readings += len(batch.Readings)
			w.WriteHeader(http.StatusCreated)
			_, _ = w.Write([]byte(`{"stored":0,"duplicates":0,"stored_at":"2026-11-26T00:00:00Z"}`))
		case strings.HasSuffix(r.URL.Path, "/result"):
			w.WriteHeader(http.StatusNoContent)
		default:
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
	})
}

func controlPlane(t *testing.T, limit int) (*capped, *Client) {
	t.Helper()
	plane := &capped{limit: limit, refused: map[string]bool{}}
	server := httptest.NewServer(plane.handler(t))
	t.Cleanup(server.Close)
	client, err := New(server.URL, "agent-size", newKey(t), 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	return plane, client
}

// backlog writes count entries to a fresh audit log, each with a reason of
// size(index) bytes.
func backlog(t *testing.T, count int, size func(index int) int) *agent.AuditLog {
	t.Helper()
	audit, err := agent.OpenAudit(filepath.Join(t.TempDir(), "audit.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	for index := 0; index < count; index++ {
		if _, err := audit.Append(agent.Entry{
			Time: time.Date(2026, 11, 26, 0, 0, index, 0, time.UTC), AgentID: "agent-size",
			TaskID: fmt.Sprintf("task-%d", index), Kind: agent.EntryTask, Outcome: "completed",
			Reason: strings.Repeat("r", size(index)),
		}); err != nil {
			t.Fatal(err)
		}
	}
	return audit
}

func TestABacklogOf500LargeEntriesShipsInSeveralRequests(t *testing.T) {
	// 500 entries of about 10 KB: about 5 MB, against a 1 MiB cap. In
	// requests of 500 entries, that was one request, refused, and the agent
	// stopped; restarted, it sent the same request again.
	plane, client := controlPlane(t, 1<<20)
	source := &Source{Client: client, Audit: backlog(t, 500, func(int) int { return 10_000 }), BodyBytes: 1 << 20}
	if err := source.ShipAudit(context.Background()); err != nil {
		t.Fatalf("the backlog was not shipped: %v", err)
	}
	if len(plane.entries) != 500 {
		t.Fatalf("the control plane holds %d of 500 entries", len(plane.entries))
	}
	if len(plane.bodies) < 5 {
		t.Fatalf("500 entries of 10 KB went in %d request(s); want several, each under half the cap", len(plane.bodies))
	}
	for index, size := range plane.sizes {
		if size > (1<<20)/2 {
			t.Errorf("request %d is %d bytes, over half the cap", index+1, size)
		}
	}
}

func TestAnOversizedEntryIsKeptLocallyAndTheAgentCarriesOn(t *testing.T) {
	// Entry 4 alone is over the cap. 1-3 are shipped; 4 is held, logged with
	// its reason, and never sent; the agent carries on, and a later ship
	// sends nothing more (the chain is in order).
	plane, client := controlPlane(t, 64<<10)
	audit := backlog(t, 6, func(index int) int {
		if index == 3 {
			return 100 << 10
		}
		return 200
	})
	var logged []string
	source := &Source{Client: client, Audit: audit, BodyBytes: 64 << 10,
		Logf: func(format string, args ...any) { logged = append(logged, fmt.Sprintf(format, args...)) }}
	for round := 0; round < 3; round++ {
		if err := source.ShipAudit(context.Background()); err != nil {
			t.Fatalf("round %d: the agent stopped on an oversized entry: %v", round, err)
		}
	}
	if len(plane.entries) != 3 {
		t.Fatalf("the control plane holds %d entries; want 1-3, before the held one", len(plane.entries))
	}
	for _, size := range plane.sizes {
		if size > 64<<10 {
			t.Fatalf("a body of %d bytes was sent, over the cap: the held entry left the agent", size)
		}
	}
	if len(logged) != 1 || !strings.Contains(logged[0], "audit entry 4 is") ||
		!strings.Contains(logged[0], "kept in the local audit log and not sent") {
		t.Fatalf("the agent's log says %q; want one line naming entry 4 and why", logged)
	}
	lines, _, err := audit.LinesAfter(0)
	if err != nil || len(lines) != 6 {
		t.Fatalf("the local log holds %d entries (%v); want all 6 kept", len(lines), err)
	}
}

func TestA413IsNeverRetriedUnchanged(t *testing.T) {
	// The control plane's cap is lower than the agent assumes (set lower
	// with CULPRIT_MAX_BULK_BODY_BYTES). Each 413 is met with a smaller
	// batch, never the same body (the server fails the test on a repeat),
	// and every entry arrives. An entry the control plane refuses alone is
	// held, and later ships do not send it again.
	plane, client := controlPlane(t, 16<<10)
	audit := backlog(t, 40, func(index int) int {
		if index == 30 {
			return 20 << 10 // under the agent's cap, over the control plane's
		}
		return 1_000
	})
	var logged []string
	source := &Source{Client: client, Audit: audit, BodyBytes: 1 << 20,
		Logf: func(format string, args ...any) { logged = append(logged, fmt.Sprintf(format, args...)) }}
	for round := 0; round < 3; round++ {
		if err := source.ShipAudit(context.Background()); err != nil {
			t.Fatalf("round %d: %v", round, err)
		}
	}
	if len(plane.entries) != 30 {
		t.Fatalf("the control plane holds %d entries; want the 30 before the refused one", len(plane.entries))
	}
	if len(logged) != 1 || !strings.Contains(logged[0], "audit entry 31") || !strings.Contains(logged[0], "(413)") {
		t.Fatalf("the agent's log says %q; want entry 31, refused alone", logged)
	}
	refusals := 0
	for _, refused := range plane.refused {
		if refused {
			refusals++
		}
	}
	if refusals == 0 {
		t.Fatal("no 413 was met: the test proves nothing")
	}
}

func TestReadingsShipInBatchesSizedByBytes(t *testing.T) {
	// 200 readings of about 5 KB against a 256 KiB cap: several requests,
	// each under half the cap, every reading stored.
	plane, client := controlPlane(t, 256<<10)
	readings := make([]model.Reading, 200)
	for index := range readings {
		readings[index] = model.Reading{ProbeID: "probe.http.status", ProbeVersion: 1,
			Target: fmt.Sprintf("http:svc/GET /items/%d", index), Environment: "local",
			Verdict: model.Verdict("pass"), Reason: strings.Repeat("m", 5_000), AgentID: "agent-size",
			TakenAt: time.Date(2026, 11, 26, 0, 0, 0, 0, time.UTC)}
	}
	source := &Source{Client: client, BodyBytes: 256 << 10}
	incoming := &agent.Incoming{Handle: "task-1", Task: agent.Task{ID: "task-1", Kind: "probe"}}
	if err := source.Complete(context.Background(), incoming, agent.Result{Outcome: "completed", Readings: readings}); err != nil {
		t.Fatalf("the result was not reported: %v", err)
	}
	if plane.readings != 200 {
		t.Fatalf("the control plane stored %d of 200 readings", plane.readings)
	}
	posts := 0
	for index, size := range plane.sizes {
		if size > (256<<10)/2 {
			t.Errorf("request %d is %d bytes, over half the cap", index+1, size)
		}
		posts++
	}
	if posts < 1+4 {
		t.Fatalf("200 readings of 5 KB and the result went in %d request(s); want several", posts)
	}
}
