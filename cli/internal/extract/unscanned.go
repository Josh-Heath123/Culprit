// SPDX-FileCopyrightText: 2026 Joshua Heath
// SPDX-License-Identifier: AGPL-3.0-only

package extract

import (
	"errors"
	"fmt"
	"io/fs"
	"strings"

	"github.com/josh-heath123/culprit/cli/internal/model"
)

// maxNamedUnscanned bounds how many directories are named one by one; the
// rest are counted in one more skip, so a deep tree cannot bury a report.
const maxNamedUnscanned = 20

// unscanned walks a component's tree as findFiles does — the same skipped
// directories, the same depth bound — and names every directory the
// built-in readers could not look inside (F44-057): one that could not be
// listed, and one below maxScanDepth. Each is a skip with want "*", since
// any kind of fact could have been there. A directory in skipDirs is not
// named: leaving third-party code and caches out is a choice, not a hole.
//
// Deterministic: fs.WalkDir is lexical, and paths are forward-slashed and
// relative to the component's root.
func unscanned(fsys fs.FS) []model.Skip {
	var named []string
	_ = fs.WalkDir(fsys, ".", func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			if path != "." && (entry == nil || entry.IsDir()) {
				named = append(named, fmt.Sprintf("%s/ could not be read (%s); nothing under it was read",
					path, reasonOf(err)))
			}
			if entry != nil && entry.IsDir() {
				return fs.SkipDir
			}
			return nil
		}
		if !entry.IsDir() || path == "." {
			return nil
		}
		if skipDirs[entry.Name()] {
			return fs.SkipDir
		}
		if strings.Count(path, "/")+1 > maxScanDepth {
			named = append(named, fmt.Sprintf(
				"%s/ is more than %d directories below the component's root; nothing under it was read",
				path, maxScanDepth))
			return fs.SkipDir
		}
		return nil
	})
	var skips []model.Skip
	for index, reason := range named {
		if index == maxNamedUnscanned {
			skips = append(skips, model.Skip{Want: "*", Reason: fmt.Sprintf(
				"and %d more directories could not be read or were below the scan depth",
				len(named)-maxNamedUnscanned)})
			break
		}
		skips = append(skips, model.Skip{Want: "*", Reason: reason})
	}
	return skips
}

// reasonOf names an error's kind in closed words: never its text, which
// carries an absolute path.
func reasonOf(err error) string {
	switch {
	case errors.Is(err, fs.ErrPermission):
		return "permission denied"
	case errors.Is(err, fs.ErrNotExist):
		return "it no longer exists"
	default:
		return "an error listing it"
	}
}
