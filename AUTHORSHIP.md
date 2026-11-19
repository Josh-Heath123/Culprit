# Authorship

How Culprit is made, stated as facts, each with a pointer to the record
that shows it. This file draws no legal conclusion and is not legal advice.
Counts are as of `main` at `3928f0a` (2026-11-19); the commands that give
them are shown, so they can be checked and brought up to date.

## Who directs it

**Joshua Heath** directs the work, decides it, reviews it and merges it.

- **Decisions.** The plans record what is built and why, phase by phase, and
  the rulings at each review: [`docs/DELIVERY_PLAN.md`](docs/DELIVERY_PLAN.md),
  [`docs/PERFORMANCE_PLAN.md`](docs/PERFORMANCE_PLAN.md),
  [`docs/DIAGNOSTIC_PLAN.md`](docs/DIAGNOSTIC_PLAN.md) and the earlier plans
  they link to. Decisions the owner made directly are recorded with their
  date, for example the name of record (`docs/DELIVERY_PLAN.md`, Phase 41,
  "Review") and pausing deploy (`docs/HANDOFF.md` §1, 2026-11-05).
- **Review and merge.** Every change reaches `main` through a pull request
  that the owner merges after review ([`docs/HANDOFF.md`](docs/HANDOFF.md),
  the protocol at its top: the coding agent commits and opens the pull
  request; only the human merges). All 51 merged pull requests were merged by
  `Josh-Heath123`: `gh pr list --state merged --json mergedBy`.
- **Commits.** `main`'s 308 commits since the first, on 2026-08-02, are
  authored as `Josh-Heath123` (233) or Joshua Heath (75), both the owner:
  `git log --format=%an main | sort | uniq -c`.

## How it is made

Much of the code and many of the documents were written by Claude, an AI
model made by Anthropic, working under the owner's direction in two places:

- **Claude Code,** an agent that implements one phase at a time from a brief,
  runs the gates, commits on the phase's branch and opens the pull request
  ([`.claude/skills/`](.claude/skills), [`CLAUDE.md`](CLAUDE.md)).
- **An architecture session,** in which the plans and each phase's brief are
  written and each phase is reviewed before the next begins.

The pointers:

- **Commit trailers.** 109 of `main`'s 308 commits carry a `Co-Authored-By:
  Claude` trailer: `git log --format='%(trailers:key=Co-Authored-By)' main`.
  A commit without the trailer may still contain text Claude wrote; the
  trailer records that a commit was made with Claude, not the share of it.
- **The briefs and reports.** Each phase's brief, written in the architecture
  session, and Claude Code's run report against it, are in the plans and in
  the history of `docs/HANDOFF.md` §5 (`git log -p docs/HANDOFF.md`).
- **The pull requests** the owner merged, each with its run report:
  `gh pr list --state merged`.

## What the model's provider says about outputs

Anthropic's Consumer Terms of Service, effective 8 October 2025, section 4
("Inputs, Outputs, Actions, and Materials"), say that Anthropic assigns to
the user all of its right, title and interest, if any, in Outputs, subject to
the user's compliance with the Terms
(<https://www.anthropic.com/legal/consumer-terms>, read 2026-11-19). That
is a paraphrase; the terms themselves govern, and they may change.

## Where the law decides

Whether, and how far, copyright subsists in work made with an AI model
depends on the law of the place where it is claimed. Two examples:

- **United States.** The US Copyright Office's report *Copyright and
  Artificial Intelligence, Part 2: Copyrightability* (29 January 2025)
  discusses when material generated with AI is protected
  (<https://www.copyright.gov/ai/Copyright-and-Artificial-Intelligence-Part-2-Copyrightability-Report.pdf>).
- **South Africa.** The Copyright Act 98 of 1978, section 1(1), defines the
  author of a computer program as "the person who exercised control over the
  making of the computer program"
  (<https://www.wipo.int/wipolex/en/text/474815>, the Act as amended to 2002).

This file states what the record shows. It does not say what follows from
it in any jurisdiction, and it is not legal advice.

## See also

[`NOTICE`](NOTICE) (the copyright holder and third-party material),
[`LICENSING.md`](LICENSING.md) (which licence covers which path),
[`CONTRIBUTING.md`](CONTRIBUTING.md) and [`TRADEMARKS.md`](TRADEMARKS.md).
