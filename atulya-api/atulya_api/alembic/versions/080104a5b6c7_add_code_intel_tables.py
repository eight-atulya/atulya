"""Add code intelligence columns and artifact/override tables.

Revision ID: 080104a5b6c7
Revises: 080103a4b5c6
Create Date: 2026-04-19
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "080104a5b6c7"
down_revision: str | Sequence[str] | None = "080103a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else "public."


def upgrade() -> None:
    prefix = _schema_prefix()

    op.execute(
        f"""
        ALTER TABLE {prefix}codebase_chunks
            ADD COLUMN IF NOT EXISTS significance_score double precision NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS significance_components jsonb,
            ADD COLUMN IF NOT EXISTS file_role text,
            ADD COLUMN IF NOT EXISTS auto_route_reason text,
            ADD COLUMN IF NOT EXISTS complexity_score double precision,
            ADD COLUMN IF NOT EXISTS safety_tags text[] NOT NULL DEFAULT '{{}}',
            ADD COLUMN IF NOT EXISTS pagerank_centrality double precision,
            ADD COLUMN IF NOT EXISTS fanin_count integer NOT NULL DEFAULT 0
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_chunks_snapshot_significance
        ON {prefix}codebase_chunks (snapshot_id, significance_score DESC)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_chunks_snapshot_role
        ON {prefix}codebase_chunks (snapshot_id, file_role)
        """
    )

    op.execute(
        f"""
        ALTER TABLE {prefix}codebases
            ADD COLUMN IF NOT EXISTS triage_settings jsonb NOT NULL DEFAULT '{{}}'::jsonb
        """
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}codebase_intel_artifacts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            codebase_id uuid NOT NULL REFERENCES {prefix}codebases(id) ON DELETE CASCADE,
            snapshot_id uuid NOT NULL REFERENCES {prefix}codebase_snapshots(id) ON DELETE CASCADE,
            bank_id text NOT NULL,
            kind text NOT NULL,
            ref_id text NOT NULL,
            payload jsonb NOT NULL,
            created_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_intel_artifacts_snapshot_kind
        ON {prefix}codebase_intel_artifacts (snapshot_id, kind)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_intel_artifacts_codebase_kind
        ON {prefix}codebase_intel_artifacts (codebase_id, kind)
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_codebase_intel_artifacts_snapshot_ref
        ON {prefix}codebase_intel_artifacts (snapshot_id, kind, ref_id)
        """
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}codebase_auto_triage_overrides (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            codebase_id uuid NOT NULL REFERENCES {prefix}codebases(id) ON DELETE CASCADE,
            snapshot_id uuid NOT NULL REFERENCES {prefix}codebase_snapshots(id) ON DELETE CASCADE,
            chunk_id uuid NOT NULL REFERENCES {prefix}codebase_chunks(id) ON DELETE CASCADE,
            bank_id text NOT NULL,
            prior_route text NOT NULL,
            prior_reason text,
            new_route text NOT NULL,
            user_id text,
            created_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_auto_triage_overrides_snapshot
        ON {prefix}codebase_auto_triage_overrides (snapshot_id, chunk_id)
        """
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}codebase_saved_intents (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            bank_id text NOT NULL,
            codebase_id uuid NOT NULL REFERENCES {prefix}codebases(id) ON DELETE CASCADE,
            label text NOT NULL,
            intent_text text NOT NULL,
            scope_hint text,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_saved_intents_codebase
        ON {prefix}codebase_saved_intents (codebase_id, bank_id)
        """
    )


def downgrade() -> None:
    prefix = _schema_prefix()

    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_saved_intents_codebase")
    op.execute(f"DROP TABLE IF EXISTS {prefix}codebase_saved_intents")

    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_auto_triage_overrides_snapshot")
    op.execute(f"DROP TABLE IF EXISTS {prefix}codebase_auto_triage_overrides")

    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_intel_artifacts_snapshot_ref")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_intel_artifacts_codebase_kind")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_intel_artifacts_snapshot_kind")
    op.execute(f"DROP TABLE IF EXISTS {prefix}codebase_intel_artifacts")

    op.execute(
        f"""
        ALTER TABLE {prefix}codebases
            DROP COLUMN IF EXISTS triage_settings
        """
    )

    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_chunks_snapshot_role")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_chunks_snapshot_significance")
    op.execute(
        f"""
        ALTER TABLE {prefix}codebase_chunks
            DROP COLUMN IF EXISTS fanin_count,
            DROP COLUMN IF EXISTS pagerank_centrality,
            DROP COLUMN IF EXISTS safety_tags,
            DROP COLUMN IF EXISTS complexity_score,
            DROP COLUMN IF EXISTS auto_route_reason,
            DROP COLUMN IF EXISTS file_role,
            DROP COLUMN IF EXISTS significance_components,
            DROP COLUMN IF EXISTS significance_score
        """
    )
