"""create api keys table

Revision ID: 48c0b29fa215
Revises: cc323b6c7779
Create Date: 2026-08-02 19:58:16.971735

Three fixed, manually-provisioned keys for the three demo services — no
general onboarding flow, per the Phase 3 scope decision. Plaintext values
come from ORDER_SERVICE_API_KEY / INVENTORY_SERVICE_API_KEY /
PAYMENTS_SERVICE_API_KEY in the environment; only their SHA-256 hashes are
ever written here. ingest-gateway hashes the presented key the same way
and compares hash-to-hash with secrets.compare_digest — the plaintext
never touches the database.
"""
import hashlib
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "48c0b29fa215"
down_revision: str | None = "cc323b6c7779"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SERVICE_KEY_ENV_VARS = {
    "order-service": "ORDER_SERVICE_API_KEY",
    "inventory-service": "INVENTORY_SERVICE_API_KEY",
    "payments-service": "PAYMENTS_SERVICE_API_KEY",
}


def _hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("service_name", sa.String(), nullable=False, unique=True),
        sa.Column("key_hash", sa.String(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    api_keys_table = sa.table(
        "api_keys",
        sa.column("service_name", sa.String),
        sa.column("key_hash", sa.String),
    )
    rows = []
    for service_name, env_var in SERVICE_KEY_ENV_VARS.items():
        plaintext = os.environ.get(env_var)
        if not plaintext:
            raise RuntimeError(f"{env_var} must be set in the environment to run this migration")
        rows.append({"service_name": service_name, "key_hash": _hash_key(plaintext)})
    op.bulk_insert(api_keys_table, rows)


def downgrade() -> None:
    op.drop_table("api_keys")
