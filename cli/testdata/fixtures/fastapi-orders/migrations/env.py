"""Minimal Alembic env, so ScriptDirectory can be constructed offline."""

from alembic import context

if context.is_offline_mode():  # pragma: no cover - fixture scaffolding
    pass
