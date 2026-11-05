# Claude Code setup for this repository

What is configured, why each piece earns its place, and the steps a human still
has to do. Written 2026-09-08 against `docs/DIAGNOSTIC_PLAN.md`.

The governing idea: this repository is building an instrument that replaces
guessing with evidence. The development environment should work the same way —
Claude does not get to say "I've implemented it", it gets to show that the gates
passed.

---

## 1. What is already configured

| Path | What it does |
|---|---|
| `.claude/rules/determinism.md` | The LLM boundary. Loads only when working in `worker/app/`, `cli/internal/`, `mcp_server/`, `shared/culprit_model/`, `scripts/check_*.py`. |
| `.claude/rules/database.md` | Role least-privilege, schema parity, migration symmetry. Loads on `api/migrations/`, `api/app/db/`, `worker/app/db.py`. |
| `.claude/rules/model.md` | Planes, subject URIs, probe verdicts, extraction preference order. Loads on `shared/culprit_model/`, `cli/`, `extractors/`. |
| `.claude/agents/invariant-auditor.md` | Audits a diff against this repo's enforced invariants. Not a general code reviewer. |
| `.claude/agents/phase-auditor.md` | Executes a phase's acceptance criteria rather than reading the code. |
| `.claude/agents/test-triage.md` | Isolates a failure and returns the cause — keeps pytest output out of the main context. |
| `.claude/skills/phase/SKILL.md` | `/phase 26` — execute exactly one phase of the plan, respecting its "do not build yet" list. |
| `.claude/skills/verify/SKILL.md` | `/verify` — run every gate, report honestly, never infer a pass. |
| `.claude/skills/audit/SKILL.md` | `/audit` — dispatch the two auditor agents on the current branch. |
| `.claude/skills/limits/SKILL.md` | `/limits` — update `docs/LIMITS.md`, which the plan makes obligatory per phase. |
| `.claude/hooks/fast_gates.sh` | `Stop` hook. Runs ruff on changed files, coupled-files, migration symmetry. Exits 2 on failure so Claude must fix before finishing. |
| `.claude/settings.json` | Permissions (allow / ask / deny) plus the three hooks. |
| `.mcp.json` | Registers this repo's **own** MCP server so a session can query engineering memory and file history. |

`.claude/hooks/capture_ai_change.sh` and `check_invariants.sh` already existed and
are unchanged.

---

## 2. Steps you have to do

**1. Make the new hook executable and keep the bit in git.**

```bash
chmod +x .claude/hooks/fast_gates.sh
git update-index --chmod=+x .claude/hooks/fast_gates.sh
```

**2. Export the MCP server's environment variables in your shell profile — not in
the repo.** `.mcp.json` expands `${VAR}` from the environment, which is why no
secret is committed.

```bash
# ~/.bashrc, ~/.zshrc, or your Windows environment variables
export MCP_READER_DATABASE_URL="postgresql+asyncpg://mcp-reader:<password>@localhost:5432/culprit"
export VOYAGE_API_KEY="<key>"          # optional; only culprit_search_memory needs it
```

The password is in `infra/.env` under `MCP_READER_DB_PASSWORD`. If it is not
there, `just bootstrap-env` generates it.

**3. Approve the project MCP server.** Claude Code prompts on first run in this
directory because `.mcp.json` is project-scoped and checked into git. Approve it
once. Then confirm with `/mcp` — you should see `culprit` connected with four
tools.

**4. Verify what actually loaded.** Run `/context`. Check that the three
`.claude/rules/` files, the three agents and the four skills are listed, and note
the context percentage — see §3, which is the point.

**5. Optional: a status line.** On a project this long-running, seeing branch and
context usage constantly is worth the five minutes. `/statusline` will set one up
from a description.

---

## 3. The highest-leverage thing left to do: fix `CLAUDE.md`

*Done in Phase 32.2 (2026-11-05): `CLAUDE.md` is about 5 KB; the
architecture walkthrough moved to `docs/ARCHITECTURE.md`. Kept below as the
reasoning, and as the budget to hold it to.*

This matters more than every agent and hook above combined, and it is not in any
generic Claude Code advice.

`CLAUDE.md` is 32 KB and is loaded into **every single session**, so it costs
roughly 8,000 tokens of context before you have said anything. Worse, it is
stale: its status line still reads *"Phases 0–19 merged; Phase 20 in progress"*
and it contains no reference to Phases 21–24, the MCP server, or `.claude/hooks/`
— four shipped phases invisible to the file that is supposed to be the
session-to-session source of truth. Its own stated philosophy is that a stale
status line is worse than none.

**Target: `CLAUDE.md` under 8 KB.** The mechanism is already available:

- **Path-scoped rules** — the three `.claude/rules/*.md` files load *only* when
  Claude touches matching files. Everything in `CLAUDE.md`'s "Where the AI must
  stay deterministic" section and its database notes is now duplicated there.
  Delete those sections from `CLAUDE.md` and let the rules carry them.
- **Imports** — `@docs/DIAGNOSTIC_PLAN.md` pulls a file in on demand rather than
  inlining its content. Replace the long Architecture narration with a short
  index plus imports.
- **Delete the history.** The blow-by-blow of Phases 0–19, the Trivy tag
  incident, the Let's Encrypt timing — all of it is real and all of it belongs in
  the plan documents, which are already written and already read on demand.

What should survive in `CLAUDE.md`: what the product is now (three sentences),
the current phase and branch, the scope ceilings, the commands table, the pointer
to `docs/DIAGNOSTIC_PLAN.md`, and the Windows CRLF warning — which is operational
and affects every single `git diff`.

Phase 26 of the plan already lists "bring `CLAUDE.md` current" as a deliverable.
Do it first, before writing any Phase 26 code, because every session until then
pays for the stale version.

---

## 4. Where this differs from the generic advice

Four deliberate departures, each with a reason:

**Three agents, not six.** Six agents whose descriptions all sound plausible
means Claude picks the wrong one, and "architect" versus "backend-engineer"
versus "code-reviewer" are not distinguishable by *trigger condition* — only by
job title. The three here fire on genuinely different events: a diff is ready
(`invariant-auditor`), a phase claims to be complete (`phase-auditor`), something
failed (`test-triage`). Add a fourth only when you can state the event that
triggers it and no existing agent covers it.

**Slash commands are skills now.** They live in `.claude/skills/<name>/SKILL.md`,
not `.claude/commands/*.md`. Frontmatter supports `argument-hint`, `allowed-tools`,
`model`, `context: fork` and more; `$1`/`$ARGUMENTS` for arguments, `` !`cmd` ``
to inline shell output, `@file` to pull a file in. The `/phase` skill uses all of
these.

**MCP is Tier 3 here, not Tier 1 — with one exception.** Connecting Claude to
GitHub, Postgres and Docker sounds powerful, but for *building* Culprit the `gh`
and `docker` CLIs through `Bash` already reach all of it, with no extra server to
run and no extra context spent on tool definitions. The `gh run` and `gh api`
allows in `settings.json` cover CI triage. The exception, and the reason
`.mcp.json` exists at all, is **this repo's own MCP server** — `culprit_file_history`
answers "has this file caused a problem before" from recorded history, which no
CLI can. That is the one MCP server that earns its place today.

**The `Stop` hook runs fast gates only.** Running pytest on every turn is how a
hook setup gets disabled within a week. `fast_gates.sh` targets under five
seconds — ruff on changed files, coupled-files, migration symmetry. Everything
slower (pytest, pyright, `check_schema_drift`, which shells out to two separate
uv venvs) lives in `/verify`, invoked deliberately. The hook also blocks at most
twice per session, so a check that can never pass cannot trap you.

---

## 5. The loop this is building toward

The hook layer today is the *shape* of the thing, not the thing:

```
Claude edits code
      ↓
check_invariants.sh   →  coupled files, migration symmetry
      ↓
Claude finishes turn
      ↓
fast_gates.sh         →  ruff, coupled files, migration symmetry
      ↓
   FAIL → exit 2, Claude must fix before it can stop
   PASS → turn ends
```

**At Phase 29, this closes for real.** Once `culprit check` exists, add it to
`fast_gates.sh` and run it against this repository:

```bash
culprit check --fail-on=breaks_request_path
```

At that point Claude's "I think this works" is adjudicated by the instrument
being built, on the instrument's own source. That is the strongest possible
dogfooding, it is a genuine continuous eval, and it costs one line in a hook.

Two things worth knowing while working this way: `/rewind` (or Esc twice on an
empty prompt) restores code and conversation to any prior checkpoint, which makes
aggressive changes cheap to undo; and `/context` shows exactly what is consuming
your window, which is how you notice `CLAUDE.md` regrowing.
