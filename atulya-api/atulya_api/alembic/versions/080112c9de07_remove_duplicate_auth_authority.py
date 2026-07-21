"""Remove deprecated identity and key-level authorization columns.

Revision ID: 080112c9de07
Revises: 080111b8cd06
Create Date: 2026-07-20
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import context, op

revision: str = "080112c9de07"
down_revision: str | Sequence[str] | None = "080111b8cd06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else ""


def _is_auth_schema() -> bool:
    target = context.config.get_main_option("target_schema") or "public"
    return target == os.getenv("ATULYA_API_AUTH_SCHEMA", "public")


def upgrade() -> None:
    if not _is_auth_schema():
        return
    schema = _schema_prefix()
    op.execute(f"DROP INDEX IF EXISTS {schema}ux_principals_org_email")
    op.execute(f"ALTER TABLE {schema}principals DROP COLUMN IF EXISTS org_id")
    op.execute(f"ALTER TABLE {schema}principals DROP COLUMN IF EXISTS role")
    op.execute(f"DROP INDEX IF EXISTS {schema}ix_api_keys_schema_name")
    op.execute(f"ALTER TABLE {schema}api_keys DROP CONSTRAINT IF EXISTS api_keys_role_check")
    op.execute(f"ALTER TABLE {schema}api_keys DROP COLUMN IF EXISTS role")
    op.execute(f"ALTER TABLE {schema}api_keys DROP COLUMN IF EXISTS schema_name")
    op.execute(f"ALTER TABLE {schema}api_keys DROP COLUMN IF EXISTS allowed_bank_ids")


def downgrade() -> None:
    if not _is_auth_schema():
        return
    schema = _schema_prefix()
    op.execute(f"ALTER TABLE {schema}principals ADD COLUMN org_id UUID REFERENCES {schema}orgs(id) ON DELETE CASCADE")
    op.execute(f"ALTER TABLE {schema}principals ADD COLUMN role TEXT")
    op.execute(f"ALTER TABLE {schema}api_keys ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
    op.execute(f"ALTER TABLE {schema}api_keys ADD COLUMN schema_name TEXT NOT NULL DEFAULT 'public'")
    op.execute(f"ALTER TABLE {schema}api_keys ADD COLUMN allowed_bank_ids TEXT[]")
    op.execute(f"CREATE INDEX ix_api_keys_schema_name ON {schema}api_keys (schema_name)")
