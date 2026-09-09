---
name: next
description: Advance Culprit by exactly one phase — read the handoff, implement the current phase, run every gate, audit the acceptance criteria, write the run report back, and stop. Use to start or resume phase work.
---

Advance the project by **one** phase. Do not start a second one.

Current handoff state:

@docs/HANDOFF.md

Repository state:

!`git branch --show-current`
!`git status --short --ignore-submodules | head -20`

## Procedure

**1. Read the handoff.** `docs/HANDOFF.md` §1 gives the current phase and status;
§2 is the decisions register; §3 is open questions; §4 has the phase brief.

**2. Check for blockers before doing anything.**

- If any question in §3 is marked as blocking the current phase, **stop now.**
  Report which question and why it blocks. Do not answer it yourself — §3 is
  written by the architecture session, not by you.
- If §1 status is `gates red`, fix the gates before starting new work.
- If §1 status is `awaiting decision`, stop and report.

**3. Execute the phase.** Run `/phase <N>` for the current phase number. Follow
that skill's procedure exactly, including its field-17 boundary.

**4. Run the gates.** Run `/verify`. If anything is red, fix it and re-run.

Never make a gate green by weakening it. Widening a `lint-imports` contract,
adding a `# type: ignore`, skipping a test or widening a Postgres role to make a
check pass is an escalation (§6), not a fix.

**5. Audit.** Invoke the `phase-auditor` agent to check the acceptance criteria
by executing them. Then invoke `invariant-auditor` on the branch diff. Both must
come back clean.

**6. Update `docs/LIMITS.md`.** Run `/limits`. Every phase carries this
obligation — the Phase 23 heuristic went undocumented for months because it was
skipped.

**7. Write the run report.** Replace §5 of `docs/HANDOFF.md` with what actually
happened: gates, acceptance criteria verdicts, what was built, what was
deliberately left out per field 17, and anything in the plan that turned out to
be wrong. Update §1 and the phase's row in §4.

Report honestly. `NOT RUN` and `NOT TESTABLE AS WRITTEN` are real outcomes and
belong in the report. A criterion you did not execute is not a criterion that
passed.

**8. Commit, then stop.** Commit the work on its branch. Then **stop and
summarise.**

## The rule that matters most

**Do not start the next phase.** Not even if this one finished cleanly, not even
if the next one looks small. The handoff exists so a human reads the report and
decides whether the architecture still holds before more is built on it. That
checkpoint is the feature, not the friction.

If the phase could not be completed, say so plainly, write the blocker into §3 of
the handoff, set §1 status accordingly, and stop. A partially-finished phase
honestly reported is worth more than a phase declared done because the gates were
bent to fit.
