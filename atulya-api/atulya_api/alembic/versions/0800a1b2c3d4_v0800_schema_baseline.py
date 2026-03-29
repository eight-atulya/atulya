"""Atulya v0.8.0 schema baseline.

Revision ID: 0800a1b2c3d4
Revises:
Create Date: 2026-03-27

This baseline replaces all pre-v0.8.0 migrations. Fresh databases start here.
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "0800a1b2c3d4"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else "public."


def _ddl(sql: str) -> str:
    return sql.replace("public.", _schema_prefix())


def upgrade() -> None:
    statements = (
        "CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public",
        "CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public",
        """
        CREATE TABLE public.banks (
            bank_id text NOT NULL,
            name text,
            disposition jsonb DEFAULT '{"empathy": 3, "literalism": 3, "skepticism": 3}'::jsonb NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            updated_at timestamp with time zone DEFAULT now() NOT NULL,
            mission text,
            last_consolidated_at timestamp with time zone,
            mission_changed_at timestamp with time zone,
            config jsonb DEFAULT '{}'::jsonb NOT NULL
        )
        """,
        """
        CREATE TABLE public.file_storage (
            storage_key text NOT NULL,
            data bytea NOT NULL
        )
        """,
        """
        CREATE TABLE public.documents (
            id text NOT NULL,
            bank_id text NOT NULL,
            original_text text,
            content_hash text,
            metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            updated_at timestamp with time zone DEFAULT now() NOT NULL,
            retain_params jsonb,
            tags character varying[] DEFAULT '{}'::character varying[] NOT NULL,
            file_storage_key text,
            file_original_name text,
            file_content_type text
        )
        """,
        """
        CREATE TABLE public.entities (
            id uuid DEFAULT gen_random_uuid() NOT NULL,
            canonical_name text NOT NULL,
            bank_id text NOT NULL,
            metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
            first_seen timestamp with time zone DEFAULT now() NOT NULL,
            last_seen timestamp with time zone DEFAULT now() NOT NULL,
            mention_count integer DEFAULT 1 NOT NULL
        )
        """,
        """
        CREATE TABLE public.async_operations (
            operation_id uuid DEFAULT gen_random_uuid() NOT NULL,
            bank_id text NOT NULL,
            operation_type text NOT NULL,
            status text DEFAULT 'pending'::text NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            updated_at timestamp with time zone DEFAULT now() NOT NULL,
            completed_at timestamp with time zone,
            error_message text,
            result_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
            result_payload jsonb,
            worker_id text,
            claimed_at timestamp with time zone,
            retry_count integer DEFAULT 0 NOT NULL,
            task_payload jsonb,
            next_retry_at timestamp with time zone
        )
        """,
        """
        CREATE TABLE public.webhooks (
            id uuid DEFAULT gen_random_uuid() NOT NULL,
            bank_id text,
            url text NOT NULL,
            secret text,
            event_types text[] DEFAULT '{}'::text[] NOT NULL,
            enabled boolean DEFAULT true NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            updated_at timestamp with time zone DEFAULT now() NOT NULL,
            http_config jsonb DEFAULT '{}'::jsonb NOT NULL
        )
        """,
        """
        CREATE TABLE public.dream_artifacts (
            id uuid DEFAULT gen_random_uuid() NOT NULL,
            bank_id text NOT NULL,
            run_type text NOT NULL,
            trigger_source text DEFAULT 'event'::text NOT NULL,
            html_blob text NOT NULL,
            input_refs jsonb DEFAULT '[]'::jsonb NOT NULL,
            stats jsonb DEFAULT '{}'::jsonb NOT NULL,
            quality_score double precision DEFAULT 0.0 NOT NULL,
            distilled_written boolean DEFAULT false NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL
        )
        """,
        """
        CREATE TABLE public.directives (
            id uuid DEFAULT gen_random_uuid() NOT NULL,
            bank_id character varying(64) NOT NULL,
            name character varying(256) NOT NULL,
            content text NOT NULL,
            priority integer DEFAULT 0 NOT NULL,
            is_active boolean DEFAULT true NOT NULL,
            tags character varying[] DEFAULT ARRAY[]::character varying[],
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            updated_at timestamp with time zone DEFAULT now() NOT NULL
        )
        """,
        """
        CREATE TABLE public.mental_models (
            id text DEFAULT gen_random_uuid() NOT NULL,
            bank_id character varying(64) NOT NULL,
            name character varying(256) NOT NULL,
            source_query text NOT NULL,
            content text NOT NULL,
            embedding vector(384),
            tags character varying[] DEFAULT ARRAY[]::character varying[],
            last_refreshed_at timestamp with time zone DEFAULT now() NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, (((COALESCE(name, ''::character varying))::text || ' '::text) || content))) STORED,
            reflect_response jsonb,
            max_tokens integer DEFAULT 2048 NOT NULL,
            trigger jsonb DEFAULT '{"refresh_after_consolidation": false}'::jsonb NOT NULL,
            history jsonb DEFAULT '[]'::jsonb,
            access_count integer DEFAULT 0 NOT NULL,
            last_accessed_at timestamp with time zone,
            influence_features jsonb DEFAULT '{}'::jsonb NOT NULL,
            influence_score double precision DEFAULT 0.0 NOT NULL
        )
        """,
        """
        CREATE TABLE public.chunks (
            chunk_id text NOT NULL,
            document_id text NOT NULL,
            bank_id text NOT NULL,
            chunk_index integer NOT NULL,
            chunk_text text NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            access_count integer DEFAULT 0 NOT NULL,
            last_accessed_at timestamp with time zone,
            influence_features jsonb DEFAULT '{}'::jsonb NOT NULL,
            influence_score double precision DEFAULT 0.0 NOT NULL
        )
        """,
        """
        CREATE TABLE public.entity_cooccurrences (
            entity_id_1 uuid NOT NULL,
            entity_id_2 uuid NOT NULL,
            cooccurrence_count integer DEFAULT 1 NOT NULL,
            last_cooccurred timestamp with time zone DEFAULT now() NOT NULL
        )
        """,
        """
        CREATE TABLE public.memory_units (
            id uuid DEFAULT gen_random_uuid() NOT NULL,
            bank_id text NOT NULL,
            document_id text,
            text text NOT NULL,
            embedding vector(384),
            context text,
            event_date timestamp with time zone,
            occurred_start timestamp with time zone,
            occurred_end timestamp with time zone,
            mentioned_at timestamp with time zone,
            fact_type text DEFAULT 'world'::text NOT NULL,
            confidence_score double precision,
            access_count integer DEFAULT 0 NOT NULL,
            metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            updated_at timestamp with time zone DEFAULT now() NOT NULL,
            chunk_id text,
            tags character varying[] DEFAULT '{}'::character varying[] NOT NULL,
            proof_count integer DEFAULT 1,
            source_memory_ids uuid[] DEFAULT ARRAY[]::uuid[],
            history jsonb DEFAULT '[]'::jsonb,
            consolidated_at timestamp with time zone,
            observation_scopes jsonb,
            text_signals text,
            search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, ((((COALESCE(text, ''::text) || ' '::text) || COALESCE(context, ''::text)) || ' '::text) || COALESCE(text_signals, ''::text)))) STORED,
            last_accessed_at timestamp with time zone,
            influence_features jsonb DEFAULT '{}'::jsonb NOT NULL,
            influence_score double precision DEFAULT 0.0 NOT NULL
        )
        """,
        """
        CREATE TABLE public.memory_links (
            from_unit_id uuid NOT NULL,
            to_unit_id uuid NOT NULL,
            link_type text NOT NULL,
            entity_id uuid,
            weight double precision DEFAULT '1'::double precision NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL
        )
        """,
        """
        CREATE TABLE public.unit_entities (
            unit_id uuid NOT NULL,
            entity_id uuid NOT NULL
        )
        """,
        """
        ALTER TABLE ONLY public.banks ADD CONSTRAINT pk_banks PRIMARY KEY (bank_id)
        """,
        """
        ALTER TABLE ONLY public.file_storage ADD CONSTRAINT file_storage_pkey PRIMARY KEY (storage_key)
        """,
        """
        ALTER TABLE ONLY public.documents ADD CONSTRAINT pk_documents PRIMARY KEY (id, bank_id)
        """,
        """
        ALTER TABLE ONLY public.entities ADD CONSTRAINT pk_entities PRIMARY KEY (id)
        """,
        """
        ALTER TABLE ONLY public.async_operations ADD CONSTRAINT pk_async_operations PRIMARY KEY (operation_id)
        """,
        """
        ALTER TABLE ONLY public.async_operations ADD CONSTRAINT async_operations_status_check CHECK (status = ANY (ARRAY['pending'::text, 'processing'::text, 'completed'::text, 'failed'::text]))
        """,
        """
        ALTER TABLE ONLY public.webhooks ADD CONSTRAINT webhooks_pkey PRIMARY KEY (id)
        """,
        """
        ALTER TABLE ONLY public.dream_artifacts ADD CONSTRAINT dream_artifacts_pkey PRIMARY KEY (id)
        """,
        """
        ALTER TABLE ONLY public.directives ADD CONSTRAINT directives_pkey PRIMARY KEY (id)
        """,
        """
        ALTER TABLE ONLY public.directives ADD CONSTRAINT fk_directives_bank_id FOREIGN KEY (bank_id) REFERENCES banks(bank_id) ON DELETE CASCADE
        """,
        """
        ALTER TABLE ONLY public.mental_models ADD CONSTRAINT mental_models_pkey PRIMARY KEY (bank_id, id)
        """,
        """
        ALTER TABLE ONLY public.mental_models ADD CONSTRAINT fk_mental_models_bank_id FOREIGN KEY (bank_id) REFERENCES banks(bank_id) ON DELETE CASCADE
        """,
        """
        ALTER TABLE ONLY public.chunks ADD CONSTRAINT pk_chunks PRIMARY KEY (chunk_id)
        """,
        """
        ALTER TABLE ONLY public.chunks ADD CONSTRAINT chunks_document_fkey FOREIGN KEY (document_id, bank_id) REFERENCES documents(id, bank_id) ON DELETE CASCADE
        """,
        """
        ALTER TABLE ONLY public.entity_cooccurrences ADD CONSTRAINT pk_entity_cooccurrences PRIMARY KEY (entity_id_1, entity_id_2)
        """,
        """
        ALTER TABLE ONLY public.entity_cooccurrences ADD CONSTRAINT fk_entity_cooccurrences_entity_id_1_entities FOREIGN KEY (entity_id_1) REFERENCES entities(id) ON DELETE CASCADE
        """,
        """
        ALTER TABLE ONLY public.entity_cooccurrences ADD CONSTRAINT fk_entity_cooccurrences_entity_id_2_entities FOREIGN KEY (entity_id_2) REFERENCES entities(id) ON DELETE CASCADE
        """,
        """
        ALTER TABLE ONLY public.entity_cooccurrences ADD CONSTRAINT entity_cooccurrence_order_check CHECK (entity_id_1 < entity_id_2)
        """,
        """
        ALTER TABLE ONLY public.memory_units ADD CONSTRAINT pk_memory_units PRIMARY KEY (id)
        """,
        """
        ALTER TABLE ONLY public.memory_units ADD CONSTRAINT memory_units_chunk_fkey FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id) ON DELETE SET NULL
        """,
        """
        ALTER TABLE ONLY public.memory_units ADD CONSTRAINT memory_units_document_fkey FOREIGN KEY (document_id, bank_id) REFERENCES documents(id, bank_id) ON DELETE CASCADE
        """,
        """
        ALTER TABLE ONLY public.memory_units ADD CONSTRAINT confidence_score_fact_type_check CHECK (fact_type = 'opinion'::text AND confidence_score IS NOT NULL OR fact_type = 'observation'::text OR (fact_type <> ALL (ARRAY['opinion'::text, 'observation'::text])) AND confidence_score IS NULL)
        """,
        """
        ALTER TABLE ONLY public.memory_units ADD CONSTRAINT memory_units_confidence_range_check CHECK (confidence_score IS NULL OR confidence_score >= 0.0::double precision AND confidence_score <= 1.0::double precision)
        """,
        """
        ALTER TABLE ONLY public.memory_units ADD CONSTRAINT memory_units_fact_type_check CHECK (fact_type = ANY (ARRAY['world'::text, 'experience'::text, 'opinion'::text, 'observation'::text]))
        """,
        """
        ALTER TABLE ONLY public.memory_links ADD CONSTRAINT fk_memory_links_entity_id_entities FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
        """,
        """
        ALTER TABLE ONLY public.memory_links ADD CONSTRAINT fk_memory_links_from_unit_id_memory_units FOREIGN KEY (from_unit_id) REFERENCES memory_units(id) ON DELETE CASCADE
        """,
        """
        ALTER TABLE ONLY public.memory_links ADD CONSTRAINT fk_memory_links_to_unit_id_memory_units FOREIGN KEY (to_unit_id) REFERENCES memory_units(id) ON DELETE CASCADE
        """,
        """
        ALTER TABLE ONLY public.memory_links ADD CONSTRAINT memory_links_link_type_check CHECK (link_type = ANY (ARRAY['temporal'::text, 'semantic'::text, 'entity'::text, 'causes'::text, 'caused_by'::text, 'enables'::text, 'prevents'::text]))
        """,
        """
        ALTER TABLE ONLY public.memory_links ADD CONSTRAINT memory_links_weight_check CHECK (weight >= 0.0::double precision AND weight <= 1.0::double precision)
        """,
        """
        ALTER TABLE ONLY public.unit_entities ADD CONSTRAINT pk_unit_entities PRIMARY KEY (unit_id, entity_id)
        """,
        """
        ALTER TABLE ONLY public.unit_entities ADD CONSTRAINT fk_unit_entities_entity_id_entities FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
        """,
        """
        ALTER TABLE ONLY public.unit_entities ADD CONSTRAINT fk_unit_entities_unit_id_memory_units FOREIGN KEY (unit_id) REFERENCES memory_units(id) ON DELETE CASCADE
        """,
        """
        CREATE MATERIALIZED VIEW public.memory_units_bm25 AS
         SELECT id,
            bank_id,
            text,
            to_tsvector('english'::regconfig, text) AS text_vector,
            log(1.0::double precision + length(text)::double precision / (( SELECT avg(length(memory_units_1.text)) AS avg
                   FROM memory_units memory_units_1))::double precision) AS doc_length_factor
           FROM memory_units
        """,
        """
        CREATE INDEX idx_async_operations_bank_id ON public.async_operations USING btree (bank_id)
        """,
        """
        CREATE INDEX idx_async_operations_bank_status ON public.async_operations USING btree (bank_id, status)
        """,
        """
        CREATE INDEX idx_async_operations_pending_claim ON public.async_operations USING btree (status, created_at) WHERE ((status = 'pending'::text) AND (task_payload IS NOT NULL))
        """,
        """
        CREATE INDEX idx_async_operations_result_metadata ON public.async_operations USING gin (result_metadata)
        """,
        """
        CREATE INDEX idx_async_operations_status ON public.async_operations USING btree (status)
        """,
        """
        CREATE INDEX idx_async_operations_status_retry ON public.async_operations USING btree (status, next_retry_at)
        """,
        """
        CREATE INDEX idx_async_operations_worker_id ON public.async_operations USING btree (worker_id) WHERE (worker_id IS NOT NULL)
        """,
        """
        CREATE INDEX idx_banks_config ON public.banks USING gin (config)
        """,
        """
        CREATE INDEX idx_chunks_access_count ON public.chunks USING btree (access_count DESC)
        """,
        """
        CREATE INDEX idx_chunks_bank_id ON public.chunks USING btree (bank_id)
        """,
        """
        CREATE INDEX idx_chunks_document_id ON public.chunks USING btree (document_id)
        """,
        """
        CREATE INDEX idx_directives_bank_active ON public.directives USING btree (bank_id, is_active)
        """,
        """
        CREATE INDEX idx_directives_bank_id ON public.directives USING btree (bank_id)
        """,
        """
        CREATE INDEX idx_directives_tags ON public.directives USING gin (tags)
        """,
        """
        CREATE INDEX idx_documents_bank_id ON public.documents USING btree (bank_id)
        """,
        """
        CREATE INDEX idx_documents_content_hash ON public.documents USING btree (content_hash)
        """,
        """
        CREATE INDEX idx_documents_retain_params ON public.documents USING gin (retain_params)
        """,
        """
        CREATE INDEX idx_dream_artifacts_bank_created ON public.dream_artifacts USING btree (bank_id, created_at DESC)
        """,
        """
        CREATE INDEX entities_canonical_name_trgm_idx ON public.entities USING gin (canonical_name gin_trgm_ops)
        """,
        """
        CREATE INDEX idx_entities_bank_id ON public.entities USING btree (bank_id)
        """,
        """
        CREATE UNIQUE INDEX idx_entities_bank_lower_name ON public.entities USING btree (bank_id, lower(canonical_name))
        """,
        """
        CREATE INDEX idx_entities_bank_name ON public.entities USING btree (bank_id, canonical_name)
        """,
        """
        CREATE INDEX idx_entities_canonical_name ON public.entities USING btree (canonical_name)
        """,
        """
        CREATE INDEX idx_entity_cooccurrences_count ON public.entity_cooccurrences USING btree (cooccurrence_count DESC)
        """,
        """
        CREATE INDEX idx_entity_cooccurrences_entity1 ON public.entity_cooccurrences USING btree (entity_id_1)
        """,
        """
        CREATE INDEX idx_entity_cooccurrences_entity2 ON public.entity_cooccurrences USING btree (entity_id_2)
        """,
        """
        CREATE INDEX idx_memory_links_entity ON public.memory_links USING btree (entity_id)
        """,
        """
        CREATE INDEX idx_memory_links_entity_covering ON public.memory_links USING btree (from_unit_id) INCLUDE (to_unit_id, entity_id) WHERE (link_type = 'entity'::text)
        """,
        """
        CREATE INDEX idx_memory_links_from_type_weight ON public.memory_links USING btree (from_unit_id, link_type, weight DESC)
        """,
        """
        CREATE INDEX idx_memory_links_from_unit ON public.memory_links USING btree (from_unit_id)
        """,
        """
        CREATE INDEX idx_memory_links_link_type ON public.memory_links USING btree (link_type)
        """,
        """
        CREATE INDEX idx_memory_links_to_type_weight ON public.memory_links USING btree (to_unit_id, link_type, weight DESC)
        """,
        """
        CREATE INDEX idx_memory_links_to_unit ON public.memory_links USING btree (to_unit_id)
        """,
        """
        CREATE UNIQUE INDEX idx_memory_links_unique ON public.memory_links USING btree (from_unit_id, to_unit_id, link_type, COALESCE(entity_id, '00000000-0000-0000-0000-000000000000'::uuid))
        """,
        """
        CREATE INDEX idx_memory_units_access_count ON public.memory_units USING btree (access_count DESC)
        """,
        """
        CREATE INDEX idx_memory_units_bank_date ON public.memory_units USING btree (bank_id, event_date DESC)
        """,
        """
        CREATE INDEX idx_memory_units_bank_fact_type ON public.memory_units USING btree (bank_id, fact_type)
        """,
        """
        CREATE INDEX idx_memory_units_bank_id ON public.memory_units USING btree (bank_id)
        """,
        """
        CREATE INDEX idx_memory_units_bank_mentioned_at ON public.memory_units USING btree (bank_id, fact_type, mentioned_at) WHERE (mentioned_at IS NOT NULL)
        """,
        """
        CREATE INDEX idx_memory_units_bank_occurred_end ON public.memory_units USING btree (bank_id, fact_type, occurred_end) WHERE (occurred_end IS NOT NULL)
        """,
        """
        CREATE INDEX idx_memory_units_bank_occurred_start ON public.memory_units USING btree (bank_id, fact_type, occurred_start) WHERE (occurred_start IS NOT NULL)
        """,
        """
        CREATE INDEX idx_memory_units_bank_type_date ON public.memory_units USING btree (bank_id, fact_type, event_date DESC)
        """,
        """
        CREATE INDEX idx_memory_units_chunk_id ON public.memory_units USING btree (chunk_id)
        """,
        """
        CREATE INDEX idx_memory_units_document_id ON public.memory_units USING btree (document_id)
        """,
        """
        CREATE INDEX idx_memory_units_embedding ON public.memory_units USING hnsw (embedding vector_cosine_ops)
        """,
        """
        CREATE INDEX idx_memory_units_event_date ON public.memory_units USING btree (event_date DESC)
        """,
        """
        CREATE INDEX idx_memory_units_fact_type ON public.memory_units USING btree (fact_type)
        """,
        """
        CREATE INDEX idx_memory_units_last_accessed_at ON public.memory_units USING btree (last_accessed_at DESC)
        """,
        """
        CREATE INDEX idx_memory_units_observations ON public.memory_units USING btree (bank_id, fact_type) WHERE (fact_type = 'observation'::text)
        """,
        """
        CREATE INDEX idx_memory_units_opinion_confidence ON public.memory_units USING btree (bank_id, confidence_score DESC) WHERE (fact_type = 'opinion'::text)
        """,
        """
        CREATE INDEX idx_memory_units_opinion_date ON public.memory_units USING btree (bank_id, event_date DESC) WHERE (fact_type = 'opinion'::text)
        """,
        """
        CREATE INDEX idx_memory_units_source_memory_ids ON public.memory_units USING gin (source_memory_ids) WHERE (source_memory_ids IS NOT NULL)
        """,
        """
        CREATE INDEX idx_memory_units_tags ON public.memory_units USING gin (tags)
        """,
        """
        CREATE INDEX idx_memory_units_text_search ON public.memory_units USING gin (search_vector)
        """,
        """
        CREATE INDEX idx_memory_units_unconsolidated ON public.memory_units USING btree (bank_id, created_at) WHERE ((consolidated_at IS NULL) AND (fact_type = ANY (ARRAY['experience'::text, 'world'::text])))
        """,
        """
        CREATE INDEX idx_memory_units_bm25_bank ON public.memory_units_bm25 USING btree (bank_id)
        """,
        """
        CREATE INDEX idx_memory_units_bm25_text_vector ON public.memory_units_bm25 USING gin (text_vector)
        """,
        """
        CREATE INDEX idx_mental_models_access_count ON public.mental_models USING btree (access_count DESC)
        """,
        """
        CREATE INDEX idx_mental_models_bank_id ON public.mental_models USING btree (bank_id)
        """,
        """
        CREATE INDEX idx_mental_models_embedding ON public.mental_models USING hnsw (embedding vector_cosine_ops)
        """,
        """
        CREATE INDEX idx_mental_models_tags ON public.mental_models USING gin (tags)
        """,
        """
        CREATE INDEX idx_mental_models_text_search ON public.mental_models USING gin (search_vector)
        """,
        """
        CREATE INDEX idx_unit_entities_entity ON public.unit_entities USING btree (entity_id)
        """,
        """
        CREATE INDEX idx_unit_entities_unit ON public.unit_entities USING btree (unit_id)
        """,
        """
        CREATE INDEX idx_webhooks_bank_id ON public.webhooks USING btree (bank_id)
        """,
    )

    for statement in statements:
        op.execute(_ddl(statement))


def downgrade() -> None:
    statements = (
        "DROP MATERIALIZED VIEW IF EXISTS public.memory_units_bm25",
        "DROP TABLE IF EXISTS public.unit_entities CASCADE",
        "DROP TABLE IF EXISTS public.memory_links CASCADE",
        "DROP TABLE IF EXISTS public.memory_units CASCADE",
        "DROP TABLE IF EXISTS public.entity_cooccurrences CASCADE",
        "DROP TABLE IF EXISTS public.chunks CASCADE",
        "DROP TABLE IF EXISTS public.mental_models CASCADE",
        "DROP TABLE IF EXISTS public.directives CASCADE",
        "DROP TABLE IF EXISTS public.dream_artifacts CASCADE",
        "DROP TABLE IF EXISTS public.webhooks CASCADE",
        "DROP TABLE IF EXISTS public.async_operations CASCADE",
        "DROP TABLE IF EXISTS public.entities CASCADE",
        "DROP TABLE IF EXISTS public.documents CASCADE",
        "DROP TABLE IF EXISTS public.file_storage CASCADE",
        "DROP TABLE IF EXISTS public.banks CASCADE",
    )

    for statement in statements:
        op.execute(_ddl(statement))
