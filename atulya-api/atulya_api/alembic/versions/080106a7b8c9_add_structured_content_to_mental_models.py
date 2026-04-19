"""Add structured_content column to mental_models.

Revision ID: 080106a7b8c9
Revises: 080105a6b7c8
Create Date: 2026-04-19

Stores the authoritative structured representation of a mental model document
(see atulya_api.engine.reflect.structured_doc). The markdown ``content`` column
remains the user-facing render; ``structured_content`` is the source of truth
that delta-mode refreshes operate on so unchanged sections survive byte-identical.
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "080106a7b8c9"
down_revision: str | Sequence[str] | None = "080105a6b7c8"
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
            ADD COLUMN IF NOT EXISTS structured_content JSONB
        """
    )


def downgrade() -> None:
    prefix = _schema_prefix()
    op.execute(f"ALTER TABLE {prefix}mental_models DROP COLUMN IF EXISTS structured_content")
