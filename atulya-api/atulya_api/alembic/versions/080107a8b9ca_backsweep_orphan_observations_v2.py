"""Defensive backsweep of orphan observations.

Revision ID: 080107a8b9ca
Revises: 080106a7b8c9
Create Date: 2026-04-19

The retain pipeline's ``handle_document_tracking`` upsert path used to delete
documents (cascading to memory_units) without sweeping observations whose
``source_memory_ids`` referenced the now-deleted units, leaving orphans in the
database. The bug fix in this PR adds the sweep to the upsert path; this
migration removes any orphans that accumulated before the fix.

Idempotent: deletes only observations whose ``source_memory_ids`` reference
zero live memories in the same bank. Re-running it on a clean database is a
no-op.
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "080107a8b9ca"
down_revision: str | Sequence[str] | None = "080106a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else "public."


def upgrade() -> None:
    prefix = _schema_prefix()
    mu = f"{prefix}memory_units"
    op.execute(
        f"""
        DELETE FROM {mu} orphan
        WHERE orphan.fact_type = 'observation'
          AND NOT EXISTS (
              SELECT 1
              FROM {mu} src
              WHERE src.id = ANY(orphan.source_memory_ids)
                AND src.bank_id = orphan.bank_id
          )
        """
    )


def downgrade() -> None:
    # Cannot resurrect deleted rows; downgrade is a no-op.
    pass
