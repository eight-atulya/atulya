"""Add timeline metadata columns for memories.

Revision ID: 0800d1e2f3a4
Revises: 0800c1d2e3f4
Create Date: 2026-03-31
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "0800d1e2f3a4"
down_revision: str | Sequence[str] | None = "0800c1d2e3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else "public."


def upgrade() -> None:
    prefix = _schema_prefix()
    op.execute(
        f"""
        ALTER TABLE {prefix}memory_units
        ADD COLUMN IF NOT EXISTS timeline_anchor_at timestamp with time zone,
        ADD COLUMN IF NOT EXISTS timeline_anchor_kind text NOT NULL DEFAULT 'recorded_only',
        ADD COLUMN IF NOT EXISTS temporal_direction text NOT NULL DEFAULT 'atemporal',
        ADD COLUMN IF NOT EXISTS temporal_confidence double precision,
        ADD COLUMN IF NOT EXISTS temporal_reference_text text
        """
    )
    op.execute(f"ALTER TABLE {prefix}memory_units DROP CONSTRAINT IF EXISTS memory_units_timeline_anchor_kind_check")
    op.execute(
        f"""
        ALTER TABLE {prefix}memory_units
        ADD CONSTRAINT memory_units_timeline_anchor_kind_check CHECK (
            timeline_anchor_kind = ANY (ARRAY[
                'event_exact'::text,
                'event_inferred'::text,
                'ongoing_state'::text,
                'future_plan'::text,
                'recorded_only'::text,
                'derived_snapshot'::text
            ])
        )
        """
    )
    op.execute(f"ALTER TABLE {prefix}memory_units DROP CONSTRAINT IF EXISTS memory_units_temporal_direction_check")
    op.execute(
        f"""
        ALTER TABLE {prefix}memory_units
        ADD CONSTRAINT memory_units_temporal_direction_check CHECK (
            temporal_direction = ANY (ARRAY[
                'past'::text,
                'present'::text,
                'future'::text,
                'atemporal'::text
            ])
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_memory_units_bank_timeline_anchor
        ON {prefix}memory_units (bank_id, timeline_anchor_at DESC)
        """
    )


def downgrade() -> None:
    prefix = _schema_prefix()
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_memory_units_bank_timeline_anchor")
    op.execute(f"ALTER TABLE {prefix}memory_units DROP CONSTRAINT IF EXISTS memory_units_temporal_direction_check")
    op.execute(f"ALTER TABLE {prefix}memory_units DROP CONSTRAINT IF EXISTS memory_units_timeline_anchor_kind_check")
    op.execute(
        f"""
        ALTER TABLE {prefix}memory_units
        DROP COLUMN IF EXISTS temporal_reference_text,
        DROP COLUMN IF EXISTS temporal_confidence,
        DROP COLUMN IF EXISTS temporal_direction,
        DROP COLUMN IF EXISTS timeline_anchor_kind,
        DROP COLUMN IF EXISTS timeline_anchor_at
        """
    )
