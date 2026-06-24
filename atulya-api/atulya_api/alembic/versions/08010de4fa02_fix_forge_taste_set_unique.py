"""Fix forge_taste_sets unique constraint for variants."""

from __future__ import annotations

from typing import Sequence

from alembic import context, op

revision: str = "08010de4fa02"
down_revision: str | Sequence[str] | None = "08010cd3ef01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else "public."


def upgrade() -> None:
    prefix = _schema_prefix()
    op.execute(
        f"""
        ALTER TABLE {prefix}forge_taste_sets
        DROP CONSTRAINT IF EXISTS forge_taste_sets_dataset_id_set_key_key
        """
    )
    op.execute(
        f"""
        ALTER TABLE {prefix}forge_taste_sets
        ADD CONSTRAINT forge_taste_sets_dataset_id_set_key_variant_key
        UNIQUE (dataset_id, set_key, variant_index)
        """
    )


def downgrade() -> None:
    prefix = _schema_prefix()
    op.execute(
        f"""
        ALTER TABLE {prefix}forge_taste_sets
        DROP CONSTRAINT IF EXISTS forge_taste_sets_dataset_id_set_key_variant_key
        """
    )
    op.execute(
        f"""
        ALTER TABLE {prefix}forge_taste_sets
        ADD CONSTRAINT forge_taste_sets_dataset_id_set_key_key
        UNIQUE (dataset_id, set_key)
        """
    )
