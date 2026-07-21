"""Finalize canonical service-key constraints.

Revision ID: 080111b8cd06
Revises: 080110a7bc05
Create Date: 2026-07-20
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import context, op

revision: str = "080111b8cd06"
down_revision: str | Sequence[str] | None = "080110a7bc05"
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
    op.execute(f"ALTER TABLE {schema}api_keys DROP CONSTRAINT IF EXISTS api_keys_role_check")
    op.execute(
        f"ALTER TABLE {schema}api_keys ADD CONSTRAINT api_keys_role_check "
        "CHECK (role IN ('superuser', 'owner', 'admin', 'operator', 'viewer', 'service', 'user'))"
    )
    op.execute(
        f"ALTER TABLE {schema}api_keys ADD CONSTRAINT api_keys_principal_fk "
        f"FOREIGN KEY (principal_id) REFERENCES {schema}principals(id) ON DELETE CASCADE"
    )
    op.execute(
        f"ALTER TABLE {schema}api_keys ADD CONSTRAINT api_keys_created_by_fk "
        f"FOREIGN KEY (created_by) REFERENCES {schema}principals(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    if not _is_auth_schema():
        return
    schema = _schema_prefix()
    op.execute(f"ALTER TABLE {schema}api_keys DROP CONSTRAINT IF EXISTS api_keys_created_by_fk")
    op.execute(f"ALTER TABLE {schema}api_keys DROP CONSTRAINT IF EXISTS api_keys_principal_fk")
    op.execute(f"ALTER TABLE {schema}api_keys DROP CONSTRAINT IF EXISTS api_keys_role_check")
    op.execute(
        f"ALTER TABLE {schema}api_keys ADD CONSTRAINT api_keys_role_check "
        "CHECK (role IN ('superuser', 'admin', 'user'))"
    )
