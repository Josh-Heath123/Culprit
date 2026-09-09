---
name: limits
description: Update docs/LIMITS.md with the honest constraints introduced by the work just completed. Use at the end of every phase, and whenever a change adds a threshold, a ceiling, a heuristic or a failure mode a user could hit.
---

Update `docs/LIMITS.md` for the work on this branch.

Current limits document:

@docs/LIMITS.md

Changes on this branch:

!`git diff --ignore-space-at-eol --stat origin/main...HEAD`

## What belongs in LIMITS.md

A limit is anything a user could hit that would make Culprit wrong, silent, or
slower than expected, and that they could not have predicted from the README:

- Fixed thresholds and constants (a z-score cutoff, a lookback window, a top-k
  with no relevance floor, a warm-up count).
- Heuristics stated as heuristics — what a substring match or a time window will
  and will not catch.
- Scale ceilings — connection pools, request rates, table growth, retention.
- Coverage gaps — what a probe returns `inconclusive` for, what an extractor
  cannot see, which fault classes are structurally undetectable.
- Anything where "it correctly shows nothing" could be mistaken for "it is
  broken".

## Rules

- Write it the way the existing document is written: honest, specific, and in the
  user's terms. "A product that states its limits is more trustworthy than one
  that implies it has none" is that file's own framing — keep it.
- State the *number*, not "configurable". A reader wants to know what it is set
  to, then that it can be changed.
- If this branch introduced no user-visible limit, say so and change nothing. An
  invented limit is worse than a missing one.
- `docs/DIAGNOSTIC_PLAN.md` §3 makes this obligatory per phase — the Phase 23
  linking heuristic was built without it and stayed undocumented for months.
