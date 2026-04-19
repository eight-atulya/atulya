"""Add last_refreshed_source_query column to mental_models.

Revision ID: 080105a6b7c8
Revises: 080104a5b6c7
Create Date: 2026-04-19

Tracks the source_query value at the time of the last refresh, so that the
delta-mode refresh path can detect a topic change and force a full rebuild
instead of attempting surgical edits against a now-irrelevant document.
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "080105a6b7c8"
down_revision: str | Sequence[str] | None = "080104a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else "public."


def upgrade() -> None:
    prefix = _schema_prefix()
    op.execute(
        f"""
        ALTER TABLE {prefix}mental_models
            ADD COLUMN IF NOT EXISTS last_refreshed_source_query TEXT
        """
    )


def downgrade() -> None:
    prefix = _schema_prefix()
    op.execute(f"ALTER TABLE {prefix}mental_models DROP COLUMN IF EXISTS last_refreshed_source_query")
