---
name: ci
description: Verify CI is green on the merge result, for this exact commit. Push, watch the run pinned to its SHA, assert its conclusion, then gate on every check on the pull request (including Code scanning results) and on no open code-scanning alert, and triage any failure. Use before reporting any phase complete and before merging.
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
conclude `failure` on a job you were not looking at. A run with
`conclusion=success` and every job `success` or `skipped` is necessary — and
still not green. Step 4b is the gate.

**4b. Gate on the pull request, not on workflow runs.** Workflow runs are not
the only checks on a PR. GitHub posts others — "Code scanning results / CodeQL"
above all — that no `gh run` command lists. The CodeQL *workflow* concluding
`success` only means the analyses ran; the alerts they found fail a separate
check (PR #28: every run green, PR blocked by one high alert). Wait for every
check, then read them all:

```bash
PR=$(gh pr view --json number -q .number)   # no PR yet -> open it first
gh pr checks "$PR" --watch --interval 15 >/dev/null   # wait; exit code ignored
gh pr checks "$PR" --json name,bucket,link \
  -q '.[] | "\(.bucket)\t\(.name)\t\(.link)"'
```

Every check's `bucket` must be `pass` or `skipping`. `fail`, `pending` or
`cancel` on any one of them is red.

Then no code-scanning alert may be open on the pull request. Query by PR
**and** by both refs: CodeQL default setup analyses `refs/pull/<n>/head`, so a
query on the merge ref alone returns `[]` while the PR is blocked (PR #28,
2026-11-10). An alert that already exists on `main` still counts when the PR's
check fails on it.

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
for q in "pr=$PR" "ref=refs/pull/$PR/merge" "ref=refs/pull/$PR/head"; do
  gh api "repos/$REPO/code-scanning/alerts?$q&state=open&per_page=100" \
    -q ".[] | \"open alert #\(.number)  \(.rule.id)  \(.rule.security_severity_level // .rule.severity)  \(.most_recent_instance.location.path):\(.most_recent_instance.location.start_line)  ($q)\""
done
```

Any line printed is red. If the API call itself fails (no code scanning, no
permission), the result is `NOT RUN`, not pass.

**Green** = step 4 holds, every PR check is `pass`/`skipping`, and the three
alert queries print nothing. Anything less is not green, however the runs
concluded.

An open alert is never cleared from here: no dismissal, no `# lgtm`/`codeql`
suppression comment, no query-suite or severity change. Either fix the defect
with a test that reproduces it, or write the false-positive argument into the
handoff (§5 and a blocking §3 question) and stop. Dismissing is the
architecture session's decision.

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

Then one line per job: conclusion and name. Then one line per PR check from
`gh pr checks`: bucket and name. Then the open code-scanning alerts, or
`none` with the three queries that returned empty. Then the verdict. Then
whether what you tested was the **merge result** or the branch alone, stated
explicitly.

**An unattributed "green" is not a result.** If the report does not name the
commit and the run it came from, it cannot be checked, and a check that cannot
be checked is the thing this whole project exists to stop shipping.
