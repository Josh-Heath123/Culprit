#!/usr/bin/env python3
"""Fails if the migration chain cannot round-trip against a real database.

Standing invariant 8 (docs/DIAGNOSTIC_PLAN.md §3), added 2026-09-09 after
Phase 26.1 shipped a downgrade that rewrote SQL `NULL` to `'null'::jsonb`,
so re-upgrading failed on its own new constraint.

`scripts/check_migration_symmetry.py` passed that migration both before
and after the fix, and always will: it is a structural AST check and
cannot see a data-dependent defect. A structural check that cannot fail
on a real class of bug is not a gate for that class, and pretending
otherwise is the exact error this product exists to stop. So this is the
gate for that class, and the only thing that can be: run the migrations
for real, both ways, twice.

    upgrade head -> downgrade base -> upgrade head

**Rows, not just an empty schema.** After the first `upgrade head` this
inserts a small amount of representative data before going back down.
A downgrade over an empty database exercises nothing but DDL, and the
Phase 26.1 defect was entirely in the DML — it was invisible until there
was a row for the downgrade to rewrite and the re-upgrade to choke on.
`_seed_statements()` is therefore not decoration; it is the part that
does the work.

Exit codes: 0 round trip clean · 1 a migration failed · 2 the check could
not run (no Docker, missing dependency). 2 is distinct on purpose — "the
gate did not run" must never be reported as "the gate passed", which is
the failure mode standing invariant 9 exists to name.

Run locally with `just check-migration-round-trip`; runs in CI as its own
job (.github/workflows/ci-cd.yml). Needs Docker, and api's venv for
alembic + testcontainers.
"""

import asyncio
import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_API_DIR = ROOT / "api"
_ALEMBIC_INI = str(_API_DIR / "alembic.ini")


@contextmanager
def _in_api_dir():
    """alembic.ini declares `script_location = migrations`, relative to
    itself, and alembic resolves it against the process working
    directory — so every alembic command here has to run from api/.
    Restored afterwards, so this script stays callable from anywhere."""
    previous = Path.cwd()
    os.chdir(_API_DIR)
    try:
        yield
    finally:
        os.chdir(previous)


#: Role passwords the role-creating migrations read via their own
#: `_require_env` at upgrade time. Test-only values against a throwaway
#: container that is destroyed when this script exits — the same set
#: api/tests/conftest.py uses, kept as its own copy because this script
#: runs outside pytest and importing a conftest would be worse.
_MIGRATION_ROLE_PASSWORDS = {
    "INGESTION_WRITER_PASSWORD": "round-trip-ingestion-writer",
    "API_READER_PASSWORD": "round-trip-api-reader",
    "INGEST_GATEWAY_DB_PASSWORD": "round-trip-ingest-gateway",
    "ANOMALY_DETECTOR_DB_PASSWORD": "round-trip-anomaly-detector",
    "CORRELATION_ENGINE_DB_PASSWORD": "round-trip-correlation-engine",
    "ROOT_CAUSE_WRITER_DB_PASSWORD": "round-trip-root-cause-writer",
    "REGISTRY_ADMIN_DB_PASSWORD": "round-trip-registry-admin",
    "AUTH_SERVICE_DB_PASSWORD": "round-trip-auth-service",
    "POSTMORTEM_WRITER_DB_PASSWORD": "round-trip-postmortem-writer",
    "MCP_READER_DB_PASSWORD": "round-trip-mcp-reader",
    "FACT_WRITER_DB_PASSWORD": "round-trip-fact-writer",
}

def _seed_statements() -> tuple[tuple[str, str], ...]:
    """Representative rows, inserted at head before the downgrade.

    A function rather than a module constant so the two config subjects
    can be built with `culprit_model.subjects.build()` — the only
    sanctioned way to construct one (§2.3), and a rule this script is no
    more exempt from than any other module. `scripts/` is inside the
    subject-construction lint's scanned roots.

    Kept deliberately small and hand-written rather than generated: every
    statement here exists because some migration's downgrade has to cope
    with it, and a reader should be able to see which. Each entry is
    (label, SQL); a statement that fails because its table does not exist
    at head is a bug in this list, not in the migrations, so `main`
    reports it as exit code 2 rather than 1.
    """
    from culprit_model.subjects import SubjectKind
    from culprit_model.subjects import build as build_subject

    port = build_subject(SubjectKind.CONFIG, component="rt-alpha", key="PORT")
    database_url = build_subject(SubjectKind.CONFIG, component="rt-alpha", key="DATABASE_URL")

    return (
        (
            "components",
            "INSERT INTO components (name, display_name, kind, sort_order, monitored_metrics) "
            "VALUES ('rt-alpha', 'RT Alpha', 'service', 0, '[]'::jsonb), "
            "       ('rt-beta', 'RT Beta', 'database', 1, '[]'::jsonb)",
        ),
        (
            # Two kinds between the same pair: the case the Phase 27
            # downgrade has to collapse into one service_dependencies row.
            # Without a row like this the downgrade looks fine and fails
            # on real data — removing its GROUP BY makes this script fail,
            # which is how that safeguard was confirmed load-bearing.
            "connections",
            "INSERT INTO connections (from_component_id, to_component_id, kind, criticality) "
            "SELECT f.id, t.id, k.kind, 'on_request_path' "
            "FROM components f, components t, (VALUES ('http'), ('sql')) AS k(kind) "
            "WHERE f.name = 'rt-alpha' AND t.name = 'rt-beta'",
        ),
        (
            "api_keys",
            "INSERT INTO api_keys (service_name, service_id, key_hash, label) "
            "SELECT c.name, c.id, 'round-trip-' || c.name, 'rt' FROM components c",
        ),
        (
            # A configured fact carrying a granted value: the Phase 26.1
            # shape whose downgrade/re-upgrade defect motivated this gate.
            "configured_facts",
            "WITH c AS ("
            "  INSERT INTO captures (plane, environment, extractor, started_at) "
            "  VALUES ('CONFIGURED', 'rt-env', 'round-trip@0.0.0', now()) RETURNING id"
            ") "
            "INSERT INTO configured_facts "
            "(capture_id, environment, subject, predicate, value, value_shape, grant_ref, "
            " source_kind, extractor, captured_at) "
            f"SELECT c.id, 'rt-env', '{port}', 'value', '8080'::jsonb, "
            # A shape in the closed four-field form Phase 28's
            # ck_configured_facts_value_shape_is_closed requires. It used
            # to be `{"type":"int"}` -- free-form JSONB, and not even a
            # valid ValueType. The gate caught it the moment the
            # constraint landed, which is the gate working: seed data
            # that no longer describes the schema is a defect in this
            # script, and it says so rather than blaming the migration.
            "       '{\"type\":\"integer\",\"length_class\":\"short\","
            "         \"format\": \"port\", \"present\": true}'::jsonb, "
            # The space after each colon is load-bearing, not style:
            # SQLAlchemy's text() reads `:true` as a bind parameter and
            # substitutes it, producing `"present"$1` and a syntax error
            # a long way from its cause.
            "'grant:config.read.values/PORT', "
            "       'introspection', 'round-trip@0.0.0', now() FROM c",
        ),
        (
            # ...and one without a value, the ordinary shape-only fact.
            # Both sides of ck_configured_facts_value_requires_grant have
            # to survive a round trip, not only the one it names.
            "configured_facts (shape only)",
            "WITH c AS ("
            "  INSERT INTO captures (plane, environment, extractor, started_at) "
            "  VALUES ('CONFIGURED', 'rt-env', 'round-trip@0.0.0', now()) RETURNING id"
            ") "
            "INSERT INTO configured_facts "
            "(capture_id, environment, subject, predicate, value_shape, "
            " source_kind, extractor, captured_at) "
            f"SELECT c.id, 'rt-env', '{database_url}', 'value', "
            "       '{\"type\": \"string\", \"length_class\": \"medium\", "
            "         \"format\": \"dsn\", \"present\": true}'::jsonb, "
            "       'introspection', 'round-trip@0.0.0', now() FROM c",
        ),
    )


def _fail(message: str, code: int = 1) -> int:
    print(message, file=sys.stderr)
    return code


async def _seed(sa, url: str) -> tuple[str, Exception] | None:
    """Inserts the seed statements at head. Returns the first failure, or None.

    asyncpg rather than psycopg2 because asyncpg is the only Postgres
    driver this repository installs (api/pyproject.toml) — `sa` is passed
    in rather than imported at module scope so the import-failure path in
    `main` stays the single place that reports a missing dependency.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            for label, statement in _seed_statements():
                try:
                    await conn.execute(sa.text(statement))
                except Exception as exc:
                    return label, exc
    finally:
        await engine.dispose()
    return None


def main() -> int:
    try:
        import sqlalchemy as sa
        from alembic import command
        from alembic.config import Config
        from testcontainers.community.postgres import PostgresContainer
    except ImportError as exc:  # pragma: no cover - environment problem
        return _fail(
            f"cannot run the migration round trip: {exc}\n"
            "Run it from api's venv: uv run --project api python "
            "scripts/check_migration_round_trip.py",
            2,
        )

    try:
        container = PostgresContainer("timescale/timescaledb-ha:pg16", driver="asyncpg")
        container.start()
    except Exception as exc:  # pragma: no cover - environment problem
        return _fail(
            f"cannot start a Postgres container (is Docker running?): {exc}\n"
            "NOT RUN is not the same as passing — see standing invariant 9.",
            2,
        )

    try:
        url = container.get_connection_url()
        os.environ["DATABASE_URL"] = url
        os.environ.update(_MIGRATION_ROLE_PASSWORDS)
        config = Config(_ALEMBIC_INI)

        print("==> upgrade head")
        with _in_api_dir():
            command.upgrade(config, "head")

        print(f"==> seeding {len(_seed_statements())} representative row set(s)")
        failure = asyncio.run(_seed(sa, url))
        if failure is not None:
            label, exc = failure
            return _fail(
                f"could not seed {label!r} at head: {exc}\n"
                "This is a defect in scripts/check_migration_round_trip.py's "
                "_seed_statements(), not in the migrations — the seed describes "
                "a schema head no longer has.",
                2,
            )

        print("==> downgrade base")
        try:
            with _in_api_dir():
                command.downgrade(config, "base")
        except Exception as exc:
            return _fail(
                f"downgrade to base failed with data present: {exc}\n\n"
                "A migration's downgrade() must survive real rows, not only an "
                "empty schema.",
            )

        print("==> upgrade head (again)")
        try:
            with _in_api_dir():
                command.upgrade(config, "head")
        except Exception as exc:
            return _fail(
                f"re-upgrade after downgrade failed: {exc}\n\n"
                "This is the Phase 26.1 defect class: a downgrade that leaves the "
                "database in a state its own upgrade() will not accept. "
                "scripts/check_migration_symmetry.py cannot see this — it is "
                "structural. Only this round trip can.",
            )
    finally:
        container.stop()

    print("Migration round trip clean: upgrade -> seed -> downgrade base -> upgrade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
