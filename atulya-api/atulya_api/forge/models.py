"""Canonical Atulya Training Record (ATR) models for Data Forge.

Purpose
    Define the shared training-data contract (ATR) produced by forge recipes
    and consumed by exporters (JSONL, OpenAI chat, graph intelligence). Also
    holds forge job request/status types and export manifests.

Trigger path
    - Recipes in ``forge/recipes/*`` build ``AtulyaTrainingRecord`` instances.
    - ``forge/job.py`` audits records; ``forge/engine.py`` persists and exports.
    - Taste export materializes simplified records then uses same exporters.

Inputs
    - Bank memory snapshots (facts, observations, links, graph) from recipes.
    - ``ForgeJobRequest`` from HTTP/worker with recipe_id, ingest source, options.

Outputs
    - Serialized ATR JSON stored in ``forge_records`` table.
    - ``ExportManifest`` with adapter output and lineage block.

Side effects
    None at model layer.

Mutability
    - ``TrainingLabels`` fields vary by recipe (only relevant label slots populated).
    - ``QualityScore.exportable`` set by ``forge/quality.audit_record``.

Impact radius
    - All training exporters, eval pipelines, and future fine-tune adapters.
    - ``LineageBlock`` ties records to recipe version and optional repo commit.

Core logic
    - ATR bundles timeline context, evidence snapshots, tasks, labels, provenance,
      quality gates, and lineage for auditability.

Failure modes
    - Pydantic validation on ``ForgeJobRequest`` / ``query_anchor`` coercion.

Maintenance notes
    - Good: add optional label sub-fields without breaking existing exporters.
    - Bad: change ``record_id`` or ``forge_job_id`` semantics without migration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class TimelineTurn(BaseModel):
    role: str
    content: str
    speaker: str | None = None
    turn_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TimelineSession(BaseModel):
    session_id: str
    event_date: datetime
    context: str | None = None
    document_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    turns: list[TimelineTurn] = Field(default_factory=list)


class TimelineEpisode(BaseModel):
    sessions: list[TimelineSession] = Field(default_factory=list)


class FactSnapshot(BaseModel):
    id: str
    text: str
    fact_type: str
    context: str | None = None
    occurred_start: datetime | None = None
    occurred_end: datetime | None = None
    mentioned_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    chunk_id: str | None = None
    document_id: str | None = None


class ObsSnapshot(BaseModel):
    id: str
    text: str
    proof_count: int = 0
    source_memory_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)


class LinkSnapshot(BaseModel):
    from_unit_id: str
    to_unit_id: str
    link_type: str
    weight: float = 1.0
    entity_id: str | None = None


class GraphNodeSnapshot(BaseModel):
    title: str
    node_kind: str
    status: str
    confidence: float = 0.0
    change_score: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)


class GraphChangeEventSnapshot(BaseModel):
    change_type: str
    summary: str
    evidence_ids: list[str] = Field(default_factory=list)
    before_text: str | None = None
    after_text: str | None = None


class GraphSnapshot(BaseModel):
    nodes: list[GraphNodeSnapshot] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    change_events: list[GraphChangeEventSnapshot] = Field(default_factory=list)


class ToolTraceStep(BaseModel):
    tool: str
    reason: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = 0
    iteration: int = 0


class TrainingTask(BaseModel):
    task_type: str
    query: str | None = None
    category: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TrainingLabels(BaseModel):
    """Supervision targets; only recipe-relevant fields are populated per record."""

    answer: str | None = None
    gold_answer: str | None = None
    cited_memory_ids: list[str] = Field(default_factory=list)
    cited_observation_ids: list[str] = Field(default_factory=list)
    cited_mental_model_ids: list[str] = Field(default_factory=list)
    tool_trace: list[ToolTraceStep] = Field(default_factory=list)
    structured_output: dict[str, Any] | None = None
    expected_graph: dict[str, Any] | None = None  # graph_state recipe
    belief_update: dict[str, Any] | None = None  # belief_update recipe
    consolidation_pair: dict[str, Any] | None = None  # consolidation_pairs recipe


class ProvenanceBlock(BaseModel):
    """Pointers back to source documents/chunks in the memory bank."""

    document_ids: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)
    source_chains: list[list[str]] = Field(default_factory=list)
    ingest_adapter: str | None = None


class QualityScore(BaseModel):
    """Gate computed by ``forge/quality.audit_record`` before export."""

    overall: float = 0.0
    provenance_complete: bool = False
    temporal_coherent: bool = True
    citation_valid: bool = True
    contradiction_unresolved: bool = False
    judge_score: float | None = None
    exportable: bool = False  # True when overall >= job quality_threshold
    issues: list[str] = Field(default_factory=list)


class LineageBlock(BaseModel):
    """Audit trail linking a record to recipe, model, and optional repo snapshot."""

    snapshot_hash: str | None = None
    repo_commit_id: str | None = None
    recipe_id: str
    recipe_version: str = "1"
    adapter_version: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    exported_at: datetime | None = None


class AtulyaTrainingRecord(BaseModel):
    """Canonical training record (ATR) — single exportable unit from Data Forge."""

    record_id: str
    forge_job_id: str
    bank_id: str
    recipe_id: str
    domain_tags: list[str] = Field(default_factory=list)
    timeline: TimelineEpisode = Field(default_factory=TimelineEpisode)
    query_anchor: datetime | None = None
    facts: list[FactSnapshot] = Field(default_factory=list)
    observations: list[ObsSnapshot] = Field(default_factory=list)
    graph: GraphSnapshot | None = None
    links: list[LinkSnapshot] = Field(default_factory=list)
    tasks: list[TrainingTask] = Field(default_factory=list)
    labels: TrainingLabels = Field(default_factory=TrainingLabels)
    provenance: ProvenanceBlock = Field(default_factory=ProvenanceBlock)
    quality: QualityScore = Field(default_factory=QualityScore)
    lineage: LineageBlock

    @field_validator("query_anchor", mode="before")
    @classmethod
    def _coerce_query_anchor(cls, v: Any) -> datetime | None:
        if v is None or isinstance(v, datetime):
            return v
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


RetainBatchItem = dict[str, Any]

ForgeSourceType = Literal["chat", "timeseries", "scenario", "sessions", "bank_only"]
ForgeRecipeId = Literal[
    "consolidation_pairs",
    "temporal_qa",
    "agent_trace",
    "graph_state",
    "belief_update",
    "synthetic_expand",
]


class ForgeIngestSource(BaseModel):
    source_type: ForgeSourceType
    payload: dict[str, Any] = Field(default_factory=dict)


class ForgeJobRequest(BaseModel):
    """Request to run a forge job: ingest → consolidate → recipe → quality audit."""

    recipe_id: ForgeRecipeId
    domain_tags: list[str] = Field(default_factory=list)
    source: ForgeIngestSource | None = None
    quality_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    wait_consolidation: bool = True
    max_records: int = Field(default=500, ge=1, le=10000)
    repo_commit_on_complete: bool = False
    commit_message: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class ForgeJobStatus(BaseModel):
    operation_id: str
    bank_id: str
    status: str
    recipe_id: str
    stage: str | None = None
    records_total: int = 0
    records_exportable: int = 0
    quality_summary: dict[str, Any] = Field(default_factory=dict)
    artifact_urls: dict[str, str] = Field(default_factory=dict)
    repo_commit_id: str | None = None
    error_message: str | None = None


class ForgeExportRequest(BaseModel):
    operation_id: str
    adapter_id: str = "atr_jsonl"
    quality_threshold: float | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class ExportManifest(BaseModel):
    adapter_id: str
    record_count: int
    exportable_count: int
    output_path: str | None = None
    content: str | None = None
    lineage: LineageBlock
    quality_summary: dict[str, Any] = Field(default_factory=dict)
