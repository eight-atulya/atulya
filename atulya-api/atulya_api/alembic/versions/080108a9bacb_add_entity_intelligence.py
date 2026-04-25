"""Add bank-level entity intelligence.

Revision ID: 080108a9bacb
Revises: 080107a8b9ca
Create Date: 2026-04-25
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "080108a9bacb"
down_revision: str | Sequence[str] | None = "080107a8b9ca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else "public."


def upgrade() -> None:
    prefix = _schema_prefix()
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}entity_intelligence (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            bank_id text NOT NULL,
            computed_at timestamp with time zone NOT NULL DEFAULT now(),
            entity_count integer NOT NULL DEFAULT 0,
            source_entity_count integer NOT NULL DEFAULT 0,
            entity_snapshot_hash text NOT NULL DEFAULT '',
            content text NOT NULL DEFAULT '',
            structured_content jsonb NOT NULL,
            entity_context jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            delta_metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            llm_model text NOT NULL DEFAULT '',
            prompt_version text NOT NULL DEFAULT 'v1'
        )
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_entity_intelligence_bank
        ON {prefix}entity_intelligence (bank_id)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_entity_intelligence_computed
        ON {prefix}entity_intelligence (computed_at DESC)
        """
    )


def downgrade() -> None:
    prefix = _schema_prefix()
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_entity_intelligence_computed")
    op.execute(f"DROP INDEX IF EXISTS {prefix}uq_entity_intelligence_bank")
    op.execute(f"DROP TABLE IF EXISTS {prefix}entity_intelligence CASCADE")
