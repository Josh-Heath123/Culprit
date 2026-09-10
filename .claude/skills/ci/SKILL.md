---
name: ci
description: Verify CI is green on the merge result, not just the branch. Push, watch the run, and triage any failure. Use before reporting any phase complete and before merging.
argument-hint: "[branch]"
---

Establish whether this work actually passes, on the tree that will actually be
merged.

Current position:

!`git branch --show-current`
!`git log --oneline -1`
!`git log --oneline -1 origin/main`

## Procedure

**1. Test the merge result, not the branch.** This is the step that has been
missing. Every phase branch is cut from a `main` that then moves underneath it,
so the tree the gates ran against is not the tree that gets merged.

```
git fetch origin
git merge origin/main          # on the phase branch
```

If that conflicts, resolve it and say so in the report — a conflict means the
branch and `main` disagree about something, which is worth a sentence.

**2. Re-run the local gates on the merged tree.** `/verify`. Green before the
merge does not carry over.

**3. Push and watch.**

```
git push -u origin HEAD
gh run watch --exit-status
```

**4. If CI is red, triage before touching anything.** Get the failing job and
its log:

```
gh run view --log-failed
```

Then hand it to the `test-triage` agent rather than reading the whole log into
this session.

Check these first — they are the failure classes this repository actually has,
and all four are invisible to local gates:

- **Line endings.** No `.gitattributes`, `core.autocrlf` unset. A file that
  passes on Windows can fail on Linux. This is the single most likely cause of a
  local-green/CI-red split here.
- **A clean checkout.** CI has no venvs, no `node_modules`, no
  `api-types.generated.ts`. Anything locally present but generated at build time
  will be missing, and a step that silently depended on it fails.
- **`origin/main` as a moving base.** `check_coupled_files.py --base origin/main`
  compares against a different commit than it did locally.
- **Linux vs Windows.** Case-sensitive paths, `/` vs `\`, and file modes.

**5. Fix, re-run, repeat.** Never make CI green by removing a job, loosening a
Trivy severity, adding `continue-on-error`, or skipping a matrix entry. If that
appears to be the only route, that is an escalation to §6 of the handoff, not a
fix.

## Output

Per job: name, `PASS` / `FAIL`, and for failures the one line that identifies the
cause. Then the verdict. Then whether the merge result — not the branch — is what
you tested, stated explicitly, because that is the thing this skill exists to
guarantee.
