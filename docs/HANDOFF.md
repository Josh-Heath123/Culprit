# Handoff — the baton between architecture and execution

This file is the state carrier for Culprit's development. It exists because the
architecture conversation and the implementation session are different places,
and a decision that lives only in a chat transcript is a decision that gets made
twice.

**Protocol.**

- **The architecture session writes** §2 (Decisions), §3 (Open questions) and the
  *Brief* line of the current phase in §4. It never writes run reports.
- **Claude Code writes** §4 status transitions and §5 (Last run). It never
  answers an open question in §3 on its own — it surfaces the question and stops.
- **Both read the whole file first.** It is committed, so `git log docs/HANDOFF.md`
  is the decision history.

**The one rule that makes this work:** a phase does not advance on a red gate,
and Claude Code does not auto-start the next phase. One human keystroke per
phase is not friction — it is the review checkpoint, and it is the only place a
wrong architectural turn gets caught before it is built on.

---

## §1. Where things stand

| | |
|---|---|
| Plan of record | `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35) |
| Current phase | **26 — Truth repair and the three-plane schema** |
| Status | Not started |
| Branch | — |
| Blocking questions | 2 open (§3) — Q1 blocks Phase 28, not Phase 26 |
| Last gate run | None |

Phase 25 (memory visualisation) is **cancelled**. Do not implement it.

---

## §2. Decisions register

Decisions made and not to be relitigated per session. Architectural decisions
D1–D8 live in `docs/DIAGNOSTIC_PLAN.md` §1 with their alternatives and revisit
triggers; this section records the session-level ones and anything that
supersedes the plan.

| Date | Decision | Rationale |
|---|---|---|
| 2026-09-08 | Evolve the existing repository. No new repo. | Requirements changing is normal; the substrate (role model, CI, ingest, Timescale/pgvector) is real capital. |
| 2026-09-08 | Target user is solo developers and small teams without SRE/DevOps. Not enterprise. | Determines that the CLI wedge outranks the production agent in sequencing. |
| 2026-09-08 | Deterministic core; AI optional. `LLM_PROVIDER=none` must produce complete correct output from every command except prose. | This is the product's defensible property and is enforced as a CI job, not an aspiration. |
| 2026-09-08 | Tier-3 business-logic correctness is out of scope permanently. | No oracle exists. Promising it fails the product's own standard on first contact. The shippable version is the unverifiable-surface report (Phase 29). |
| 2026-09-08 | No `mutate`-effect probe and no `*.write` capability in this entire plan. | Structural boundary, not a config flag. Adding one requires its own plan document. |
| 2026-09-08 | Historical baseline is a statistic over `OBSERVED`, never a fourth plane. | Treating "usual" as a proxy for "correct" is the exact mistake the rewrite exists to fix. |

---

## §3. Open questions

Claude Code must not answer these. It surfaces them and stops.

**Q1 — Is Go acceptable for the CLI and probe agent?** (Blocks Phase 28.)
`docs/DIAGNOSTIC_PLAN.md` D2 chooses Go for a single static binary, because
`pip install` at the first-run moment is friction where it costs most. The cost
is two languages in one repo for a small team. Fallback if no: a Python CLI
distributed via PyInstaller — worse distribution, no rewrite. **Decide before
Phase 28 starts, not midway through it.**

**Q2 — Product or portfolio piece?** (Affects ordering from Phase 30 on.)
As written, the phases optimise for a usable product early: Phase 29 ships
something a stranger can run. If the priority is a portfolio artefact, Phases 31
(probes) and 32 (fault isolation) are the impressive ones and Phase 30 could be
deferred behind them.

---

## §4. Phase ledger

Status values: `not started` · `in progress` · `gates red` · `awaiting decision` ·
`complete`.

| Phase | Title | Status | Brief |
|---|---|---|---|
| 26 | Truth repair and the three-plane schema | not started | Start here. Deliberately the smallest and most mechanical phase — a good shakedown for the whole toolchain. Do the `CLAUDE.md` repair *first*, before any code: every session until it lands pays for the stale version. |
| 27 | The system model (the circuit) | not started | — |
| 28 | CLI, extractor protocol, intent extraction | not started | Blocked on Q1. |
| 29 | The divergence engine | not started | First shippable product. This is the wedge — treat its acceptance criteria as the real bar, especially "zero findings on a fixture known to be correct". |
| 30 | Environment capture and cross-env diff | not started | — |
| 31 | Probes | not started | — |
| 32 | Fault isolation and the Investigation | not started | — |
| 33 | Production agent and permission model | not started | — |
| 34 | Verification loop and calibration | not started | — |
| 35 | Agent surface and the narrator | not started | — |

---

## §5. Last run

Claude Code overwrites this section at the end of every `/next`.

```
Phase:        —
Branch:       —
Started:      —
Finished:     —

Gates:        (from /verify)
  lint            —
  typecheck       —
  lint-imports    —
  schema-drift    —
  tests           —
  coupled-files   —

Acceptance criteria (from phase-auditor):
  —

Built:        —
Deliberately not built (field 17):  —

Plan corrections needed:  —
Blocked on:               —
```

---

## §6. Escalate to the architecture session when

Do not guess on any of these. Stop, write the question into §3, and stop.

- The plan's stated interface, data model or acceptance criterion turns out to be
  wrong or under-specified against the real code.
- Implementing a phase appears to require something on its own field-17 list.
- A gate can only be made green by weakening it — widening a `lint-imports`
  contract, adding a `# type: ignore`, skipping a test, widening a Postgres role.
- A decision in §2 would have to be reversed.
- Two intent sources disagree in a way the plan does not describe how to rank.
