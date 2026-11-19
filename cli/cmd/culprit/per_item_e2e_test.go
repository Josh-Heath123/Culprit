// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Phase 39 part 1's criterion against a real PostgreSQL 16 (the database
// boundary step in CI): a local test server answers a list of N items. Its
// /items route runs the list's own statement and then one statement per
// item, as an N+1 does; its /joined route loads the same list in one
// statement. `culprit probe -p probe.db.statements_per_request`, the whole
// path through the binary's runner, the manifest's isolated: and the real
// bracket and guarded client, measures the per-item statement at N calls
// and names it; on /joined every statement measures one call and none is
// named. In an environment not declared isolated nothing reaches the
// server. The per-item statement carries a secret-looking constant and the
// items secret-looking values: neither reaches a reading.

const perItemCount = 6

const perItemSecret = "sk_live_SECRETKEY-hunter2"

func perItemManifest(isolated bool) string {
	return fmt.Sprintf(`version: 1
components:
  - name: shop
    kind: service
    connections:
      - to: shop-db
        kind: sql
        criticality: on_request_path
  - name: shop-db
    kind: database
environments:
  lab:
    adapter: process
    isolated: %v
    components:
      shop:
        database: { dsn_env: CULPRIT_TEST_PER_ITEM_DSN, name: shop-db }
    grants:
      db.stats.read: true
      net.http.outbound: true
`, isolated)
}

func TestStatementsPerRequestAgainstARealPostgres(t *testing.T) {
	if os.Getenv("CULPRIT_DOCKER_TESTS") != "1" {
		t.Skip("NOT RUN: set CULPRIT_DOCKER_TESTS=1 to run the per-item bracket test (needs Docker)")
	}
	container, address := startPostgresWithStatements(t)
	setup := `
		CREATE EXTENSION pg_stat_statements;
		CREATE TABLE items (id int PRIMARY KEY, name text NOT NULL);
		CREATE TABLE tags (item_id int NOT NULL REFERENCES items (id), name text NOT NULL);
		INSERT INTO items SELECT i, 'item ' || i FROM generate_series(1, ` + fmt.Sprint(perItemCount) + `) i;
		INSERT INTO tags SELECT i, 'tag ' || i FROM generate_series(1, ` + fmt.Sprint(perItemCount) + `) i;
		CREATE ROLE app LOGIN PASSWORD 'app-pass';
		GRANT SELECT ON items, tags TO app;
		CREATE ROLE reader LOGIN PASSWORD 'reader-pass' IN ROLE pg_read_all_stats;`
	if err := runSQL(t, container, "postgres", "index-test", "shop", setup); err != nil {
		t.Fatal("setting up the test database failed")
	}
	t.Setenv("CULPRIT_TEST_PER_ITEM_DSN", "postgresql://reader:reader-pass@"+address+"/shop?sslmode=disable")

	// The application: each GET runs its statements as app, through one
	// psql, before it answers.
	var requests atomic.Int64
	asApp := func(statements []string) error {
		args := []string{"exec", "-e", "PGPASSWORD=app-pass", container, "psql", "-v", "ON_ERROR_STOP=1",
			"-q", "-h", "127.0.0.1", "-U", "app", "-d", "shop"}
		for _, statement := range statements {
			args = append(args, "-c", statement)
		}
		return exec.Command("docker", args...).Run()
	}
	items := make([]any, perItemCount)
	for index := range items {
		items[index] = map[string]any{"id": index + 1, "token": perItemSecret, "email": "customer@private.example"}
	}
	answer := func(w http.ResponseWriter, statements []string) {
		requests.Add(1)
		if err := asApp(statements); err != nil {
			http.Error(w, "the database did not answer", http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"items": items})
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/items", func(w http.ResponseWriter, r *http.Request) {
		statements := []string{"SELECT id, name FROM items ORDER BY id"}
		for id := 1; id <= perItemCount; id++ {
			statements = append(statements, fmt.Sprintf(
				"SELECT name FROM tags WHERE item_id = %d AND name <> '%s'", id, perItemSecret))
		}
		answer(w, statements)
	})
	mux.HandleFunc("/joined", func(w http.ResponseWriter, r *http.Request) {
		answer(w, []string{"SELECT i.id, t.name FROM items i JOIN tags t ON t.item_id = i.id ORDER BY i.id"})
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	run := func(isolated bool, route string) model.Reading {
		t.Helper()
		path := filepath.Join(t.TempDir(), "culprit.yaml")
		if err := os.WriteFile(path, []byte(perItemManifest(isolated)), 0o600); err != nil {
			t.Fatal(err)
		}
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
		defer cancel()
		readings, _, err := runProbe(ctx, probeInput{
			ManifestPath: path, Environment: "lab", Target: "http:shop/GET " + route, AgentID: "test",
			ProbeIDs:  []string{model.StatementsPerRequestProbeID},
			Inputs:    map[string]any{"base_url": server.URL, "at": "/items"},
			NoPlugins: true, Timeout: 20 * time.Second,
		})
		if err != nil || len(readings) != 1 {
			t.Fatalf("culprit probe %s: %v %d readings", route, err, len(readings))
		}
		encoded, _ := json.Marshal(readings[0])
		for _, secret := range []string{"hunter2", "sk_live", "private.example", "email", "token"} {
			if strings.Contains(string(encoded), secret) {
				t.Errorf("%s: the reading holds %q: %s", route, secret, encoded)
			}
		}
		if err := readings[0].Validate(); err != nil {
			t.Errorf("%s: the reading does not validate: %v", route, err)
		}
		return readings[0]
	}
	statementsOf := func(reading model.Reading) []map[string]any {
		var out []map[string]any
		list, _ := reading.Measured["statements"].([]any)
		for _, item := range list {
			out = append(out, item.(map[string]any))
		}
		return out
	}

	// Not declared isolated: nothing is sent.
	if reading := run(false, "/items"); reading.Verdict != model.VerdictInconclusive ||
		!strings.Contains(reading.Reason, "not declared isolated") || requests.Load() != 0 {
		t.Fatalf("not isolated: %s (%s), %d request(s) reached the server", reading.Verdict, reading.Reason, requests.Load())
	}

	// The N+1: the per-item statement measures N calls, and is named.
	nPlusOne := run(true, "/items")
	t.Logf("MEASURED /items: %s, %v: %s", nPlusOne.Verdict, nPlusOne.Measured["per_item"], nPlusOne.Reason)
	if nPlusOne.Verdict != model.VerdictPass || nPlusOne.Measured["items"] != perItemCount {
		t.Fatalf("/items: %s (%s) %v", nPlusOne.Verdict, nPlusOne.Reason, nPlusOne.Measured)
	}
	perItem, _ := nPlusOne.Measured["per_item"].([]string)
	if len(perItem) != 1 {
		t.Fatalf("/items: per_item %v, want the tags statement alone", perItem)
	}
	found := false
	for _, statement := range statementsOf(nPlusOne) {
		text, _ := statement["text"].(string)
		switch {
		case strings.Contains(text, "FROM tags"):
			found = true
			if statement["queryid"] != perItem[0] || statement["calls"] != perItemCount {
				t.Errorf("/items: the tags statement %v, want %d calls and named", statement, perItemCount)
			}
		case strings.Contains(text, "FROM items"):
			if statement["calls"] != 1 {
				t.Errorf("/items: the list's statement %v, want 1 call", statement)
			}
		}
	}
	if !found {
		t.Errorf("/items: the tags statement is not in the bracket: %v", statementsOf(nPlusOne))
	}

	// Loaded together: every statement one call, none named.
	joined := run(true, "/joined")
	t.Logf("MEASURED /joined: %s, %v: %s", joined.Verdict, joined.Measured["per_item"], joined.Reason)
	if joined.Verdict != model.VerdictPass {
		t.Fatalf("/joined: %s (%s)", joined.Verdict, joined.Reason)
	}
	if named, _ := joined.Measured["per_item"].([]string); len(named) != 0 {
		t.Errorf("/joined: per_item %v, want none", named)
	}
	if len(statementsOf(joined)) == 0 {
		t.Error("/joined: no statement in the bracket")
	}
	for _, statement := range statementsOf(joined) {
		if statement["calls"] != 1 {
			t.Errorf("/joined: %v, want every statement at one call", statement)
		}
	}
}
