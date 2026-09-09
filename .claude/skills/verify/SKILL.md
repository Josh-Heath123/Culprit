---
name: verify
description: Run every gate this repository enforces and report honestly what passed, what failed and what could not be run. Use before declaring work complete, before merging, and any time you are about to claim something works.
---

Run the full gate set. Report results; do not fix anything unless asked.

Run these in order and stop reporting a stage as passed only if it actually
exited zero:

```
just lint
just typecheck
just lint-imports
just check-schema-drift
just test
uv run python scripts/check_coupled_files.py --base origin/main
```

Then, once Phase 29 exists, dogfood:

```
culprit check --fail-on=breaks_request_path
```

And once `LLM_PROVIDER=none` support exists (Phase 29 onward), the negative test
that keeps the product honest:

```
LLM_PROVIDER=none culprit check
```

## Rules

- **A gate you did not run is not a gate that passed.** Report it as `NOT RUN`
  with the reason. Never infer a pass.
- If a gate fails, delegate to the `test-triage` agent rather than pasting its
  output here.
- Do not weaken a gate to make it pass. Widening a `lint-imports` contract,
  adding a `# type: ignore`, skipping a test or extending a suppression without a
  reason is a finding, not a fix.
- `git status` in this repo is dominated by CRLF noise. Use
  `git diff --ignore-space-at-eol --stat` when you need to see what actually
  changed.

## Output

One line per gate: name, `PASS` / `FAIL` / `NOT RUN`, and for failures the single
most useful line of output. Then an overall verdict. Then, if anything failed,
what you propose to do about it — but do not do it yet.
