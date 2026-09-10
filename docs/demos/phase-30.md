# Phase 30 — "works in staging, fails in production", found before anyone is paged

The written account the architecture session asked for (docs/HANDOFF.md
§3, Q2) of what `culprit diff` established against a real fault, and
how. The recording is a person running the commands below on camera; it
is not in this repository.

## The setup

`cli/testdata/demo` is the Phase 29 demo repository — a FastAPI orders
service, a React storefront calling it, and a deliberately broken billing
service. Phase 30 adds two environments for it,
`cli/testdata/demo/environments/`: two Docker Compose projects, each an
`orders-api` container carrying the environment a real deployment would
carry, and a real Postgres whose schema is what a given Alembic revision
would have left.

Staging is correct. Production has three faults planted, each one an
acceptance criterion of the phase:

1. `JWT_SECRET_KEY` is not set. `orders_api/config.py` reads it with
   `os.environ["JWT_SECRET_KEY"]`, no default.
2. The database is at `0002_add_status`: the deploy shipped code that maps
   the `order_lines` table and nobody ran migration `0003`.
3. It runs `alpine:3.19` where staging runs `alpine:3.20` — a different
   build, with a different digest.

`culprit.yaml` grants each environment three things: the names and shapes
of its configuration (`config.read.names`), its image metadata
(`deploy.metadata.read`) and its schema metadata (`db.metadata.read`).
Not config values and not the network.

```
cd cli/testdata/demo/environments
docker compose -p culprit-demo-staging    -f compose.yml -f staging.yml    up -d --wait
docker compose -p culprit-demo-production -f compose.yml -f production.yml up -d --wait
cd ..
export CULPRIT_DEMO_STAGING_DB_URL="postgresql://orders:…@$(…port orders-db 5432)/orders?sslmode=disable"
export CULPRIT_DEMO_PRODUCTION_DB_URL="postgresql://orders:…@$(…port orders-db 5432)/orders?sslmode=disable"
culprit diff staging production
```

## What it reported

Verbatim, in about four seconds, exit code 1:

```
5 divergence(s)

  [breaks_request_path] component:orders-api
      alembic.ini and production (postgres:orders-api-db) disagree about migration_head
      ["0003_add_order_lines"]                   alembic.ini (rank 90)
      ["0002_add_status"]                        postgres:orders-api-db (in production)
      why breaks_request_path: orders-api is on the request path from web, and this is a fact about it as deployed

  [breaks_request_path] config:orders-api/JWT_SECRET_KEY
      .env.example refers to JWT_SECRET_KEY, which production (compose:orders-api) does not have
      true                                       .env.example L4 (rank 80)
      false                                      compose:orders-api (in production)
      why breaks_request_path: orders-api is on the request path from web, and the key is read

  [degrades] image:orders-api
      production (compose:orders-api) and staging (compose:orders-api) disagree about digest
      "sha256:6baf43584bcb78f2e5847d1de515f2349… compose:orders-api (in production)
      "sha256:d9e853e87e55526f6b2917df91a2115c3… compose:orders-api (in staging)
      why degrades: the two environments run different builds of orders-api

  [degrades] image:orders-api
      production (compose:orders-api) and staging (compose:orders-api) disagree about reference
      "alpine:3.19"                              compose:orders-api (in production)
      "alpine:3.20"                              compose:orders-api (in staging)
      why degrades: the two environments run different builds of orders-api

  [breaks_request_path] schema:orders-api-db/public.order_lines
      orders_api.main:app refers to public.order_lines, which production (postgres:orders-api-db) does not have
      ["id","order_id","quantity","sku"]         orders_api.main:app public.order_lines (rank 90)
      false                                      postgres:orders-api-db (in production)
      why breaks_request_path: orders-api-db backs a component on the request path


Refused (2) — not looked at, because the capability was not granted
  staging/orders-api           config values          the values of 7 key(s) were not captured — only their shape (config.read.values is not granted)
  production/orders-api        config values          the values of 6 key(s) were not captured — only their shape (config.read.values is not granted)
```

(followed by the "Not checked" list of INTENT extraction gaps, as for
`culprit check`.)

## What the engine established, and how

**Every planted fault, and nothing else.** Five findings for three faults:
the migration fault shows as both the version and the missing table, and
the image fault as both the tag and the digest it resolves to. Staging —
which differs from production in its URL lengths, its Stripe key's prefix
and a secret that happens to be longer — produced nothing, because none
of those is a fault. The corpus fixture `envdiff/clean-environments` holds
that property at zero false positives in CI.

**It is the Phase 29 comparator, unchanged in kind.** Each finding is two
facts that answer the same `(subject, predicate)` question differently,
or a fact claiming something exists against a source that enumerated
that kind of thing and does not list it. What is new is *where* the facts
come from and which pair of planes they sit on: `intent_vs_configured`
when the repository says one thing and an environment another,
`env_vs_env` when two environments differ on something the repository
says nothing about. Nothing in the comparator knows what an environment
variable, a column or an image digest is.

**Where the repository has an answer, the environment is judged against
it** — not against the other environment. "Production lacks
`JWT_SECRET_KEY`" is reported once, as production against the code;
"staging has it and production does not" would be the same fault said
worse, because it no longer says which side is wrong.

**Severity comes from the model, and says why.** `JWT_SECRET_KEY` is
`breaks_request_path` because `culprit.yaml` puts `orders-api` on the
request path from `web`, the Python extractor found the code reading the
key, and no default was found. The image findings are `degrades`:
different builds explain a great many "works in staging" reports, and
prove nothing is broken by themselves.

**What it could not see, it says.** Config values were not granted, so the
report says how many it did not read. The capture compared each key's
*shape* — the production `DATABASE_URL` is a `postgresql` connection
string with a credential in it, exactly like staging's — and never held
the value past classifying it. The end-to-end test plants the database
password, the JWT signing key and both Stripe keys in the two
environments, and searches the text, JSON, SARIF and JUnit reports, the
sealed capture envelope and its decoded payload for every one of them.

**The capture can be kept.** `culprit env capture production -o
production.capture.json` writes the same facts as a sealed envelope — the
exact bytes, their SHA-256 and optionally an Ed25519 signature — plus the
grants it ran under and what it was refused. `culprit diff staging
production.capture.json` reproduces the findings from the file; an
envelope with one byte changed is refused before a fact is read. `POST
/captures` verifies and stores the same envelope.

## Two defects the real environment found that no fixture had

- The first version read the schema through `information_schema`, which
  only lists tables the connecting role has a privilege on. A
  least-privilege capture role — the right thing to hand a tool — would
  have made every table it could not read look *missing* from production.
  It reads `pg_catalog` now, which lists every table to any role.
- `pgx` reports "permission denied" on the migration-version query after
  iteration, not when the query is issued. The first version never
  checked, so a role without `SELECT` on `alembic_version` read as "the
  database is at no revision at all" — a confident, false
  `breaks_request_path`. It now says the version was not read.

Both were found by capturing the running demo with a role holding no
privileges, and both are now in the end-to-end test.
