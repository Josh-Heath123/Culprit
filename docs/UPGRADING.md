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
This is exactly what `infra/deploy.sh` does when the `deploy` job is started
by hand (`docs/INSTALL.md` step 6 — it no longer runs on a push), and it's
the same order for a manual upgrade:

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

**Phase 32.1** adds no secret, but the `culprit` binary now refuses a
connection `kind` outside the closed set (`http`, `grpc`, `sql`, `message`,
`cache`, `dns`, `auth`) when it loads `culprit.yaml`, as the control plane
already did. A file that says `kind: queue` (or any other kind) for a
connection made `culprit check` and `culprit diagnose` load it and then skip
that edge; it now exits 2 naming the edge. Change `queue` to `message`.

**Phase 33** renames the grant `culprit diagnose` needs to inspect a bearer
token. `probe.auth.token_shape` used to read the token under
`config.read.values`; it now needs `config.inspect.values` for that exact
key, and `config.read.values` no longer counts — storing a value and
inspecting one are different permissions (`docs/PERMISSIONS.md`). An
environment written for the older binary, such as

```yaml
grants:
  config.read.values: [order-service/INVENTORY_TOKEN]
```

still loads, but the audience hypothesis is now refused and the diagnosis
is partial, naming `config.inspect.values`. Rename the grant:

```yaml
grants:
  config.inspect.values: [order-service/INVENTORY_TOKEN]
```

Keep `config.read.values` for that key only if you also want
`culprit env capture` to store the token's value, which you almost
certainly do not.

**Phase 33 part 2 adds six more**, for the three agent roles:

```
AGENT_ADMIN_DB_PASSWORD=<generate one>
AGENT_ADMIN_DATABASE_URL=postgresql+asyncpg://agent-admin:<same password>@postgres:5432/culprit
AGENT_REGISTRAR_DB_PASSWORD=<generate one>
AGENT_REGISTRAR_DATABASE_URL=postgresql+asyncpg://agent-registrar:<same password>@postgres:5432/culprit
AGENT_GATEWAY_DB_PASSWORD=<generate one>
AGENT_GATEWAY_DATABASE_URL=postgresql+asyncpg://agent-gateway:<same password>@postgres:5432/culprit
```

All required: the migration creating the roles will not run without the
passwords, and the api will not start without the URLs.

**`POST /readings` no longer accepts the project token.** It takes an
agent's signed request and nothing else (`docs/PERMISSIONS.md`). A CI job
or script that posted readings with `CULPRIT_PROJECT_TOKEN` now gets `401`;
run those probes through a paired agent instead. The project token keeps
the three capture endpoints and `POST /investigations`, where it is now
recorded as the submitter.

**Phase 33 part 3 adds no secret.** Its migration (`e5b8a2d4c6f1`) gives
`api-reader` SELECT on `agent_nonces`, for the agents screen's "last signed
request", and creates no role. Three changes can still stop something that
worked:

- **An agent refuses a plain-`http` control plane.** A configuration whose
  `control_plane.url` is `http://` to anything but a loopback address no
  longer loads; `culprit agent` stops at start, naming the line. Move the
  control plane behind `https` (the production compose's Caddy does it for
  a real domain). If the path is truly yours and has no certificate, set
  `allow_plain_http: true` under `control_plane:`; the agent then says so at
  every start.
- **The agent image has a `/var/lib/culprit` directory,** owned by its
  non-root user, so a fresh named volume mounted there is writable by the
  agent (`deploy/agent/compose.yaml`). A volume already created from an
  older image keeps the ownership it was made with: if the agent cannot
  write its audit log there, `chown 65532:65532` the volume's contents, or
  start from the recipe.
- **A body sent to an agent route without a valid signature now gets `401`,
  not `422`.** Only a caller that relied on reading validation errors
  without signing sees a difference; a signed request with a bad body still
  gets the `422`.

If you build the frontend image yourself from a modified copy, set the new
build argument `VITE_SOURCE_URL` to where your source is: every page links
to it (AGPL-3.0 section 13; `LICENSING.md`).

**Phase 34 part 1 adds no secret and no migration.** It changes what
`culprit diagnose` does on the machine it runs on:

- **It captures the environment before it walks,** under the grants the
  environment already has, so a later `culprit verify` can tell a fix from a
  change underneath. That is one more read of what `culprit env capture`
  reads, and the same refusals; an environment that grants no capture gets
  none, and the investigation says so.
- **It writes files.** The investigation, the request behind each reading
  and that capture go to a state directory: `$CULPRIT_STATE_DIR`, else
  `$XDG_STATE_HOME/culprit`, `~/.local/state/culprit`, or
  `%LocalAppData%\culprit` on Windows. A CI job or a read-only container
  that runs `culprit diagnose` should set `--state-dir` (or the variable) to
  a writable path; if nothing can be written, diagnose still prints the
  investigation, warns, and the investigation says it cannot be verified.
- **The `verified` criterion's reason has new words** — how to verify this
  investigation, or why it cannot be — and is still never `true` on a
  diagnosis. Anything that matched the old sentence should match on
  `holds`, not the text.

**Phase 34 part 2 adds one role, two migrations and one secret.**

```
VERIFICATION_WRITER_DB_PASSWORD=<generate one>
VERIFICATION_WRITER_DATABASE_URL=postgresql+asyncpg://verification-writer:<same password>@postgres:5432/culprit
```

Both are required: migration `f2b7d4e9a1c6` will not create the role
without the password, and the api will not start without the URL.

- **`f1a9c3d7e2b4` narrows `api-reader` on `agent_nonces`** to the columns
  `agent_id` and `seen_at`. Anything of yours that read the `nonce` column
  as `api-reader` will be refused; the agents screen reads only those two.
- **`f2b7d4e9a1c6` adds `verifications`**, append-only: no role, the owner
  included, can update, delete or truncate it. A test fixture or a cleanup
  script that ran `TRUNCATE investigations CASCADE` now fails on it, because
  the cascade reaches `verifications`; such a script must lift the trigger
  as the owner (`ALTER TABLE verifications DISABLE TRIGGER USER`) and
  restore it. It also allows `verify` as an agent task kind.
- **An agent keeps a state directory** — `state/` beside its audit log,
  or `--state-dir` — with what verifying its walks needs, including a
  capture. The shipped recipes keep the audit log on a volume, so the state
  directory is on it too. Investigations an agent walked before this
  upgrade have no record there: verifying one answers `inconclusive`.
- **`GET /investigations/{id}/tree` gains `submitted_by`**, and **`TaskResult`
  gains `verification_id` and `verdict`**; nothing was removed.

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
