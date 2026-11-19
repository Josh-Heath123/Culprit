// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package diverge

import (
	"fmt"
	"sort"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// Bundle budgets (Phase 38 part 1): an entry of a frontend build over its
// `bundle_gzip_bytes_max` is a finding of severity `degrades`.
//
// It is its own finding, not a Divergence. A Divergence's two sides share
// one predicate, in Go and in culprit_model.facts alike, and that is what
// POST /divergences/captures validates against; a budget
// (`bundle_gzip_bytes_max`, INTENT) and what the build measured
// (`bundle_gzip_bytes`, OBSERVED) do not. Ruled 2026-11-17 for part 1:
// a finding of its own, counted by --fail-on, in every format `check`
// writes, the Divergence model untouched.
//
// The rule is a comparison of whole numbers: over is strictly greater. An
// entry at or under its budget produces nothing.

// BundleChunk is one file of an entry's initial download, as the build
// reader names it.
type BundleChunk struct {
	File      string `json:"file"`
	GzipBytes int64  `json:"gzip_bytes"`
}

// BundleFinding is an entry over its gzip budget.
type BundleFinding struct {
	Subject  string         `json:"subject"`
	Severity model.Severity `json:"severity"`
	// Explanation is one sentence built from the two facts, never prose
	// from anywhere else (D8).
	Explanation string `json:"explanation"`
	// Budget is the INTENT fact, with where it was declared; Measured the
	// build's OBSERVED gzip size.
	Budget   model.Fact `json:"budget"`
	Measured model.Fact `json:"measured"`
	// Largest are the entry's three largest files by gzipped size.
	Largest []BundleChunk `json:"largest"`
}

// BundleBudgets judges every bundle budget among budgets against what the
// build reader measured (build). A budget on an entry the build does not
// have is a "Not checked" line naming it; a budget on a build that could
// not be read says nothing more, because the reader already said why.
func BundleBudgets(budgets, build []model.Fact) ([]BundleFinding, []model.Skip) {
	measured := map[string]model.Fact{}
	largest := map[string]model.Fact{}
	read := map[string]bool{} // components whose build was read
	for _, fact := range build {
		if fact.Plane != model.PlaneObserved || fact.Environment != model.BuildEnvironment {
			continue
		}
		kind, parts, err := model.ParseSubject(fact.Subject)
		if err != nil || kind != model.KindBundle {
			continue
		}
		read[parts["component"]] = true
		switch fact.Predicate {
		case model.PredicateBundleGzipBytes:
			measured[fact.Subject] = fact
		case model.PredicateBundleLargestChunks:
			largest[fact.Subject] = fact
		}
	}

	findings := []BundleFinding{}
	notChecked := []model.Skip{}
	for _, budget := range budgets {
		if budget.Plane != model.PlaneIntent || !model.BundleBudgetPredicates[budget.Predicate] {
			continue
		}
		_, parts, err := model.ParseSubject(budget.Subject)
		if err != nil {
			continue
		}
		size, found := measured[budget.Subject]
		if !found {
			if read[parts["component"]] {
				notChecked = append(notChecked, model.Skip{
					Want:      budget.Predicate,
					Component: parts["component"],
					Extractor: budget.Provenance.Extractor,
					Reason: fmt.Sprintf("%s (%s) budgets the entry %q, which the build does not have",
						budget.Provenance.Locator, budget.Subject, parts["entry"]),
				})
			}
			continue
		}
		limit, limitOK := wholeBytes(budget.Value)
		bytes, bytesOK := wholeBytes(size.Value)
		if !limitOK || !bytesOK || bytes <= limit {
			continue
		}
		chunks := chunksOf(largest[budget.Subject])
		findings = append(findings, BundleFinding{
			Subject:     budget.Subject,
			Severity:    model.SeverityDegrades,
			Explanation: explainBundle(parts["entry"], bytes, limit, budget.Provenance.Locator, chunks),
			Budget:      budget,
			Measured:    size,
			Largest:     chunks,
		})
	}
	sort.Slice(findings, func(i, j int) bool { return findings[i].Subject < findings[j].Subject })
	sort.Slice(notChecked, func(i, j int) bool { return notChecked[i].Reason < notChecked[j].Reason })
	return findings, notChecked
}

func explainBundle(entry string, bytes, limit int64, locator string, chunks []BundleChunk) string {
	named := make([]string, 0, len(chunks))
	for _, chunk := range chunks {
		named = append(named, fmt.Sprintf("%s %d", chunk.File, chunk.GzipBytes))
	}
	return fmt.Sprintf("%s downloads %d bytes gzipped when it first loads, over its budget of %d (%s). "+
		"Largest, gzipped: %s.", entry, bytes, limit, locator, strings.Join(named, ", "))
}

// wholeBytes reads a fact's value as a whole number, as a fact built in
// this process (int, int64) or decoded from JSON (float64) holds it.
func wholeBytes(value any) (int64, bool) {
	switch typed := value.(type) {
	case int:
		return int64(typed), true
	case int64:
		return typed, true
	case float64:
		if typed == float64(int64(typed)) {
			return int64(typed), true
		}
	}
	return 0, false
}

// chunksOf reads the build reader's bundle_largest_chunks value.
func chunksOf(fact model.Fact) []BundleChunk {
	items, _ := fact.Value.([]any)
	chunks := make([]BundleChunk, 0, len(items))
	for _, item := range items {
		entry, _ := item.(map[string]any)
		file, _ := entry["file"].(string)
		size, _ := wholeBytes(entry["gzip_bytes"])
		if file != "" {
			chunks = append(chunks, BundleChunk{File: file, GzipBytes: size})
		}
	}
	return chunks
}
