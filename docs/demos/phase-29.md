# Phase 29 — what the engine established, and how

The written half of the standing obligation in `docs/HANDOFF.md` §3, Q2:
each of Phases 29, 30 and 32 produces a recorded demonstration against a
real fault and a short written account of what the engine established.

**The recording is outstanding and needs a person.** Everything below is
reproducible in one command, so the recording is a matter of running it
on camera; it is not something this session could produce.

## The demonstration

```bash
cd cli && go run ./cmd/culprit check -f testdata/demo/culprit.yaml
```

`cli/testdata/demo` is a three-component system: a FastAPI orders
service, a React storefront, and a small billing service. The first two
are Phase 28's extraction fixtures, reused unmodified — they were written
to test *extraction*, not comparison, so nothing about them was arranged
to make this work. The third has two faults planted in it deliberately,
because the first two are correct and a corpus of correct fixtures cannot
show that a tool finds anything.

Nothing is running. No database, no server, no environment, no network.
The command reads files.

## What it established

Five findings, of four distinct kinds.

**1. The storefront calls a route the API does not serve.**

    http:orders-api/GET /api/v2/orders/search
      src/api/orders.ts L33 (rank 40) says the frontend calls it
      orders_api.main:app (rank 90) does not list it

The frontend's call sites are read statically from TypeScript. The
backend's route table is read by importing the application and asking it
— not by parsing Python, which dynamic route registration defeats. Two
independent sources, one subject URI, produced by two different
implementations in two different languages, and they meet. That meeting
is the entire mechanism: `calls_to: orders-api` in the manifest is what
puts the frontend's call on the backend's subject, and without it the
call would land on `http:web/...` and compare against nothing.

The direction of the finding matters. It is not "the frontend is wrong".
It is "these two disagree", with both sides, both files, both line
numbers, and both confidence ranks, so the person reading it decides
which one to change.

**2. A column the code expects and the migrations never create.**

    schema:billing-api-db/public.invoices
      main:app (rank 90):              [created_at, id, reference, total_cents]
      migrations/versions (rank 80):   [created_at, id, reference]

The models side comes from SQLAlchemy metadata after importing the app.
The migrations side comes from replaying the Alembic chain with Python's
`ast` — never by running a migration, which would need a database this
phase deliberately cannot reach.

This is the finding that would otherwise surface as a 500 in production
on the first query that selects `total_cents`, and it is visible here
before anything is deployed, in a repository with nothing installed.

**3. A config key the code reads and nothing declares.**

    config:billing-api/BILLING_WEBHOOK_SECRET
      billing/config.py L9 (rank 60) reads it
      billing/.env.example (rank 80) does not declare it
      why breaks_request_path: billing-api is an entry point, and the key is read

`os.environ["BILLING_WEBHOOK_SECRET"]` with no default, so a fresh deploy
fails at import. Contrast the two findings Culprit made about *its own*
repository during this phase: `INGEST_RATE_LIMIT` and
`INGEST_MAX_BODY_BYTES` were also read and undeclared, and were ranked
`degrades` rather than `breaks_request_path` — because the code supplies
defaults for both, so an unset key does not break a request. The
distinction is computed, from facts, deterministically.

**4. A committed spec that has drifted from the application.**

    http:orders-api/GET /api/v1/orders/{}   status_codes
      orders_api.main:app (rank 90):  ["200","422"]
      openapi.json (rank 80):         ["200","404"]

The committed `openapi.json` says the route answers 404; the running
application says 422. §2.4's confidence ranks decide which side the
report treats as the reference — runtime introspection over a committed
spec — but the losing source is never discarded. Both are printed. Rank
orders the report; it does not silently pick a winner.

## What it said it did not know

    Not checked (17) — these are gaps, not clean results
      billing-api   http_routes   no OpenAPI or Swagger document found under .
      billing-db    *             billing-db has no source root: nothing was extracted for it.
      orders-db     *             orders-db has no source root: nothing was extracted for it.
      web           http_routes   no app.get/router.post-style route definition with a literal path found
      …

This list is not filler and it is not an apology. A tool that reports
four problems and stays silent about the seventeen things it could not
look at is telling you your system is fine when it does not know.

It is also load-bearing for correctness, in a way that took a defect to
learn. Absence findings — "you call a route that does not exist" — are
only ever judged against a source that *enumerates*: a running route
table, or a committed spec. If nothing of that quality described a
component, no absence is reported for it at all, because "we did not
look" is not "it is not there". During this phase an over-broad version
of that guard silently disabled every config-key check for a component
because an unrelated reader had nothing to say, and the result looked
exactly like a clean report. The gap list is what makes that class of
failure visible instead of comfortable.

## What it could never check

    culprit check --unverifiable

against Culprit's own repository names 156 subjects that exactly one
source describes — mostly config keys that appear in `.env.example` and
nowhere else. Nothing could contradict them, so no tool of this kind
could ever catch a mistake there. That is §0.1's Tier 3, and the honest
product is a map of it rather than a claim to have solved it.

## What it found in itself

484 facts across 221 subjects on this repository, and, on the first run,
two real findings: `INGEST_RATE_LIMIT` and `INGEST_MAX_BODY_BYTES` were
read by the ingest gateway and documented only in
`infra/.env.prod.example`, never in `api/.env.example` — the file a
developer actually copies. Both were added, with a comment recording
which tool found them.

That is the smallest possible defect and it is the right size for a first
finding. It was correctly ranked `degrades`, not `breaks_request_path`,
which is the part worth trusting: the tool declined to call its own first
discovery an emergency.
