"""Add structured dream run storage.

Revision ID: 0800c1d2e3f4
Revises: 0800b1c2d3e4
Create Date: 2026-03-29
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "0800c1d2e3f4"
down_revision: str | Sequence[str] | None = "0800b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else "public."


def upgrade() -> None:
    prefix = _schema_prefix()
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}dream_runs (
            id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
            bank_id text NOT NULL,
            run_type text NOT NULL,
            trigger_source text NOT NULL DEFAULT 'manual',
            status text NOT NULL,
            summary text,
            narrative_html text,
            evidence_basis jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            signals jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            confidence jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            novelty_score double precision NOT NULL DEFAULT 0.0,
            maturity_tier text NOT NULL DEFAULT 'sparse',
            quality_score double precision NOT NULL DEFAULT 0.0,
            validation_rate double precision NOT NULL DEFAULT 0.0,
            calibration_score double precision NOT NULL DEFAULT 0.0,
            result_metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            failure_reason text,
            source_artifact_id uuid,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            updated_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT dream_runs_status_check CHECK (
                status = ANY (ARRAY[
                    'success'::text,
                    'low_signal'::text,
                    'duplicate_low_novelty'::text,
                    'failed_llm'::text,
                    'failed_validation'::text
                ])
            ),
            CONSTRAINT dream_runs_maturity_tier_check CHECK (
                maturity_tier = ANY (ARRAY['sparse'::text, 'emerging'::text, 'mature'::text])
            )
        )
        """
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_dream_runs_bank_created ON {prefix}dream_runs (bank_id, created_at DESC)"
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS idx_dream_runs_bank_status ON {prefix}dream_runs (bank_id, status)")
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_dream_runs_result_metadata ON {prefix}dream_runs USING gin (result_metadata)"
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}dream_predictions (
            id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
            run_id uuid NOT NULL REFERENCES {prefix}dream_runs(id) ON DELETE CASCADE,
            bank_id text NOT NULL,
            title text NOT NULL,
            description text NOT NULL,
            target_ref text,
            target_kind text NOT NULL DEFAULT 'theme',
            horizon text NOT NULL DEFAULT 'near_term',
            confidence double precision NOT NULL DEFAULT 0.0,
            success_criteria jsonb NOT NULL DEFAULT '[]'::jsonb,
            expiration_window_days integer NOT NULL DEFAULT 14,
            status text NOT NULL DEFAULT 'pending',
            supporting_evidence_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
            validation_notes text,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            updated_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT dream_predictions_status_check CHECK (
                status = ANY (ARRAY['pending'::text, 'confirmed'::text, 'contradicted'::text, 'unresolved'::text])
            )
        )
        """
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_dream_predictions_run_id ON {prefix}dream_predictions (run_id, created_at DESC)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_dream_predictions_bank_status ON {prefix}dream_predictions (bank_id, status)"
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}dream_proposals (
            id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
            run_id uuid NOT NULL REFERENCES {prefix}dream_runs(id) ON DELETE CASCADE,
            bank_id text NOT NULL,
            proposal_type text NOT NULL,
            title text NOT NULL,
            content text NOT NULL,
            confidence double precision NOT NULL DEFAULT 0.0,
            tags jsonb NOT NULL DEFAULT '[]'::jsonb,
            supporting_evidence_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
            review_status text NOT NULL DEFAULT 'proposed',
            rationale text,
            approval_metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            reviewed_at timestamp with time zone,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            updated_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT dream_proposals_review_status_check CHECK (
                review_status = ANY (ARRAY[
                    'proposed'::text,
                    'approved'::text,
                    'rejected'::text,
                    'needs_more_evidence'::text
                ])
            )
        )
        """
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_dream_proposals_run_id ON {prefix}dream_proposals (run_id, created_at DESC)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_dream_proposals_bank_review_status ON {prefix}dream_proposals (bank_id, review_status)"
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}dream_prediction_outcomes (
            id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
            prediction_id uuid NOT NULL REFERENCES {prefix}dream_predictions(id) ON DELETE CASCADE,
            bank_id text NOT NULL,
            outcome_status text NOT NULL,
            note text,
            evidence_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT dream_prediction_outcomes_status_check CHECK (
                outcome_status = ANY (ARRAY[
                    'confirmed'::text,
                    'contradicted'::text,
                    'request_more_evidence'::text
                ])
            )
        )
        """
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_dream_prediction_outcomes_prediction_id ON {prefix}dream_prediction_outcomes (prediction_id, created_at DESC)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_dream_prediction_outcomes_bank_created ON {prefix}dream_prediction_outcomes (bank_id, created_at DESC)"
    )


def downgrade() -> None:
    prefix = _schema_prefix()
    op.execute(f"DROP TABLE IF EXISTS {prefix}dream_prediction_outcomes")
    op.execute(f"DROP TABLE IF EXISTS {prefix}dream_proposals")
    op.execute(f"DROP TABLE IF EXISTS {prefix}dream_predictions")
    op.execute(f"DROP TABLE IF EXISTS {prefix}dream_runs")
