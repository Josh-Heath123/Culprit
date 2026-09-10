# The environment-diff corpus — Phase 30's eval suite

Same contract as `../faults/README.md`, extended to the CONFIGURED plane.
`cli/internal/check/envdiff_eval_test.go` runs every directory here.

| File | What it is |
|---|---|
| `culprit.yaml` | the system model — the same one in every fixture, so severity is comparable across them |
| `intent.json` | the INTENT facts extraction would have produced |
| `<environment>.json` | one CONFIGURED capture per environment, as `culprit env capture` writes it (the bundle, not the sealed envelope) |
| `expected.json` | the **exact** findings — subject, predicate, kind, and for a finding about one environment, which one — plus a `false_positives` baseline of `0` |

**Do not raise a baseline to make a test pass.** A finding a fixture did
not ask for is either the comparator getting something wrong, or a
legitimate fault the fixture does not document — and if it is the second,
say so in `expected.json`.

Like the Phase 29 corpus, these evaluate the comparator given facts, not
capture. Capture is covered by `internal/capture`'s recorded-output tests,
by `cmd/culprit/diff_e2e_test.go` against real Compose projects, and by
`internal/capture/kind_test.go` against a real cluster. The bundles here
are written to match what those produce — same predicates, same
`grant_ref` on every CONFIGURED fact, same provenance shape.

| Fixture | What it pins down |
|---|---|
| `missing-required-key` | criterion 1: a key the code reads with no default, unset in production, on the request path — `breaks_request_path` |
| `live-ddl-behind-head` | criterion 2: production's database behind the migration head, missing a table the code maps |
| `image-digest-mismatch` | criterion 3: one tag, two digests |
| `clean-environments` | the one that matters: two correct environments that differ in URL length, in a secret read by reference, and in variables the code never mentions — and must produce nothing |
| `incomplete-enumeration` | a capture that could not see all of an environment never proves a key is missing from it |
| `scheme-mismatch` | Q7's own example: a `postgresql` URL against a `mysql` one |
| `unreferenced-key-differs` | a key set in one environment only, that nothing reads — reported, and `cosmetic` |
