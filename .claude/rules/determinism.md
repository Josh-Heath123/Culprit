---
paths:
  - "worker/app/**"
  - "cli/internal/**"
  - "extractors/**"
  - "mcp_server/**"
  - "shared/culprit_model/**"
  - "scripts/check_*.py"
---

# The determinism boundary

This is the rule most likely to be violated silently, because "just ask the
model" is always the shortest path and always looks fine in a demo.

**Deterministic — no LLM call, ever:**

- Anomaly and impedance scoring (`worker/app/anomaly/`)
- Fact extraction and comparison (`cli/internal/extract/`, `cli/internal/diverge/`,
  and the extractor plugins in `extractors/`)
- Severity classification (`cli/internal/severity/`) — §2.5 states it directly:
  a divergence on a subject that lies on a known request path is
  `breaks_request_path`; one on an unreferenced config key is `cosmetic`.
  "It is never an LLM judgement."
- The check pipeline and every report format (`cli/internal/check/`,
  `cli/internal/report/`). `internal/check` links **no networking package at
  all** — not `net`, not `net/http`, not `crypto/tls` — and
  `cli/cmd/culprit/check_test.go` asserts it against `go list -deps`. A package
  that does not link a socket cannot open one, which is a stronger guarantee
  than any list of vendor names.
- Environment capture and the permission model (`cli/internal/capture/`,
  `cli/internal/capability/`, Phase 30). Capture is the first package in the
  binary that opens sockets — to a database, a resolver, an endpoint's TLS
  handshake — and it does so deterministically, under a named grant, with no
  LLM anywhere; it lives outside `internal/check` precisely so the check
  pipeline's no-networking assertion still holds. The Python snapshot diff
  (`shared/culprit_model/capture_diff.py`) is pure.
- Probe execution and readings (`cli/internal/probe/`)
- Fault isolation (`cli/internal/isolate/`)
- Verification (`cli/internal/verify/`)
- Subject construction and canonicalisation (`shared/culprit_model/`)
- The MCP tool implementations (`mcp_server/tools.py`)
- The repo's own check scripts (`scripts/check_*.py`)

**The single LLM call** is narration: rendering an already-settled fault tree
into prose, and ranking hypotheses within an already-computed set. It may not
create a fact, a divergence, a reading, a verdict or a hypothesis.

## Enforcement, not intention

`worker/pyproject.toml` declares `lint-imports` contracts; `scripts/tests/test_no_llm_imports.py`
and `mcp_server/tests/test_no_llm_chat_calls.py` walk the AST and assert no LLM
client is imported and that the Voyage client is only ever `.embed()`-ed.

`scripts/check_no_llm_imports.py` covers nine packages across three languages
(Phase 28) — the Python ones by AST walk, `cli/internal/` and `extractors/node/`
by import-line scan, since this repository has no Go or JavaScript parser and
importing a client is the observable act in both.

**If a change needs to cross this boundary, that is the signal the rule is about
to be broken — not a lint configuration to relax.** Widening a contract,
shortening a forbidden-module list or adding an ignore is the violation itself.

## The test that keeps it honest

`LLM_PROVIDER=none` must produce complete, correct output from every command
except the prose field. If that stops being true, the product has become the
thing it was built not to be.
