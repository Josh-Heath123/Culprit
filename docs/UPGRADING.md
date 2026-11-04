# Upgrading a running install

For a real-VM install (`docs/INSTALL.md`) or self-managed Docker Compose
deployment. The local quickstart (`just quickstart`) mostly doesn't need
this — tear it down and re-run it instead — **except** that re-running reuses
an existing `infra/.env.prod`, so one generated before a phase that added a
database role is missing that role's password and the bootstrap migration
refuses to run. `docs/LIMITS.md` ("Every service now refuses to start without
its database URL") says what to do.

## The order, and why it's fixed

Always: **pull the new images, run migrations, then restart containers.**
This is exactly what `infra/deploy.sh` does automatically on every push to
`main`, and it's the same order for a manual upgrade:

```bash
cd ~/culprit
docker compose -f docker-compose.prod.yml --env-file .env.prod pull
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm api alembic upgrade head
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --remove-orphans
```

Migrating before restarting means the containers are never running code
that expects a schema the database doesn't have yet — restarting first
would have the new API/worker images querying columns that don't exist.
Never restart without migrating first, even if you're fairly sure "this
release didn't touch the schema" — confirm by checking whether
`api/migrations/versions/` gained new files between your current version
and the one you're upgrading to, not by assuming.

## A release that adds a Postgres role needs a new secret first

Every migration that creates a role reads its password from the
environment and **raises rather than defaulting** — so `alembic upgrade
head` fails outright if `infra/.env.prod` does not have it. That is
deliberate (a fail-open default here would provision a least-privilege
role with a committed password), but it means the upgrade order above has
a step before it whenever a release adds one:

`infra/deploy.sh` only copies `docker-compose.prod.yml` and `deploy.sh`
to the VM, so `.env.prod.example` is not there to compare against — fetch
it from the release you are upgrading to:

```bash
cd ~/culprit
curl -fsSL -o /tmp/env.example   https://raw.githubusercontent.com/Josh-Heath123/Culprit/vX.Y.Z/infra/.env.prod.example
diff <(grep -oE '^[A-Z_]+=' .env.prod | sort)      <(grep -oE '^[A-Z_]+=' /tmp/env.example | sort)
```

Add any missing key with a freshly generated value before running
migrations. If you skip it, the migration stops with
`<NAME> must be set in the environment to run this migration` and nothing
has changed — a safe failure, but one that halts the upgrade midway.

**Phase 28 adds two:**

```
FACT_WRITER_DB_PASSWORD=<generate one>
FACT_WRITER_DATABASE_URL=postgresql+asyncpg://fact-writer:<same password>@postgres:5432/culprit
CULPRIT_PROJECT_TOKEN=<generate one, or leave unset>
```

`FACT_WRITER_DB_PASSWORD` is required — the migration will not run
without it. `CULPRIT_PROJECT_TOKEN` is optional and **unset means
`POST /facts/captures` refuses every request**, which is the correct
default for an install that is not uploading captures.

**Phase 30 adds two more:**

```
CAPTURE_WRITER_DB_PASSWORD=<generate one>
CAPTURE_WRITER_DATABASE_URL=postgresql+asyncpg://capture-writer:<same password>@postgres:5432/culprit
```

Both required: the migration creating the `capture-writer` role will not
run without the password, and the api will not start without the URL.
`POST /captures` authenticates with the same `CULPRIT_PROJECT_TOKEN` as
`POST /facts/captures`, so unset still means it refuses every request.

**Phase 31 adds two more:**

```
PROBE_WRITER_DB_PASSWORD=<generate one>
PROBE_WRITER_DATABASE_URL=postgresql+asyncpg://probe-writer:<same password>@postgres:5432/culprit
```

Both required, and the URL is read by **two** processes, not one: the api
(for `POST /readings`) and the worker (whose anomaly job now emits an
impedance reading beside each score). Neither starts without it, and the
migration creating the `probe-writer` role will not run without the
password. `POST /readings` authenticates with the same
`CULPRIT_PROJECT_TOKEN`, so unset still means it refuses every request.

**Phase 32 adds two more:**

```
INVESTIGATION_WRITER_DB_PASSWORD=<generate one>
INVESTIGATION_WRITER_DATABASE_URL=postgresql+asyncpg://investigation-writer:<same password>@postgres:5432/culprit
```

Both required: the migration creating the `investigation-writer` role will
not run without the password, and the api will not start without the URL.
`POST /investigations` authenticates with the same `CULPRIT_PROJECT_TOKEN`.

The same migration makes `incident_candidates` and `incident_anomalies`
read-only, and the worker no longer runs the correlation engine or the
narrative job: an upgraded install keeps its incidents as history, and new
diagnoses arrive as investigations from `culprit diagnose`.

## Picking a version

Pin `IMAGE_TAG` in `infra/.env.prod` to a specific release
(`IMAGE_TAG=v0.2.0`), not `latest`. `latest` always points at the most
recent push to `main`, which can be ahead of any tagged release and can
change under you on a routine `docker compose pull` — a third-party
install silently jumping to whatever landed on `main` five minutes ago is
a bad default, even though it's convenient for continuous deployment of
the author's own VM (which is what `docker-compose.prod.yml`'s own
default `IMAGE_TAG=latest` fallback is for). Released versions are tagged
`vX.Y.Z` and published to `ghcr.io/josh-heath123/culprit/{api,worker,frontend}` —
see the repository's Releases/tags for what's available.

## Back up first

Always, before running the migration step above:

```bash
scripts/backup.sh
```

Dumps the whole database — simpler than trying to selectively exclude
tables, and cheap enough at this project's scale that there's no reason
to. But not every table matters equally if you ever need to actually
restore from one:

- **Disposable:** `raw_events` — the highest-volume table by far
  (`docs/LIMITS.md`), and the one thing in this database that regenerates
  itself the moment ingestion resumes. Losing recent history here is a
  gap in the timeline, not data you can't get back some other way.
- **Irreplaceable:** `postmortems`, `services`, `service_dependencies`,
  `users`, `incident_candidates` (and its `incident_anomalies` join
  table), `api_keys`. This is the corpus that actually matters — your
  team's postmortem history, who's registered to talk to this install and
  with what key, who can log in, and the incident record itself. None of
  it can be regenerated; a backup exists to protect this part.

A migration that turns out to be wrong is far cheaper to recover from
with a backup than without one, even though most migrations in this
project are additive and low-risk.

## Restoring a backup

```bash
gunzip -c backups/culprit-<timestamp>.sql.gz | docker compose \
  -f docker-compose.prod.yml --env-file .env.prod exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

**Restore into a database that has already had `alembic upgrade head` run
against it, not a bare, freshly-created Postgres instance.** The dump
includes `GRANT`/`OWNER TO` statements for this project's own DB roles
(`ingestion-writer`, `api-reader`, `postmortem-writer`, and so on) —
those roles only exist once the migrations that create them have run, so
restoring into a database that's never been migrated prints a page of
`ERROR: role "..." does not exist`. Verified directly: the actual table
data still restores correctly even with those errors present (`psql`
keeps going past individual statement failures), but they're confusing
enough on a real disaster-recovery night that they're worth avoiding —
bring the target database up to the same schema version first
(`docker compose run --rm api alembic upgrade head` against an otherwise
empty database creates the roles and tables with no data in them, then
the restore populates them), rather than restoring into a completely
untouched Postgres.

Restoring into a database that already has data in it will conflict on
existing rows — restore into a fresh (but migrated) database, not over a
live one, unless you've already torn the live one down first.

## Downgrading

Supported one version back, no further. If an upgrade goes wrong:

1. Restore the database backup taken before you upgraded (a migration's
   own `downgrade()` reverses schema changes, but doesn't undo data
   changes a newer version may have written under the new schema — a
   restored backup is the only fully reliable path back).
2. Point `IMAGE_TAG` in `.env.prod` back at the previous version.
3. `docker compose -f docker-compose.prod.yml --env-file .env.prod pull`
   then `up -d --remove-orphans` — no `alembic downgrade` needed if you
   restored the backup, since that already put the schema back too.

Going back more than one version is unsupported: migrations aren't
tested for a multi-version downgrade path, and the older the target
version, the more likely a `downgrade()` from several releases ago
depends on schema state that no longer matches what's actually running.
If you're more than one version behind, upgrade forward one version at a
time instead of trying to skip ahead and back out.
