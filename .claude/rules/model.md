---
paths:
  - "shared/culprit_model/**"
  - "cli/internal/model/**"
  - "cli/internal/diverge/**"
  - "cli/internal/probe/**"
  - "extractors/**"
---

# The core model

Definitions are binding. `docs/DIAGNOSTIC_PLAN.md` §2 is authoritative; this is
the working summary.

## Planes

`INTENT` (what the system is supposed to do) · `CONFIGURED` (what an environment
is actually set up to do) · `OBSERVED` (what actually happened or was measured).

Historical baseline is a **statistic derived from `OBSERVED`**, never a plane.
Treating "usual" as a proxy for "correct" is the specific mistake this
architecture exists to fix.

## Subject URIs

The comparator only works if two independent sources describing the same thing
produce a byte-identical subject. Construction is centralised:

- Python — `shared/culprit_model/subjects.py`
- Go — `cli/internal/model/subjects.go`
- Both are covered by a **shared conformance fixture**. Change one, change both.

**Never format a subject URI as a string anywhere else.** Path templating
normalisation (`/orders/{id}` ≡ `/orders/:id`) is the highest-risk code in the
extraction layer and gets exhaustive table-driven tests.

## Intent conflicts are findings

Sources carry a `confidence_rank` (§2.4). Rank orders reports and picks a default
for comparison. **Rank never silently discards the losing source.** Two `INTENT`
facts that disagree emit an `intent_conflict` divergence — that disagreement is
usually itself the bug, detectable before deployment.

## Probes

Four verdicts: `pass`, `fail`, `inconclusive`, `refused`. The last two are honest
answers and must appear in reports. `inconclusive` means the probe ran and could
not establish the answer; `refused` means the capability was not granted. **A
probe that cannot admit uncertainty is a probe that guesses** — every probe needs
a test fixture for its `inconclusive` case.

`effect: mutate` fails manifest validation. No `*.write` capability exists.
Adding one requires its own plan document, not a phase.

## Extraction

Source preference order is a hard rule, not a heuristic:

1. Machine-readable declarations that already exist (OpenAPI, migrations,
   lockfiles, manifests).
2. Runtime introspection of the application (`app.openapi()`), because dynamic
   route registration defeats static parsing in most frameworks.
3. Thin language-specific extraction, only for what the first two cannot give —
   chiefly client call sites. tree-sitter queries, not type-aware analysis.

An extractor that cannot answer emits `skipped` with a reason and exits zero. It
never fails the run and never guesses.

## Config values

Facts, readings, reports and captures carry config **names and shapes**, never
values, unless an explicit per-key grant applies. A capture bundle must be safe
to attach to a bug report by construction, and there is a test asserting it.
