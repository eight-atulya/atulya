"""
SQLAlchemy models for the memory system.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID as PyUUID


@dataclass
class RequestContext:
    """
    Context for request authentication and authorization.

    This dataclass carries authentication data from HTTP requests to the
    memory engine operations. It can be extended to include additional
    context like headers, tokens, user info, etc.
    """

    api_key: str | None = None
    api_key_id: str | None = None  # UUID of the API key used for authentication
    tenant_id: str | None = None  # Tenant identifier (set by extension after auth)
    org_id: str | None = None
    membership_id: str | None = None
    principal_id: str | None = None
    principal_type: str | None = None
    display_name: str | None = None
    email: str | None = None
    role: str = "user"
    schema_name: str | None = None
    internal: bool = False  # True for background/internal operations (skips extension auth)
    user_initiated: bool = False  # True for async operations that originated from a user request
    allowed_bank_ids: list[str] | None = None  # None = unrestricted (all banks)
    allowed_actions: list[str] | None = None
    action_scopes: dict[str, list[str]] | None = None

    @classmethod
    def system_internal(cls, *, schema_name: str | None = None) -> "RequestContext":
        """Create an explicit, non-user context for trusted system work.

        Internal jobs must opt into this identity explicitly. Anonymous
        ``internal=True`` contexts remain unable to pass RBAC/ABAC checks.
        """
        return cls(
            internal=True,
            role="superuser",
            schema_name=schema_name,
            allowed_actions=["system.admin"],
            action_scopes={"system.admin": ["system:*"]},
        )

    def to_task_authorization(self) -> dict[str, Any]:
        """Return the non-secret authorization envelope for a queued task.

        Workers must not receive a session or API-key secret.  They do need the
        already-resolved identity and permission boundary that was authorized
        when the task was accepted, so an async operation cannot accidentally
        become anonymous after the request has ended.
        """
        return {
            "version": 1,
            "tenant_id": self.tenant_id,
            "org_id": self.org_id,
            "membership_id": self.membership_id,
            "principal_id": self.principal_id,
            "principal_type": self.principal_type,
            "display_name": self.display_name,
            "email": self.email,
            "role": self.role,
            "schema_name": self.schema_name,
            "api_key_id": self.api_key_id,
            "allowed_bank_ids": list(self.allowed_bank_ids) if self.allowed_bank_ids is not None else None,
            "allowed_actions": list(self.allowed_actions) if self.allowed_actions is not None else None,
            "action_scopes": {action: list(scopes) for action, scopes in (self.action_scopes or {}).items()},
            "user_initiated": self.user_initiated,
        }

    @classmethod
    def from_task_payload(cls, task_payload: dict[str, Any]) -> "RequestContext":
        """Restore a worker context without ever restoring a raw credential.

        The legacy fields remain as a compatibility fallback for tasks queued
        before authorization envelopes were introduced.  Such tasks retain
        their old behavior and are still subject to normal operation checks.
        """
        snapshot = task_payload.get("_authorization")
        if not isinstance(snapshot, dict):
            return cls(
                internal=True,
                user_initiated=True,
                tenant_id=task_payload.get("_tenant_id"),
                api_key_id=task_payload.get("_api_key_id"),
            )

        def string_value(name: str) -> str | None:
            value = snapshot.get(name)
            return value if isinstance(value, str) else None

        def string_list(name: str) -> list[str] | None:
            value = snapshot.get(name)
            if value is None:
                return None
            return [item for item in value if isinstance(item, str)] if isinstance(value, list) else None

        raw_scopes = snapshot.get("action_scopes")
        action_scopes = (
            {
                action: [scope for scope in scopes if isinstance(scope, str)]
                for action, scopes in raw_scopes.items()
                if isinstance(action, str) and isinstance(scopes, list)
            }
            if isinstance(raw_scopes, dict)
            else None
        )

        return cls(
            internal=True,
            user_initiated=bool(snapshot.get("user_initiated", True)),
            tenant_id=string_value("tenant_id"),
            org_id=string_value("org_id"),
            membership_id=string_value("membership_id"),
            principal_id=string_value("principal_id"),
            principal_type=string_value("principal_type"),
            display_name=string_value("display_name"),
            email=string_value("email"),
            role=string_value("role") or "user",
            schema_name=string_value("schema_name"),
            api_key_id=string_value("api_key_id"),
            allowed_bank_ids=string_list("allowed_bank_ids"),
            allowed_actions=string_list("allowed_actions"),
            action_scopes=action_scopes,
        )


from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .config import EMBEDDING_DIMENSION


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all models."""

    pass


class Document(Base):
    """Source documents for memory units."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    bank_id: Mapped[str] = mapped_column(Text, primary_key=True)
    original_text: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(Text)
    doc_metadata: Mapped[dict] = mapped_column("metadata", JSONB, server_default=sql_text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    memory_units = relationship("MemoryUnit", back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_documents_bank_id", "bank_id"),
        Index("idx_documents_content_hash", "content_hash"),
    )


class MemoryUnit(Base):
    """Individual sentence-level memories."""

    __tablename__ = "memory_units"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sql_text("gen_random_uuid()")
    )
    bank_id: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(EMBEDDING_DIMENSION))  # pgvector type
    context: Mapped[str | None] = mapped_column(Text)
    event_date: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )  # Kept for backward compatibility
    occurred_start: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True)
    )  # When fact occurred (range start)
    occurred_end: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))  # When fact occurred (range end)
    mentioned_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))  # When fact was mentioned
    timeline_anchor_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    timeline_anchor_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'recorded_only'"))
    temporal_direction: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'atemporal'"))
    temporal_confidence: Mapped[float | None] = mapped_column(Float)
    temporal_reference_text: Mapped[str | None] = mapped_column(Text)
    fact_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="world")
    confidence_score: Mapped[float | None] = mapped_column(Float)
    unit_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, server_default=sql_text("'{}'::jsonb")
    )  # User-defined metadata (str->str)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    document = relationship("Document", back_populates="memory_units")
    unit_entities = relationship("UnitEntity", back_populates="memory_unit", cascade="all, delete-orphan")
    outgoing_links = relationship(
        "MemoryLink", foreign_keys="MemoryLink.from_unit_id", back_populates="from_unit", cascade="all, delete-orphan"
    )
    incoming_links = relationship(
        "MemoryLink", foreign_keys="MemoryLink.to_unit_id", back_populates="to_unit", cascade="all, delete-orphan"
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "bank_id"],
            ["documents.id", "documents.bank_id"],
            name="memory_units_document_fkey",
            ondelete="CASCADE",
        ),
        CheckConstraint("fact_type IN ('world', 'experience', 'opinion', 'observation')"),
        CheckConstraint("confidence_score IS NULL OR (confidence_score >= 0.0 AND confidence_score <= 1.0)"),
        CheckConstraint(
            "(fact_type = 'opinion' AND confidence_score IS NOT NULL) OR "
            "(fact_type = 'observation') OR "
            "(fact_type NOT IN ('opinion', 'observation') AND confidence_score IS NULL)",
            name="confidence_score_fact_type_check",
        ),
        Index("idx_memory_units_bank_id", "bank_id"),
        Index("idx_memory_units_document_id", "document_id"),
        Index("idx_memory_units_event_date", "event_date", postgresql_ops={"event_date": "DESC"}),
        Index("idx_memory_units_bank_date", "bank_id", "event_date", postgresql_ops={"event_date": "DESC"}),
        Index("idx_memory_units_fact_type", "fact_type"),
        Index("idx_memory_units_bank_fact_type", "bank_id", "fact_type"),
        Index(
            "idx_memory_units_bank_type_date",
            "bank_id",
            "fact_type",
            "event_date",
            postgresql_ops={"event_date": "DESC"},
        ),
        Index(
            "idx_memory_units_opinion_confidence",
            "bank_id",
            "confidence_score",
            postgresql_where=sql_text("fact_type = 'opinion'"),
            postgresql_ops={"confidence_score": "DESC"},
        ),
        Index(
            "idx_memory_units_opinion_date",
            "bank_id",
            "event_date",
            postgresql_where=sql_text("fact_type = 'opinion'"),
            postgresql_ops={"event_date": "DESC"},
        ),
        Index(
            "idx_memory_units_observation_date",
            "bank_id",
            "event_date",
            postgresql_where=sql_text("fact_type = 'observation'"),
            postgresql_ops={"event_date": "DESC"},
        ),
        Index(
            "idx_memory_units_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class Entity(Base):
    """Resolved entities (people, organizations, locations, etc.)."""

    __tablename__ = "entities"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sql_text("gen_random_uuid()")
    )
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    bank_id: Mapped[str] = mapped_column(Text, nullable=False)
    entity_metadata: Mapped[dict] = mapped_column("metadata", JSONB, server_default=sql_text("'{}'::jsonb"))
    first_seen: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    mention_count: Mapped[int] = mapped_column(Integer, server_default="1")

    # Relationships
    unit_entities = relationship("UnitEntity", back_populates="entity", cascade="all, delete-orphan")
    memory_links = relationship("MemoryLink", back_populates="entity", cascade="all, delete-orphan")
    cooccurrences_1 = relationship(
        "EntityCooccurrence",
        foreign_keys="EntityCooccurrence.entity_id_1",
        back_populates="entity_1",
        cascade="all, delete-orphan",
    )
    cooccurrences_2 = relationship(
        "EntityCooccurrence",
        foreign_keys="EntityCooccurrence.entity_id_2",
        back_populates="entity_2",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_entities_bank_id", "bank_id"),
        Index("idx_entities_canonical_name", "canonical_name"),
        Index("idx_entities_bank_name", "bank_id", "canonical_name"),
    )


class UnitEntity(Base):
    """Association between memory units and entities."""

    __tablename__ = "unit_entities"

    unit_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_units.id", ondelete="CASCADE"), primary_key=True
    )
    entity_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )

    # Relationships
    memory_unit = relationship("MemoryUnit", back_populates="unit_entities")
    entity = relationship("Entity", back_populates="unit_entities")

    __table_args__ = (
        Index("idx_unit_entities_unit", "unit_id"),
        Index("idx_unit_entities_entity", "entity_id"),
    )


class EntityCooccurrence(Base):
    """Materialized cache of entity co-occurrences."""

    __tablename__ = "entity_cooccurrences"

    entity_id_1: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    entity_id_2: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    cooccurrence_count: Mapped[int] = mapped_column(Integer, server_default="1")
    last_cooccurred: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    entity_1 = relationship("Entity", foreign_keys=[entity_id_1], back_populates="cooccurrences_1")
    entity_2 = relationship("Entity", foreign_keys=[entity_id_2], back_populates="cooccurrences_2")

    __table_args__ = (
        CheckConstraint("entity_id_1 < entity_id_2", name="entity_cooccurrence_order_check"),
        Index("idx_entity_cooccurrences_entity1", "entity_id_1"),
        Index("idx_entity_cooccurrences_entity2", "entity_id_2"),
        Index("idx_entity_cooccurrences_count", "cooccurrence_count", postgresql_ops={"cooccurrence_count": "DESC"}),
    )


class MemoryLink(Base):
    """Links between memory units (temporal, semantic, entity)."""

    __tablename__ = "memory_links"

    from_unit_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_units.id", ondelete="CASCADE"), primary_key=True
    )
    to_unit_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_units.id", ondelete="CASCADE"), primary_key=True
    )
    link_type: Mapped[str] = mapped_column(Text, primary_key=True)
    entity_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    weight: Mapped[float] = mapped_column(Float, nullable=False, server_default="1.0")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    from_unit = relationship("MemoryUnit", foreign_keys=[from_unit_id], back_populates="outgoing_links")
    to_unit = relationship("MemoryUnit", foreign_keys=[to_unit_id], back_populates="incoming_links")
    entity = relationship("Entity", back_populates="memory_links")

    __table_args__ = (
        CheckConstraint(
            "link_type IN ('temporal', 'semantic', 'entity', 'causes', 'caused_by', 'enables', 'prevents')",
            name="memory_links_link_type_check",
        ),
        CheckConstraint("weight >= 0.0 AND weight <= 1.0", name="memory_links_weight_check"),
        Index("idx_memory_links_from", "from_unit_id"),
        Index("idx_memory_links_to", "to_unit_id"),
        Index("idx_memory_links_type", "link_type"),
        Index("idx_memory_links_entity", "entity_id", postgresql_where=sql_text("entity_id IS NOT NULL")),
        Index(
            "idx_memory_links_from_weight",
            "from_unit_id",
            "weight",
            postgresql_where=sql_text("weight >= 0.1"),
            postgresql_ops={"weight": "DESC"},
        ),
    )


class EntityTrajectory(Base):
    """Latest LLM+HMM-style progression snapshot per entity (one row per bank+entity)."""

    __tablename__ = "entity_trajectories"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sql_text("gen_random_uuid()")
    )
    bank_id: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"))
    computed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    state_vocabulary: Mapped[list] = mapped_column(JSONB, nullable=False)
    vocabulary_hash: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    transition_matrix: Mapped[list] = mapped_column(JSONB, nullable=False)
    current_state: Mapped[str] = mapped_column(Text, nullable=False)
    viterbi_path: Mapped[list] = mapped_column(JSONB, nullable=False)
    forecast_horizon: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    forecast_distribution: Mapped[dict] = mapped_column(JSONB, nullable=False)
    forward_log_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    anomaly_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_model: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False, server_default="v1")

    entity = relationship("Entity", backref="trajectory_rows")

    __table_args__ = (
        UniqueConstraint("bank_id", "entity_id", name="uq_entity_trajectories_bank_entity"),
        Index("idx_entity_trajectories_bank_computed", "bank_id", "computed_at"),
    )


class EntityIntelligence(Base):
    """Latest bank-level intelligence synthesized from entities and trajectories."""

    __tablename__ = "entity_intelligence"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sql_text("gen_random_uuid()")
    )
    bank_id: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    entity_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    source_entity_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    entity_snapshot_hash: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    structured_content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    entity_context: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=sql_text("'{}'::jsonb"))
    delta_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=sql_text("'{}'::jsonb"))
    llm_model: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False, server_default="v1")

    __table_args__ = (
        UniqueConstraint("bank_id", name="uq_entity_intelligence_bank"),
        Index("idx_entity_intelligence_computed", "computed_at"),
    )


class Bank(Base):
    """Memory bank profiles with disposition traits and background."""

    __tablename__ = "banks"

    bank_id: Mapped[str] = mapped_column(Text, primary_key=True)
    disposition: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=sql_text('\'{"skepticism": 3, "literalism": 3, "empathy": 3}\'::jsonb')
    )
    background: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_banks_bank_id", "bank_id"),)


class MemoryRepo(Base):
    """Git-like memory repo rooted at a durable bank."""

    __tablename__ = "memory_repos"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sql_text("gen_random_uuid()")
    )
    root_bank_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    active_branch: Mapped[str] = mapped_column(Text, nullable=False, server_default="main")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_memory_repos_root_bank", "root_bank_id"),)


class MemoryObject(Base):
    """Content-addressed repo object payload."""

    __tablename__ = "memory_objects"

    object_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    object_kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class MemoryCommit(Base):
    """Immutable commit snapshot for a memory repo branch."""

    __tablename__ = "memory_commits"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sql_text("gen_random_uuid()")
    )
    repo_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_repos.id", ondelete="CASCADE"), nullable=False
    )
    parent_commit_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_commits.id", ondelete="SET NULL")
    )
    branch_name: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str | None] = mapped_column(Text)
    root_manifest_hash: Mapped[str] = mapped_column(
        Text, ForeignKey("memory_objects.object_hash", ondelete="RESTRICT"), nullable=False
    )
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=sql_text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_memory_commits_repo_branch_created", "repo_id", "branch_name", "created_at"),)


class MemoryRef(Base):
    """Branch head pointer for a memory repo."""

    __tablename__ = "memory_refs"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sql_text("gen_random_uuid()")
    )
    repo_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_repos.id", ondelete="CASCADE"), nullable=False
    )
    ref_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="branch")
    ref_name: Mapped[str] = mapped_column(Text, nullable=False)
    head_commit_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_commits.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("repo_id", "ref_type", "ref_name", name="uq_memory_refs_repo_type_name"),
        Index("idx_memory_refs_repo_type", "repo_id", "ref_type"),
    )


class MemoryWorkspace(Base):
    """Workspace bank backing one memory repo branch."""

    __tablename__ = "memory_workspaces"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sql_text("gen_random_uuid()")
    )
    repo_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_repos.id", ondelete="CASCADE"), nullable=False
    )
    branch_name: Mapped[str] = mapped_column(Text, nullable=False)
    workspace_bank_id: Mapped[str] = mapped_column(Text, nullable=False)
    head_commit_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_commits.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=sql_text("false"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("repo_id", "branch_name", name="uq_memory_workspaces_repo_branch"),
        Index("idx_memory_workspaces_repo_active", "repo_id", "is_active"),
    )
