"""Add approval-tracking columns to existing codebase tables.

Revision ID: 0800f1a2b3c4
Revises: 0800e1f2a3b4
Create Date: 2026-04-12
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "0800f1a2b3c4"
down_revision: str | Sequence[str] | None = "0800e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else "public."


def upgrade() -> None:
    prefix = _schema_prefix()

    op.execute(
        f"""
        ALTER TABLE {prefix}codebases
        ADD COLUMN IF NOT EXISTS approved_snapshot_id uuid
        """
    )
    op.execute(
        f"""
        ALTER TABLE {prefix}codebase_snapshots
        ADD COLUMN IF NOT EXISTS approved_at timestamp with time zone
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebases_approved_snapshot
        ON {prefix}codebases (approved_snapshot_id)
        """
    )


def downgrade() -> None:
    prefix = _schema_prefix()
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebases_approved_snapshot")
    op.execute(f"ALTER TABLE {prefix}codebase_snapshots DROP COLUMN IF EXISTS approved_at")
    op.execute(f"ALTER TABLE {prefix}codebases DROP COLUMN IF EXISTS approved_snapshot_id")
