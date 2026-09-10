# The fault corpus — the eval suite

Phase 29 field 13: "Every fault class gets a fixture in the corpus with
an expected divergence set — this is the beginning of the eval suite.
False-positive rate is tracked as an explicit metric per fixture and
reported in CI; a fixture whose false-positive count rises fails the
build."

Each directory is one fixture:

| File | What it is |
|---|---|
| `culprit.yaml` | the system model, including any `invariants:` / `suppress:` / `severity_overrides:` the fixture is about |
| `bundle.json` | the facts extraction would have produced |
| `expected.json` | the **exact** divergence set that must come out, plus a `false_positives` baseline |

`cli/internal/check/eval_test.go` runs them.

## The assertion is exact, in both directions

A missing expected finding fails. So does an unexpected one. The second
half is the one that matters: field 13 asks for the false-positive rate
to be tracked, and a corpus that only checked for the findings it wanted
would let the tool grow noisier indefinitely without a single test going
red. Noise is how a CI tool dies — it gets its threshold turned down
once, and then it is never turned back up.

**Do not raise a `false_positives` baseline to make a test pass.** Every
one is `0` and is meant to stay there. If a fixture starts producing a
finding it does not document, either the comparator got something wrong
or the fixture is a legitimate example of a fault it does not describe —
and if it is the second, say so in `expected.json`.

## Why the bundles are committed rather than extracted

These fixtures evaluate the **divergence engine** — comparison, severity,
suppression, invariants — given facts. They do not evaluate extraction.

Extraction has its own corpus: `cli/testdata/fixtures/` with golden
capture bundles (Phase 28), plus the Python and Node extractors' own test
suites. And `cli/testdata/demo/` joins the two, running the whole
pipeline over real source trees through the real extractors.

Splitting them this way keeps these hermetic and fast enough to run on
every commit, which a corpus needing `uv` and `npx` per fixture would not
be. The cost is written down in `docs/LIMITS.md`: if an extractor changes
what it emits, these bundles go stale silently. They are written to match
what the real extractors actually produce — same predicates, same
confidence ranks, same provenance shape — so check that when you add one.

## The fixtures

| Fixture | What it pins down |
|---|---|
| `route-not-exposed` | criterion 1: a call site against a route table that does not list it |
| `column-not-migrated` | criterion 2: the ORM and the migration chain disagreeing about columns — note both sides come from the *same extractor*, which is why the duplicate guard keys on the artefact too |
| `config-key-undeclared` | criterion 3: a key read in code and absent from `.env.example` |
| `openapi-drift` | criterion 4: a committed spec against the running route table |
| `clean` | criterion 6, the most important one: everything agrees, and it must stay empty |
| `skip-blocks-absence` | "we did not look" is not "it is not there" — a call site with no authoritative route table produces nothing |
| `suppressed` | a finding silenced by `culprit.yaml`, still present and still carrying its reason |
| `severity-overridden` | `severity_overrides:` — the escape hatch for a key the graph rules cosmetic and the manifest knows is not |
| `invariant-broken` | a rank-100 developer assertion the system stopped meeting — and, by the two findings it must *not* produce, that an assertion is never a component's reference set |
