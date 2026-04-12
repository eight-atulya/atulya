"""Add codebase import and deterministic code index tables.

Revision ID: 0800e1f2a3b4
Revises: 0800d1e2f3a4
Create Date: 2026-04-12
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "0800e1f2a3b4"
down_revision: str | Sequence[str] | None = "0800d1e2f3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else "public."


def upgrade() -> None:
    prefix = _schema_prefix()

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}codebases (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            bank_id text NOT NULL,
            name text NOT NULL,
            source_type text NOT NULL,
            source_config jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            current_snapshot_id uuid,
            approved_snapshot_id uuid,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}codebase_snapshots (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            codebase_id uuid NOT NULL REFERENCES {prefix}codebases(id) ON DELETE CASCADE,
            bank_id text NOT NULL,
            source_ref text,
            source_commit_sha text,
            source_archive_storage_key text,
            status text NOT NULL DEFAULT 'pending',
            stats jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            approved_at timestamp with time zone,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}codebase_files (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            codebase_id uuid NOT NULL REFERENCES {prefix}codebases(id) ON DELETE CASCADE,
            snapshot_id uuid NOT NULL REFERENCES {prefix}codebase_snapshots(id) ON DELETE CASCADE,
            bank_id text NOT NULL,
            path text NOT NULL,
            language text,
            size_bytes integer NOT NULL,
            content_hash text NOT NULL,
            document_id text,
            status text NOT NULL,
            change_kind text NOT NULL DEFAULT 'added',
            reason text,
            created_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}codebase_symbols (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            codebase_id uuid NOT NULL REFERENCES {prefix}codebases(id) ON DELETE CASCADE,
            snapshot_id uuid NOT NULL REFERENCES {prefix}codebase_snapshots(id) ON DELETE CASCADE,
            bank_id text NOT NULL,
            path text NOT NULL,
            language text,
            name text NOT NULL,
            kind text NOT NULL,
            fq_name text NOT NULL,
            container text,
            start_line integer NOT NULL,
            end_line integer NOT NULL,
            created_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}codebase_edges (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            codebase_id uuid NOT NULL REFERENCES {prefix}codebases(id) ON DELETE CASCADE,
            snapshot_id uuid NOT NULL REFERENCES {prefix}codebase_snapshots(id) ON DELETE CASCADE,
            bank_id text NOT NULL,
            edge_type text NOT NULL,
            from_path text NOT NULL,
            from_symbol text,
            to_path text,
            to_symbol text,
            target_ref text,
            label text,
            created_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_codebases_bank_name_source
        ON {prefix}codebases (bank_id, name, source_type)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_snapshots_codebase_created
        ON {prefix}codebase_snapshots (codebase_id, created_at DESC)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebases_approved_snapshot
        ON {prefix}codebases (approved_snapshot_id)
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_codebase_files_snapshot_path
        ON {prefix}codebase_files (snapshot_id, path)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_files_codebase_snapshot
        ON {prefix}codebase_files (codebase_id, snapshot_id)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_files_change_kind
        ON {prefix}codebase_files (snapshot_id, change_kind)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_symbols_codebase_snapshot
        ON {prefix}codebase_symbols (codebase_id, snapshot_id)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_symbols_name
        ON {prefix}codebase_symbols (snapshot_id, name)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_symbols_fq_name
        ON {prefix}codebase_symbols (snapshot_id, fq_name)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_edges_snapshot_from
        ON {prefix}codebase_edges (snapshot_id, from_path)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_edges_snapshot_to
        ON {prefix}codebase_edges (snapshot_id, to_path)
        """
    )


def downgrade() -> None:
    prefix = _schema_prefix()
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_edges_snapshot_to")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_edges_snapshot_from")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_symbols_fq_name")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_symbols_name")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_symbols_codebase_snapshot")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_files_change_kind")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_files_codebase_snapshot")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_files_snapshot_path")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_snapshots_codebase_created")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebases_approved_snapshot")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebases_bank_name_source")
    op.execute(f"DROP TABLE IF EXISTS {prefix}codebase_edges")
    op.execute(f"DROP TABLE IF EXISTS {prefix}codebase_symbols")
    op.execute(f"DROP TABLE IF EXISTS {prefix}codebase_files")
    op.execute(f"DROP TABLE IF EXISTS {prefix}codebase_snapshots")
    op.execute(f"DROP TABLE IF EXISTS {prefix}codebases")
