---
name: phase
description: Execute one numbered phase of docs/DIAGNOSTIC_PLAN.md end to end — read the phase, check preconditions, branch, implement only that phase, and stop at its stated boundary.
argument-hint: "<phase-number>"
---

Execute Phase $1 of `docs/DIAGNOSTIC_PLAN.md`. Do not work on any other phase.

Current branch and state:

!`git status --short --ignore-submodules | head -20`
!`git branch --show-current`

## Procedure

1. **Read the phase.** Open `docs/DIAGNOSTIC_PLAN.md`, read §1 (invariants),
   §2 (the core model — planes, facts, subject URIs, divergences, probes,
   capabilities), and the full Phase $1 section including all 17 fields.

2. **Check preconditions.** Confirm the previous phase's acceptance criteria are
   met. If they are not, stop and say so — phases are ordered because later ones
   depend on earlier ones being real.

3. **Branch.** `git checkout -b phase-$1-<short-slug>`. Never work on `main`.

4. **Plan before writing.** Produce a short ordered task list derived from
   fields 4 (create), 5 (modify) and 6 (remove). Confirm the list covers every
   item in those fields and nothing outside them.

5. **Implement.** Follow the plan's stated interfaces and data models exactly —
   they are contracts, and later phases are written against them. Where the plan
   specifies a table name, a field name, a subject URI shape or an exit code, use
   that one.

6. **Respect field 17.** Field 17 lists what must NOT be built yet. Treat it as
   binding. If implementing the phase seems to require something in field 17,
   stop and raise it rather than quietly widening scope.

7. **Test as you go.** Field 13 states the testing requirement. Write those tests
   in the same commits as the code they cover, not at the end.

8. **Per-phase obligations.** Every phase must also: update `docs/LIMITS.md` with
   any new limit it introduces, add any new deterministic package to the
   `lint-imports` contract in `worker/pyproject.toml` in the same commit, and
   keep `CLAUDE.md`'s status section current.

9. **Verify.** Run `/verify`. Then invoke the `phase-auditor` agent to check the
   acceptance criteria by execution.

10. **Report.** State what was built, what was deliberately left out per field 17,
    and anything in the plan that turned out to be wrong or under-specified —
    the plan is a document to correct, not a script to obey.

## Rules

- If the phase as written conflicts with what you find in the code, say so before
  implementing. A plan written against a repository snapshot can be wrong.
- Do not refactor code the phase does not name. Opportunistic cleanup makes the
  diff unreviewable and hides the actual change.
