---
paths:
  - "worker/app/**"
  - "cli/internal/**"
  - "mcp_server/**"
  - "shared/culprit_model/**"
  - "scripts/check_*.py"
---

# The determinism boundary

This is the rule most likely to be violated silently, because "just ask the
model" is always the shortest path and always looks fine in a demo.

**Deterministic — no LLM call, ever:**

- Anomaly and impedance scoring (`worker/app/anomaly/`)
- Fact extraction and comparison (`cli/internal/extract/`, `cli/internal/diverge/`)
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

**If a change needs to cross this boundary, that is the signal the rule is about
to be broken — not a lint configuration to relax.** Widening a contract,
shortening a forbidden-module list or adding an ignore is the violation itself.

## The test that keeps it honest

`LLM_PROVIDER=none` must produce complete, correct output from every command
except the prose field. If that stops being true, the product has become the
thing it was built not to be.
