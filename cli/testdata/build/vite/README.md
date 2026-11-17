# A recorded Vite build (Phase 38 part 1)

`out/.vite/manifest.json` and the files it names, generated once and kept
as they are: `cli/internal/extract/build_test.go` and
`cli/internal/check/bundles_test.go` read them.

- `index.html` statically imports `_shared-c3d4.js` and lists a stylesheet;
  it dynamically imports `src/lazy.tsx`, the largest file, which its initial
  download leaves out.
- `admin.html` imports the same shared chunk, which each entry counts once.
- `assets/shared-c3d4.js` holds secret-looking strings: the facts must hold
  its name and size, never them.
