---
name: audit
description: Audit the current branch's changes against Culprit's enforced architectural invariants before merging. Use when a branch is ready, or when a change touched worker/app/, api/migrations/, cli/, or shared/.
---

Audit the current diff.

Changes on this branch:

!`git diff --ignore-space-at-eol --stat origin/main...HEAD`

Invoke the `invariant-auditor` agent on this diff. Give it the branch name and
the phase number if this branch implements one.

When it reports back:

- Present its verdict and violations unchanged. Do not soften them.
- For each violation, decide whether to fix now or record it. Fix anything that
  breaks an invariant. Record anything that is a risk rather than a violation.
- If it reports `CLEAN`, say so plainly and move on — do not manufacture
  findings to look thorough.

If the branch implements a phase of `docs/DIAGNOSTIC_PLAN.md`, also invoke the
`phase-auditor` agent. The two are complementary: `invariant-auditor` asks
whether the change is *allowed*, `phase-auditor` asks whether the phase is
*finished*.
