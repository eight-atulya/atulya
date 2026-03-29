"""Add result payload storage to async operations.

Revision ID: 0800b1c2d3e4
Revises: 0800a1b2c3d4
Create Date: 2026-03-29
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "0800b1c2d3e4"
down_revision: str | Sequence[str] | None = "0800a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else "public."


def upgrade() -> None:
    op.execute(f"ALTER TABLE {_schema_prefix()}async_operations ADD COLUMN IF NOT EXISTS result_payload jsonb")


def downgrade() -> None:
    op.execute(f"ALTER TABLE {_schema_prefix()}async_operations DROP COLUMN IF EXISTS result_payload")
