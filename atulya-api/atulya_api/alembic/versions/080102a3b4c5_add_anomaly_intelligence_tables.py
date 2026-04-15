"""Add anomaly intelligence tables.

Revision ID: 080102a3b4c5
Revises: 080101a2b3c4
Create Date: 2026-04-15
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "080102a3b4c5"
down_revision: str | Sequence[str] | None = "080101a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else "public."


def upgrade() -> None:
    prefix = _schema_prefix()

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}anomaly_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            bank_id text NOT NULL,
            anomaly_type text NOT NULL,
            severity double precision NOT NULL DEFAULT 0.0,
            status text NOT NULL DEFAULT 'open',
            unit_ids uuid[] NOT NULL DEFAULT '{{}}',
            entity_ids uuid[] NOT NULL DEFAULT '{{}}',
            description text NOT NULL,
            metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            detected_at timestamp with time zone NOT NULL DEFAULT now(),
            resolved_at timestamp with time zone,
            resolved_by text,
            CONSTRAINT ae_type_check CHECK (anomaly_type = ANY(ARRAY[
                'contradiction','temporal_inconsistency','entity_inconsistency',
                'flaw_circular','flaw_temporal_violation','flaw_missing_step',
                'flaw_unsupported_opinion','pattern_anti_pattern','pattern_violation'
            ])),
            CONSTRAINT ae_status_check CHECK (status = ANY(ARRAY['open','acknowledged','resolved','suppressed'])),
            CONSTRAINT ae_severity_range CHECK (severity >= 0.0 AND severity <= 1.0)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}anomaly_corrections (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            bank_id text NOT NULL,
            anomaly_id uuid NOT NULL REFERENCES {prefix}anomaly_events(id) ON DELETE CASCADE,
            correction_type text NOT NULL,
            target_unit_id uuid,
            before_state jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            after_state jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            confidence_delta double precision,
            applied_at timestamp with time zone NOT NULL DEFAULT now(),
            applied_by text NOT NULL DEFAULT 'auto',
            CONSTRAINT ac_type_check CHECK (correction_type = ANY(ARRAY[
                'confidence_adjustment','belief_revision','chain_repair_suggestion',
                'pattern_evolution','suppression'
            ]))
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}pattern_library (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            bank_id text,
            name text NOT NULL,
            pattern_type text NOT NULL,
            domain text NOT NULL DEFAULT 'code',
            structure_template jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            semantic_description text NOT NULL,
            semantic_embedding vector(384),
            match_threshold double precision NOT NULL DEFAULT 0.65,
            correction_guidance text,
            improvement_guidance text,
            false_positive_count integer NOT NULL DEFAULT 0,
            true_positive_count integer NOT NULL DEFAULT 0,
            is_active boolean NOT NULL DEFAULT true,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now(),
            CONSTRAINT pl_type_check CHECK (pattern_type = ANY(ARRAY['pattern','anti_pattern','best_practice'])),
            CONSTRAINT pl_domain_check CHECK (domain = ANY(ARRAY['code','memory','reasoning']))
        )
        """
    )

    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_anomaly_events_bank_status_time ON {prefix}anomaly_events (bank_id, status, detected_at DESC)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_anomaly_events_bank_type ON {prefix}anomaly_events (bank_id, anomaly_type)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_anomaly_events_unit_ids_gin ON {prefix}anomaly_events USING GIN (unit_ids)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_anomaly_events_entity_ids_gin ON {prefix}anomaly_events USING GIN (entity_ids)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_anomaly_corrections_anomaly ON {prefix}anomaly_corrections (anomaly_id)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_anomaly_corrections_bank_type ON {prefix}anomaly_corrections (bank_id, correction_type)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_anomaly_corrections_target_unit ON {prefix}anomaly_corrections (target_unit_id) WHERE target_unit_id IS NOT NULL"
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_pattern_library_embedding_hnsw ON {prefix}pattern_library
        USING hnsw (semantic_embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)
        """
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_pattern_library_bank_domain_active ON {prefix}pattern_library (bank_id, domain, is_active)"
    )

    # Minimal default patterns to bootstrap matching.
    op.execute(
        f"""
        INSERT INTO {prefix}pattern_library (
            bank_id, name, pattern_type, domain, structure_template, semantic_description, match_threshold,
            correction_guidance, improvement_guidance
        ) VALUES
            (NULL, 'Unsupported opinion without evidence', 'anti_pattern', 'memory', jsonb_build_object('fact_type', 'opinion', 'requires_support', true),
             'Opinion statements should be backed by supporting world or experience evidence.',
             0.62, 'Add evidence references for opinion memories.', 'Prefer evidence-first claims in retain input.'),
            (NULL, 'Circular causal chain', 'anti_pattern', 'reasoning', jsonb_build_object('causal_cycle', true),
             'Reasoning graph should avoid circular cause and effect loops.',
             0.70, 'Break cycle by introducing independent evidence or chronology.', 'Validate causal direction before storing links.')
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    prefix = _schema_prefix()
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_pattern_library_bank_domain_active")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_pattern_library_embedding_hnsw")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_anomaly_corrections_target_unit")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_anomaly_corrections_bank_type")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_anomaly_corrections_anomaly")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_anomaly_events_entity_ids_gin")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_anomaly_events_unit_ids_gin")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_anomaly_events_bank_type")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_anomaly_events_bank_status_time")
    op.execute(f"DROP TABLE IF EXISTS {prefix}pattern_library")
    op.execute(f"DROP TABLE IF EXISTS {prefix}anomaly_corrections")
    op.execute(f"DROP TABLE IF EXISTS {prefix}anomaly_events")
