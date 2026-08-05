"""create users table

Revision ID: fbf4cb16570a
Revises: 162c7130818c
Create Date: 2026-08-05 16:00:00.000000

Phase 16: replaces the single hardcoded operator (OPERATOR_USERNAME /
OPERATOR_PASSWORD_HASH env vars, api/app/auth/config.py) with a real
`users` table and two roles (admin, member). See
docs/SELF_HOSTED_PLAN.md's Phase 16 section for the full spec this
implements.

Backfill, in the same migration: if OPERATOR_USERNAME and
OPERATOR_PASSWORD_HASH are BOTH present in the environment, insert that
user as role='admin' -- this is what makes an existing deployment
(culprit.co.za) survive the upgrade with its current operator account
and password intact, no manual step. If either is absent (a fresh
install with neither ever configured), insert nothing -- Phase 17's
setup script or `just create-user` creates the first admin instead.
This is a one-time read of those env vars for the backfill only; they
are not read anywhere in application code after this migration (Trap in
Phase 16's plan section) -- api/app/auth/config.py stops importing them
at all.

Known Trap (docs/SELF_HOSTED_PLAN.md Phase 16, Trap 1): infra/.env.prod's
argon2 hash is $$-escaped for Docker Compose's own interpolation. Compose
un-escapes on injection, so THIS migration (run via `docker compose run
--rm api alembic upgrade head`, per infra/deploy.sh) receives the
already-unescaped value through its normal environment -- same as every
other _require_env password read in this file's sibling migrations. A
double-escaped hash here would backfill a user who can never log in, and
the failure looks exactly like "wrong password," not like a migration
bug -- verify the real hash round-trips before trusting this on a copy
of the live database, not just locally.
"""

import os
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fbf4cb16570a"
down_revision: str | None = "162c7130818c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTH_SERVICE_ROLE = "auth-service"


def _pg_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set in the environment to run this migration")
    return value


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE users (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            username       TEXT NOT NULL UNIQUE,
            password_hash  TEXT NOT NULL,
            role           TEXT NOT NULL DEFAULT 'member',
            disabled_at    TIMESTAMPTZ,
            last_login_at  TIMESTAMPTZ,
            created_at     TIMESTAMPTZ DEFAULT now(),
            CONSTRAINT ck_users_role CHECK (role IN ('admin', 'member'))
        )
        """
    )

    # Backfill: only if BOTH are set. A fresh install with neither ever
    # configured legitimately has zero rows here -- that's fine, it's
    # the same "no demo keys set" shape Phase 14's 48c0b29fa215 loosening
    # already established as a supported path, not an error case.
    operator_username = os.environ.get("OPERATOR_USERNAME")
    operator_password_hash = os.environ.get("OPERATOR_PASSWORD_HASH")
    if operator_username and operator_password_hash:
        op.execute(
            f"""
            INSERT INTO users (username, password_hash, role)
            VALUES ({_pg_string_literal(operator_username)},
                    {_pg_string_literal(operator_password_hash)},
                    'admin')
            """
        )

    auth_service_password = _require_env("AUTH_SERVICE_DB_PASSWORD")
    op.execute(
        f'CREATE ROLE "{AUTH_SERVICE_ROLE}" LOGIN PASSWORD '
        f"{_pg_string_literal(auth_service_password)}"
    )
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{AUTH_SERVICE_ROLE}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE ON users TO "{AUTH_SERVICE_ROLE}"')
    # api-reader stays read-only, same as every other table it can see --
    # this is what require_auth's per-request disabled-user check reads
    # through (api/app/auth/dependencies.py), not auth-service, so a
    # request that only ever reads never needs the write-capable role.
    op.execute('GRANT SELECT ON users TO "api-reader"')


def downgrade() -> None:
    op.execute('REVOKE SELECT ON users FROM "api-reader"')
    op.execute(f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "{AUTH_SERVICE_ROLE}"')
    op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{AUTH_SERVICE_ROLE}"')
    op.execute(f'DROP ROLE IF EXISTS "{AUTH_SERVICE_ROLE}"')
    op.execute("DROP TABLE users")
