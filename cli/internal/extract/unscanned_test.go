// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package extract

import (
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"testing/fstest"
	"time"
)

// F44-057. A part of a repository the built-in readers could not read —
// a directory that refused to be listed, or one below the scan depth — is
// a skipped entry naming its path, never a silent hole in a clean report.

// refusing is an fs.FS one of whose directories cannot be listed: what a
// chmod 000 directory is on Linux, in a form Windows can run.
type refusing struct {
	fstest.MapFS
	locked string
}

func (r refusing) ReadDir(name string) ([]fs.DirEntry, error) {
	if name == r.locked {
		return nil, &fs.PathError{Op: "readdir", Path: name, Err: fs.ErrPermission}
	}
	return r.MapFS.ReadDir(name)
}

func TestAnUnreadableDirectoryIsNamed(t *testing.T) {
	fsys := refusing{MapFS: fstest.MapFS{
		"api/.env.example":     {Data: []byte("A=1\n")},
		"secret/keys/x.json":   {Data: []byte("{}")},
		"node_modules/x/y.txt": {Data: []byte("")},
	}, locked: "secret"}
	skips := unscanned(fsys)
	if len(skips) != 1 || !strings.Contains(skips[0].Reason, "secret/") ||
		!strings.Contains(skips[0].Reason, "could not be read") || skips[0].Want != "*" {
		t.Fatalf("skips = %+v, want one naming secret/", skips)
	}
}

func TestADirectoryBelowTheScanDepthIsNamed(t *testing.T) {
	deep := strings.Repeat("d/", maxScanDepth) + "e/openapi.json"
	fsys := fstest.MapFS{
		deep:                          {Data: []byte("{}")},
		strings.Repeat("s/", 6) + "x": {Data: []byte("")},
	}
	skips := unscanned(fsys)
	want := strings.Repeat("d/", maxScanDepth) + "e/"
	if len(skips) != 1 || !strings.Contains(skips[0].Reason, want) {
		t.Fatalf("skips = %+v, want one naming %s", skips, want)
	}
}

// TestTheExtractionRecordsWhatItCouldNotRead runs the real orchestrator
// over a component whose tree goes below the scan depth.
func TestTheExtractionRecordsWhatItCouldNotRead(t *testing.T) {
	root := t.TempDir()
	deep := filepath.Join(root, "svc", filepath.FromSlash(strings.Repeat("d/", maxScanDepth)+"e"))
	if err := os.MkdirAll(deep, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(deep, "openapi.json"), []byte("{}"), 0o644); err != nil {
		t.Fatal(err)
	}
	manifestPath := filepath.Join(root, "culprit.yaml")
	if err := os.WriteFile(manifestPath, []byte(`version: 1
components:
  - name: svc
extract:
  components:
    svc: {root: svc}
`), 0o644); err != nil {
		t.Fatal(err)
	}
	manifest, err := LoadManifest(manifestPath)
	if err != nil {
		t.Fatal(err)
	}
	bundle, err := Run(t.Context(), Options{Manifest: manifest, ManifestDir: root, SkipPlugins: true,
		Now: time.Unix(0, 0), Version: "test"})
	if err != nil {
		t.Fatal(err)
	}
	for _, skip := range bundle.Skipped {
		if skip.Component == "svc" && strings.Contains(skip.Reason, strings.Repeat("d/", maxScanDepth)+"e/") {
			return
		}
	}
	t.Fatalf("the directory below the scan depth is not named: %+v", bundle.Skipped)
}
