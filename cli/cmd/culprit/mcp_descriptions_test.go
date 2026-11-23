// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package main

import (
	"strings"
	"testing"
)

// TestEveryToolSaysItCanRunTheManifestsCommands (Phase 44 batch 1,
// decisions 5 and 7; F44-003, F44-083): every tool resolves INTENT, so
// every tool can run the extractors culprit.yaml declares — commands that
// run as the user, one of which may import the project's own code. Each
// description says so, and none claims to read files only.
func TestEveryToolSaysItCanRunTheManifestsCommands(t *testing.T) {
	server := &mcpServer{manifestPath: "culprit.yaml"}
	tools := server.protocol().Tools
	if len(tools) == 0 {
		t.Fatal("no tools")
	}
	for _, tool := range tools {
		if strings.Contains(tool.Description, "Reads files only") {
			t.Errorf("%s still says it reads files only", tool.Name)
		}
		for _, want := range []string{"runs the extractors culprit.yaml declares", "as you", "import mode runs the project's own code", "--no-plugins"} {
			if !strings.Contains(tool.Description, want) {
				t.Errorf("%s does not say %q: %s", tool.Name, want, tool.Description)
			}
		}
	}
}
