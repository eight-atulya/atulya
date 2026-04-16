"""Add entity_trajectories for LLM+HMM-style entity progression.

Revision ID: 080103a4b5c6
Revises: 080102a3b4c5
Create Date: 2026-04-16
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "080103a4b5c6"
down_revision: str | Sequence[str] | None = "080102a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else "public."


def upgrade() -> None:
    prefix = _schema_prefix()

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}entity_trajectories (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            bank_id text NOT NULL,
            entity_id uuid NOT NULL REFERENCES {prefix}entities(id) ON DELETE CASCADE,
            computed_at timestamp with time zone NOT NULL DEFAULT now(),
            state_vocabulary jsonb NOT NULL,
            vocabulary_hash text NOT NULL DEFAULT '',
            transition_matrix jsonb NOT NULL,
            current_state text NOT NULL,
            viterbi_path jsonb NOT NULL,
            forecast_horizon integer NOT NULL DEFAULT 5,
            forecast_distribution jsonb NOT NULL,
            forward_log_prob double precision,
            anomaly_score double precision,
            llm_model text NOT NULL DEFAULT '',
            prompt_version text NOT NULL DEFAULT 'v1'
        )
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_entity_trajectories_bank_entity
        ON {prefix}entity_trajectories (bank_id, entity_id)
        """
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_entity_trajectories_bank_computed ON {prefix}entity_trajectories (bank_id, computed_at DESC)"
    )


def downgrade() -> None:
    prefix = _schema_prefix()
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_entity_trajectories_bank_computed")
    op.execute(f"DROP INDEX IF EXISTS {prefix}uq_entity_trajectories_bank_entity")
    op.execute(f"DROP TABLE IF EXISTS {prefix}entity_trajectories CASCADE")
