"""Add codebase chunk review and routing tables.

Revision ID: 080101a2b3c4
Revises: 0800f1a2b3c4
Create Date: 2026-04-13
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "080101a2b3c4"
down_revision: str | Sequence[str] | None = "0800f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else "public."


def upgrade() -> None:
    prefix = _schema_prefix()

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}codebase_chunks (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            codebase_id uuid NOT NULL REFERENCES {prefix}codebases(id) ON DELETE CASCADE,
            snapshot_id uuid NOT NULL REFERENCES {prefix}codebase_snapshots(id) ON DELETE CASCADE,
            bank_id text NOT NULL,
            chunk_key text NOT NULL,
            document_id text,
            path text NOT NULL,
            language text,
            kind text NOT NULL,
            label text NOT NULL,
            content_hash text NOT NULL,
            preview_text text NOT NULL,
            content_text text NOT NULL,
            start_line integer NOT NULL,
            end_line integer NOT NULL,
            container text,
            parent_symbol text,
            parent_fq_name text,
            parse_confidence double precision NOT NULL DEFAULT 0,
            cluster_id text,
            cluster_label text,
            created_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}codebase_chunk_edges (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            codebase_id uuid NOT NULL REFERENCES {prefix}codebases(id) ON DELETE CASCADE,
            snapshot_id uuid NOT NULL REFERENCES {prefix}codebase_snapshots(id) ON DELETE CASCADE,
            bank_id text NOT NULL,
            edge_type text NOT NULL,
            from_chunk_id uuid NOT NULL REFERENCES {prefix}codebase_chunks(id) ON DELETE CASCADE,
            to_chunk_id uuid NOT NULL REFERENCES {prefix}codebase_chunks(id) ON DELETE CASCADE,
            score double precision,
            label text,
            created_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}codebase_review_routes (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            codebase_id uuid NOT NULL REFERENCES {prefix}codebases(id) ON DELETE CASCADE,
            snapshot_id uuid NOT NULL REFERENCES {prefix}codebase_snapshots(id) ON DELETE CASCADE,
            chunk_id uuid NOT NULL REFERENCES {prefix}codebase_chunks(id) ON DELETE CASCADE,
            bank_id text NOT NULL,
            route_target text NOT NULL DEFAULT 'unrouted',
            route_source text NOT NULL DEFAULT 'system',
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_codebase_chunks_snapshot_chunk_key
        ON {prefix}codebase_chunks (snapshot_id, chunk_key)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_chunks_snapshot_path
        ON {prefix}codebase_chunks (snapshot_id, path, start_line)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_chunks_snapshot_cluster
        ON {prefix}codebase_chunks (snapshot_id, cluster_id)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_chunk_edges_snapshot_from
        ON {prefix}codebase_chunk_edges (snapshot_id, from_chunk_id)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_chunk_edges_snapshot_to
        ON {prefix}codebase_chunk_edges (snapshot_id, to_chunk_id)
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_codebase_review_routes_snapshot_chunk
        ON {prefix}codebase_review_routes (snapshot_id, chunk_id)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_codebase_review_routes_snapshot_target
        ON {prefix}codebase_review_routes (snapshot_id, route_target)
        """
    )


def downgrade() -> None:
    prefix = _schema_prefix()
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_review_routes_snapshot_target")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_review_routes_snapshot_chunk")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_chunk_edges_snapshot_to")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_chunk_edges_snapshot_from")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_chunks_snapshot_cluster")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_chunks_snapshot_path")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_codebase_chunks_snapshot_chunk_key")
    op.execute(f"DROP TABLE IF EXISTS {prefix}codebase_review_routes")
    op.execute(f"DROP TABLE IF EXISTS {prefix}codebase_chunk_edges")
    op.execute(f"DROP TABLE IF EXISTS {prefix}codebase_chunks")
