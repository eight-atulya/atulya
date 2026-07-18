"""Add llm_requests table for per-bank LLM tracing.

Stores one row per logical LLM call Atulya makes (success and failure),
capturing input payload, output payload, token usage, finish reason, and caller
metadata when available.

Tracing is opt-in at the application layer (bank config / env var); this migration only
creates the table.

Revision ID: 08010ef5ab03
Revises: 08010de4fa02
Create Date: 2026-07-09
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "08010ef5ab03"
down_revision: str | Sequence[str] | None = "08010de4fa02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _get_schema_prefix() -> str:
    """Get the schema prefix for the current database connection.

    Returns:
        str: The schema prefix, or an empty string if no schema is set.
    """
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else ""


def _pg_upgrade() -> None:
    """Perform the PostgreSQL-specific upgrade."""
    schema = _get_schema_prefix()

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {schema}llm_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            bank_id TEXT,
            operation TEXT,
            scope TEXT,
            trace_id TEXT,
            span_id TEXT,
            parent_span_id TEXT,
            provider TEXT,
            model TEXT,
            status TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ended_at TIMESTAMPTZ,
            duration_ms INTEGER,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cached_tokens INTEGER,
            total_tokens INTEGER,
            input JSONB,
            output JSONB,
            error JSONB,
            llm_info JSONB DEFAULT '{{}}'::jsonb,
            metadata JSONB DEFAULT '{{}}'::jsonb
        );
        """
    )

    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_llm_requests_bank_started ON {schema}llm_requests (bank_id, started_at DESC)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_llm_requests_status_started ON {schema}llm_requests (status, started_at DESC)"
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS idx_llm_requests_started ON {schema}llm_requests (started_at DESC)")
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_llm_requests_trace ON {schema}llm_requests (bank_id, trace_id, started_at)"
    )


def _pg_downgrade() -> None:
    """Perform the PostgreSQL-specific downgrade."""
    schema = _get_schema_prefix()
    op.execute(f"DROP INDEX IF EXISTS {schema}idx_llm_requests_trace")
    op.execute(f"DROP INDEX IF EXISTS {schema}idx_llm_requests_started")
    op.execute(f"DROP INDEX IF EXISTS {schema}idx_llm_requests_status_started")
    op.execute(f"DROP INDEX IF EXISTS {schema}idx_llm_requests_bank_started")
    op.execute(f"DROP TABLE IF EXISTS {schema}llm_requests")


def upgrade() -> None:
    """Perform the upgrade."""
    _pg_upgrade()


def downgrade() -> None:
    """Perform the downgrade."""
    _pg_downgrade()
