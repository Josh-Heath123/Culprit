"""probe readings: a probe-writer role, and api-reader on readings

Revision ID: a9d2c40f7e18
Revises: e4c1b7a9d2f0
Create Date: 2026-09-12 09:00:00.000000

Phase 31 (docs/DIAGNOSTIC_PLAN.md) — the first phase that writes the
OBSERVED plane. `readings` has existed since Phase 26 (c07a5f31d8e4) and
has been empty by design ever since, because no role held a single grant
on it. This migration grants the first two.

**1. A `probe-writer` role.** `.claude/rules/database.md` is explicit:
add a role, never widen one. Two sanctioned reuses exist —
`postmortem-writer` covering engineering memory, `fact-writer` covering
`divergences` — and that file names the signal plainly: "If you are
about to add a third, that is the signal this rule has stopped working."
So this is a new role, and the trust domains are genuinely different in
the way the rule cares about:

- `fact-writer` writes what a *repository* claims about itself, from a
  CI run on a pull request. It never touched a running system.
- `capture-writer` writes what a *running environment is configured to
  do*, read from that environment's declarations.
- `probe-writer` writes what happened when something *went and measured*
  a running system — a DNS lookup, a TCP handshake, a live schema read.
  A reading is the only one of the three that can only be produced by a
  credential that already has reach into the environment.

**What this role does and does not buy, precisely.** It bounds a leaked
*database* credential: a stolen `PROBE_WRITER_DATABASE_URL` appends to
the evidence log and can do nothing else — it cannot read that log back,
cannot touch `intent_facts` or `configured_facts`, and cannot reach any
other table. It does **not** bound a leaked *API* credential:
`POST /readings` authenticates with `require_project_token`, the same
single `CULPRIT_PROJECT_TOKEN` that already authorises
`POST /facts/captures` and `POST /divergences/captures`, so a token
leaked from a probe runner can still write the repository's own claims
about itself. An earlier draft of this docstring claimed otherwise; the
Phase 31 invariant audit caught it. Whether the three write endpoints
should share one token is an open question for the architecture session,
recorded in `docs/HANDOFF.md` §5 — it is an API-auth decision, not
something a migration can fix.

Its grants are the minimum the write path needs: INSERT on `readings`
and nothing else. **Not SELECT**, deliberately, and not by oversight —
`app/readings/service.py` uses a Core `insert()` with no RETURNING for
the same reason `app/facts/service.py` does (Postgres requires SELECT on
a table to return anything from it), so a leaked probe credential
appends to the evidence log and cannot browse it. `readings` is a
hypertable; TimescaleDB propagates a grant on the parent to its chunks,
which is how `ingestion-writer` has worked against `raw_events` since
Phase 1.

**2. `api-reader` gains SELECT on `readings`.** The established reader
pattern, and the same step Phase 27 took for `connections` and Phase 30
for `captures`/`configured_facts`: every dashboard read in this API runs
under `api-reader`, and a reading is dashboard-shaped data — a verdict, a
target, a time, a reason. It is argued rather than assumed because
`readings` carries `evidence`, which is the one JSONB column on the table
a probe could put something sensitive in. The model refuses that at
construction (`culprit_model.readings.Evidence` rejects unredacted
credential-shaped text), so the column a reader can see is one nothing
can write a credential into — the guarantee sits in front of the grant
rather than behind it.

**3. `anomaly-detector` gains SELECT on `connections`.** The worker's
anomaly job now emits an impedance reading beside each score, and an
impedance reading is *about a connection* — so it has to resolve which
connection a metric row belongs to. The attribution rule
(`worker/app/anomaly/job.py`) reads a peer name out of the row's own
attributes, and failing that looks for exactly one declared inbound
connection; with several, or none, it emits nothing rather than guess.

This is a read grant on a sibling of a table the role already reads, not
the widening `.claude/rules/database.md` forbids — that rule is about a
component needing a *write* the current roles cannot do, and the direct
precedent is 635870479f4e, which gave this same role SELECT on `services`
(now `components`) when the registry replaced the hardcoded metric list.
The role still holds INSERT on `anomalies` and nothing else it can write.

The readings themselves are **not** written under it: the worker opens a
second engine as `probe-writer` for that (`worker/app/main.py`). A
reading is the OBSERVED plane, not an anomaly row, and letting the
scoring role write one would have made `probe-writer` decorative.

No other role is touched. `fact-writer` and `capture-writer` still get
"permission denied" on `readings`, and the tests asserting that
(`api/tests/test_facts_api.py`, `api/tests/test_captures_api.py`) are
unchanged and still pass — which is the point of granting a new role
instead of reaching for one that already exists.
"""
import os
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9d2c40f7e18"
down_revision: str | None = "e4c1b7a9d2f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROBE_WRITER_ROLE = "probe-writer"
API_READER_ROLE = "api-reader"
ANOMALY_DETECTOR_ROLE = "anomaly-detector"


def _pg_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set in the environment to run this migration")
    return value


def upgrade() -> None:
    password = _require_env("PROBE_WRITER_DB_PASSWORD")
    op.execute(f'CREATE ROLE "{PROBE_WRITER_ROLE}" LOGIN PASSWORD {_pg_string_literal(password)}')
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{PROBE_WRITER_ROLE}"')
    # INSERT alone. See the docstring: no SELECT, so the insert path must
    # stay RETURNING-free, and a leaked probe credential cannot read the
    # evidence log back.
    op.execute(f'GRANT INSERT ON readings TO "{PROBE_WRITER_ROLE}"')

    op.execute(f'GRANT SELECT ON readings TO "{API_READER_ROLE}"')

    op.execute(f'GRANT SELECT ON connections TO "{ANOMALY_DETECTOR_ROLE}"')


def downgrade() -> None:
    op.execute(f'REVOKE SELECT ON connections FROM "{ANOMALY_DETECTOR_ROLE}"')

    op.execute(f'REVOKE SELECT ON readings FROM "{API_READER_ROLE}"')

    op.execute(f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "{PROBE_WRITER_ROLE}"')
    op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{PROBE_WRITER_ROLE}"')
    op.execute(f'DROP ROLE IF EXISTS "{PROBE_WRITER_ROLE}"')
