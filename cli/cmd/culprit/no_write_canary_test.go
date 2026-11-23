// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// The project the no-write canary reads: its conventional entry point
// (config.wsgi) imports a module of its own and then fails, as the GUIDE's
// tour did (F44-003).
var importedProject = map[string]string{
	"config/__init__.py": "",
	"config/settings.py": "DEBUG = False\n",
	"config/wsgi.py":     "from config import settings  # noqa: F401\nraise KeyError('DATABASE_URL')\n",
}

// Two extractors: Culprit's own Python extractor in import mode, and a
// stand-in for anyone else's — a Python command that imports the
// project's module. Only the variable the orchestrator sets protects the
// second, so dropping it turns this test red.
const noWriteManifest = `version: 1
components:
  - name: api
    kind: service
extract:
  extractors:
    - name: python
      command: ["uv", "run", "--project", %[1]q, "culprit-extract-python"]
    - name: someone-elses
      command: ["uv", "run", "--project", %[1]q, "python", "-c", "import config.settings"]
  components:
    api: { root: ., extractors: [python, someone-elses] }
`

// snapshot is every file under root, with its size and a hash of its bytes.
func snapshot(t *testing.T, root string) map[string]string {
	t.Helper()
	files := map[string]string{}
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() {
			return err
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		sum := sha256.Sum256(data)
		relative, _ := filepath.Rel(root, path)
		files[filepath.ToSlash(relative)] = fmt.Sprintf("%d %s", len(data), hex.EncodeToString(sum[:]))
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return files
}

// TestCulpritWritesNothingIntoTheProjectItReads (Phase 44 batch 1,
// decision 5): the project's tree — paths, sizes, hashes — is the same
// after `culprit intent` and `culprit check` in import mode as before.
// Every extractor runs with PYTHONDONTWRITEBYTECODE=1.
func TestCulpritWritesNothingIntoTheProjectItReads(t *testing.T) {
	extractor, err := filepath.Abs(filepath.Join("..", "..", "..", "extractors", "python"))
	if err != nil {
		t.Fatal(err)
	}
	project := t.TempDir()
	for relative, text := range importedProject {
		path := filepath.Join(project, filepath.FromSlash(relative))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	manifest := filepath.Join(project, "culprit.yaml")
	if err := os.WriteFile(manifest, []byte(fmt.Sprintf(noWriteManifest, extractor)), 0o600); err != nil {
		t.Fatal(err)
	}
	// An orchestrator's own environment may say otherwise; the extractor's
	// must not depend on it.
	t.Setenv("PYTHONDONTWRITEBYTECODE", "")

	before := snapshot(t, project)
	var reached bool
	for _, arguments := range [][]string{
		{"intent", "-f", manifest, "--format", "json"},
		{"check", "-f", manifest, "--format", "json"},
	} {
		var stdout, stderr bytes.Buffer
		code := execute(arguments, &stdout, &stderr)
		if code == exitError {
			t.Fatalf("%s: exit %d: %s", arguments[0], code, stderr.String())
		}
		// The extractor did import the project: the failure is its own.
		reached = reached || strings.Contains(stdout.String(), "DATABASE_URL")
	}
	if !reached {
		t.Fatal("neither command imported the project, so nothing was tested")
	}
	after := snapshot(t, project)
	for path, sum := range after {
		if before[path] != sum {
			t.Errorf("%s was written into the project", path)
		}
	}
	for path := range before {
		if _, kept := after[path]; !kept {
			t.Errorf("%s was removed from the project", path)
		}
	}
}
