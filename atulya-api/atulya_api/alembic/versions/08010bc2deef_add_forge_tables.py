"""Add forge_records tables for Data Forge."""

from __future__ import annotations

from typing import Sequence

from alembic import context, op

revision: str = "08010bc2deef"
down_revision: str | Sequence[str] | None = "08010ab1cbdd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else "public."


def upgrade() -> None:
    prefix = _schema_prefix()
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}forge_records (
            id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            operation_id uuid NOT NULL,
            bank_id text NOT NULL,
            record_id text NOT NULL,
            recipe_id text NOT NULL,
            record_json jsonb NOT NULL,
            quality_score double precision DEFAULT 0.0 NOT NULL,
            exportable boolean DEFAULT false NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_forge_records_operation
        ON {prefix}forge_records (operation_id, created_at DESC)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_forge_records_bank
        ON {prefix}forge_records (bank_id, created_at DESC)
        """
    )


def downgrade() -> None:
    prefix = _schema_prefix()
    op.execute(f"DROP TABLE IF EXISTS {prefix}forge_records")
