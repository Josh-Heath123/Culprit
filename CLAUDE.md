# CLAUDE.md

Guidance for Claude Code in this repository. Kept under 8 KB on purpose: it
loads into every session. Detail lives where it is wanted — see "Where things
are" below.

## Where the work is

**Read `docs/HANDOFF.md` first, every session.** §1 names the current phase,
its branch and whether the gates are green; §3 is the open-questions inbox; §4
the phase ledger; §5 the last run report. This file describes the repository;
the handoff describes where the work is. If they disagree, the handoff wins.

- **Current phase:** 34, part 2 — outcomes in the control plane
  (verifications stored and shown, the agent's `verify` task,
  `GET /outcomes/accuracy`), on branch `phase-34-outcomes`. Phases 26–33 and
  34 part 1 are merged.
- **Plan of record:** `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35). Read §1 (D1–D8),
  §2 (the core model) and the phase you are working on — not the whole file.
- **Deploy is paused** (2026-11-05): the hosted VM is offline, and the `deploy`
  job runs only when started by hand. Phase 33 builds against a local control
  plane.
- **Claude Code commits, pushes and opens the pull request; only the human
  merges.** Commit on the phase branch (`git commit -F <file>`, never
  `shared/uv.lock`), push it, open the PR with `gh pr create`, run `/ci`. Never
  push to `main`, force-push, merge or approve. A phase is complete only when
  CI is green on the merge result, and the next phase never starts without a
  human keystroke.

## What Culprit is

A diagnostic engine for small teams running a few services without an SRE
function. It holds three planes of truth — INTENT (what the system is meant to
do, extracted from code and specs), CONFIGURED (what an environment is set up
to do) and OBSERVED (what probes actually read) — and treats the divergence
between them as the finding. `culprit check` finds contradictions in CI with
no runtime access; `culprit diagnose` walks the request path from a symptom
with read-only probes and records an investigation whose every edge cites a
reading; `culprit verify` re-measures it after a fix and judges whether the
fix fixed it. It began as an incident-correlation copilot; that engine was removed
in Phase 32, and the incident tables are read-only history.

## Scope ceilings

- Two or three demo services (`demo-services/`), not a multi-tenant platform.
- Redis Streams, not Kafka. Statistical anomaly scoring, not trained models.
- No write capability in any probe; Culprit recommends a fix, never applies one.
- A task that does not fit is flagged back, not quietly widened.

## Rules that are enforced, not stated

- **Determinism.** Facts, divergences, readings, verdicts and hypotheses are
  never an LLM's output. `.claude/rules/determinism.md` (loaded when you touch
  `worker/`, `cli/internal/`, `extractors/`) has the boundary and its gates.
- **Database roles.** Add a role; never widen one. `.claude/rules/database.md`.
- **Subjects.** Built only through `subjects.build()` and its Go/TS twins,
  held together by `shared/tests/*conformance.json`. `.claude/rules/model.md`.
- Never make a gate green by weakening it — widening a contract, an ignore, a
  skipped test or a wider role is an escalation (`docs/HANDOFF.md` §6).

## Commands (all through `just`)

```bash
just up / just down            # Postgres+Timescale+pgvector, Redis, Grafana+Tempo
just dev / just migrate        # api with autoreload / alembic upgrade head
just test                      # api (+scripts, shared), worker, mcp_server
cd api && uv run pytest tests/path::test_name -v    # one test, not the suite
just lint / typecheck / lint-imports / check-schema-drift
just check-no-llm-imports / check-invariants / check-scan-coverage
just check-migration-round-trip                     # needs Docker
just check-frontend-tokens
just cli-build / cli-test / cli-lint                # Go CLI -> cli/bin/culprit
just extractors-test
just fault-library             # every fault: injected, walked, fixed, verified (Docker)
just intent [--format json]    # culprit intent over this repository
just generate-types            # frontend types from the api's OpenAPI schema
just frontend / frontend-build
just quickstart / quickstart-down   # full stack + demo services + a diagnosed fault
just e2e                       # Playwright against the quickstart stack
just apply-model <file.yaml>   # declarative culprit.yaml
just create-user <name> --role admin
```

`/verify` runs the local gate set and reports it honestly; `/ci` proves the
merge result in CI. Local green is necessary, not sufficient.

## Line endings

`.gitattributes` stores and checks out every text file as LF (Phase 32.2).
A Windows working copy made before it may still be CRLF on disk, so a file
can show as modified with no real change: trust
`git diff --ignore-space-at-eol`, and never commit an "everything changed"
diff without checking it.

## Where things are

| | |
|---|---|
| Architecture, layer by layer, and the CI/Docker traps | `docs/ARCHITECTURE.md` |
| Limits a user can hit | `docs/LIMITS.md` |
| Every grant and role | `docs/PERMISSIONS.md` |
| Probes | `docs/PROBES.md` |
| Extractor protocol | `docs/EXTRACTOR_PROTOCOL.md` |
| Install, upgrade | `docs/INSTALL.md`, `docs/UPGRADING.md` |
| Earlier plans (history) | `docs/IMPLEMENTATION_PLAN.md` (0–12), `docs/SELF_HOSTED_PLAN.md` (13–20), `docs/AI_NATIVE_PLAN.md` (21–25) |

Don't dump raw ingested logs or metrics into context; query a bounded window.
Don't run the full suite for a one-line change.
