"""Add forge taste studio tables."""

from __future__ import annotations

from typing import Sequence

from alembic import context, op

revision: str = "08010cd3ef01"
down_revision: str | Sequence[str] | None = "08010bc2deef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else "public."


def upgrade() -> None:
    prefix = _schema_prefix()
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}forge_taste_datasets (
            id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            bank_id text NOT NULL,
            name text NOT NULL,
            description text,
            schema_type text NOT NULL DEFAULT 'openai_chat',
            taste_tags text[] DEFAULT '{{}}'::text[] NOT NULL,
            taste_profile_json jsonb,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            updated_at timestamp with time zone DEFAULT now() NOT NULL
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}forge_taste_sets (
            id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            dataset_id uuid NOT NULL REFERENCES {prefix}forge_taste_datasets(id) ON DELETE CASCADE,
            bank_id text NOT NULL,
            set_key text NOT NULL,
            parent_set_id uuid REFERENCES {prefix}forge_taste_sets(id) ON DELETE SET NULL,
            variant_index integer NOT NULL DEFAULT 0,
            source_payload jsonb NOT NULL,
            working_payload jsonb NOT NULL,
            transform_log jsonb DEFAULT '[]'::jsonb NOT NULL,
            taste_tags text[] DEFAULT '{{}}'::text[] NOT NULL,
            entity_ids text[] DEFAULT '{{}}'::text[] NOT NULL,
            memory_unit_ids text[] DEFAULT '{{}}'::text[] NOT NULL,
            status text NOT NULL DEFAULT 'draft',
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            updated_at timestamp with time zone DEFAULT now() NOT NULL,
            UNIQUE (dataset_id, set_key)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}forge_transform_chains (
            id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
            bank_id text NOT NULL,
            name text NOT NULL,
            ops jsonb NOT NULL DEFAULT '[]'::jsonb,
            is_default boolean NOT NULL DEFAULT false,
            created_at timestamp with time zone DEFAULT now() NOT NULL
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_forge_taste_datasets_bank
        ON {prefix}forge_taste_datasets (bank_id, updated_at DESC)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_forge_taste_sets_dataset
        ON {prefix}forge_taste_sets (dataset_id, variant_index, updated_at DESC)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_forge_taste_sets_parent
        ON {prefix}forge_taste_sets (parent_set_id)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_forge_taste_sets_tags_gin
        ON {prefix}forge_taste_sets USING GIN (taste_tags)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_forge_transform_chains_bank
        ON {prefix}forge_transform_chains (bank_id, created_at DESC)
        """
    )


def downgrade() -> None:
    prefix = _schema_prefix()
    op.execute(f"DROP TABLE IF EXISTS {prefix}forge_transform_chains")
    op.execute(f"DROP TABLE IF EXISTS {prefix}forge_taste_sets")
    op.execute(f"DROP TABLE IF EXISTS {prefix}forge_taste_datasets")
