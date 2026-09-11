---
name: ci
description: Verify CI is green on the merge result, for this exact commit. Push, watch the run pinned to its SHA, assert its conclusion, and triage any failure. Use before reporting any phase complete and before merging.
argument-hint: "[branch]"
---

Establish whether this work actually passes, on the tree that will actually be
merged, in the run that actually belongs to this commit.

Current position:

!`git branch --show-current`
!`git log --oneline -1`
!`git log --oneline -1 origin/main`

## Procedure

**1. Test the merge result, not the branch.** Every phase branch is cut from a
`main` that then moves underneath it, so the tree the gates ran against is not
the tree that gets merged.

```
git fetch origin
git merge origin/main
```

If that conflicts, resolve it and say so — a conflict means the branch and `main`
disagree about something worth a sentence.

**2. Re-run the local gates on the merged tree.** `/verify`. Green before the
merge does not carry over.

**3. Push, then watch the run for THIS commit.** Never `gh run watch` bare — with
no run id it attaches to the most recent run, and there is a registration delay
after a push, so it will happily watch the *previous* run and report its result
as yours. Pin to the SHA:

```bash
git push -u origin HEAD
SHA=$(git rev-parse HEAD)

# Wait for the run for this commit to be registered (up to ~60s).
for i in $(seq 1 20); do
  RUN=$(gh run list --commit "$SHA" --limit 1 --json databaseId -q '.[0].databaseId')
  [ -n "$RUN" ] && break
  sleep 3
done
[ -n "$RUN" ] || { echo "No run registered for $SHA"; exit 1; }

gh run watch "$RUN" --exit-status
```

**4. Assert the conclusion. Do not infer it.** `--exit-status` alone is not
enough — read the run back and read every job:

```bash
gh run view "$RUN" --json conclusion,url,headSha \
  -q '"conclusion=\(.conclusion)  sha=\(.headSha)  \(.url)"'
gh run view "$RUN" --json jobs \
  -q '.jobs[] | "\(.conclusion)\t\(.name)"'
```

A job can log `Error:` annotations and still conclude `success`, and a run can
conclude `failure` on a job you were not looking at. Only `conclusion=success`
on the run, with no job concluding anything other than `success` or `skipped`,
is green.

**5. If red, triage before touching anything.**

```bash
gh run view "$RUN" --log-failed
```

Hand it to the `test-triage` agent rather than reading the whole log here. Check
these first — they are this repository's actual failure classes, all invisible
to local gates:

- **Line endings.** No `.gitattributes`, `core.autocrlf` unset. A file that
  passes on Windows can fail on Linux.
- **A clean checkout.** No venvs, no `node_modules`, no
  `api-types.generated.ts`. Anything generated at build time is absent, and a
  step that silently depended on it fails.
- **`origin/main` as a moving base.** `check_coupled_files.py --base origin/main`
  compares against a different commit than it did locally.
- **Base-image CVEs.** Trivy fails on new CVEs in `caddy:2-alpine` on a schedule
  nobody controls. A CVE in code we control is a defect in the change; a CVE in
  a pinned base image is a maintenance task. Do not conflate them.
- **Linux vs Windows.** Case-sensitive paths, separators, file modes.

**6. Never make CI green by weakening it.** No removed job, no lowered Trivy
severity, no `continue-on-error` on a gate, no skipped matrix entry. If that
looks like the only route, it is an escalation to §6 of the handoff.

## Output

Report, in this order and always:

```
commit   <sha>
run      <id>  <url>
```

Then one line per job: conclusion and name. Then the verdict. Then whether what
you tested was the **merge result** or the branch alone, stated explicitly.

**An unattributed "green" is not a result.** If the report does not name the
commit and the run it came from, it cannot be checked, and a check that cannot
be checked is the thing this whole project exists to stop shipping.
