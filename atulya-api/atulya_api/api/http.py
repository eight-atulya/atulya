"""
FastAPI application factory and API routes for memory system.

This module provides the create_app function to create and configure
the FastAPI application with all API endpoints.
"""

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import Response

from atulya_api.extensions import AuthenticationError


def _parse_metadata(metadata: Any) -> dict[str, Any]:
    """Parse metadata that may be a dict, JSON string, or None."""
    if metadata is None:
        return {}
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, str):
        try:
            return json.loads(metadata)
        except json.JSONDecodeError:
            return {}
    return {}


from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from atulya_api import MemoryEngine


def FieldWithDefault(default_factory: Callable, **kwargs) -> Any:
    """
    Field wrapper that ensures default_factory values appear in OpenAPI schema.

    Pydantic doesn't include default_factory in OpenAPI schemas, causing OpenAPI
    Generator to make fields Optional with default=None instead of non-optional
    with the correct default value.

    This wrapper adds json_schema_extra to include the default in the schema.
    """
    # Determine the default value for the schema based on the factory
    if default_factory is list:
        schema_default = []
    elif default_factory is dict:
        schema_default = {}
    else:
        # For custom factories (like IncludeOptions), use empty dict as placeholder
        schema_default = {}

    # Add or merge json_schema_extra
    json_extra = kwargs.pop("json_schema_extra", {})
    if isinstance(json_extra, dict):
        json_extra["default"] = schema_default
    else:
        # If json_schema_extra was a function, we can't merge easily
        # Fall back to just setting default
        json_extra = {"default": schema_default}

    return Field(default_factory=default_factory, json_schema_extra=json_extra, **kwargs)


from atulya_api.bank_presets import merge_bank_preset
from atulya_api.config import get_config
from atulya_api.engine.memory_engine import Budget, _current_schema, _get_tiktoken_encoding, fq_table
from atulya_api.engine.response_models import VALID_RECALL_FACT_TYPES, MemoryFact, TokenUsage
from atulya_api.engine.search.tags import TagsMatch
from atulya_api.extensions import HttpExtension, OperationValidationError, load_extension
from atulya_api.metrics import create_metrics_collector, get_metrics_collector, initialize_metrics
from atulya_api.models import RequestContext
from atulya_api.reflect_serialization import compose_reflect_query, serialize_reflect_response

logger = logging.getLogger(__name__)

MAX_QUERY_TOKENS = 500  # Maximum tokens allowed in recall query


class EntityIncludeOptions(BaseModel):
    """Options for including entity observations in recall results."""

    max_tokens: int = Field(default=500, description="Maximum tokens for entity observations")


class ChunkIncludeOptions(BaseModel):
    """Options for including chunks in recall results."""

    max_tokens: int = Field(default=8192, description="Maximum tokens for chunks (chunks may be truncated)")


class SourceFactsIncludeOptions(BaseModel):
    """Options for including source facts for observation-type results."""

    max_tokens: int = Field(
        default=4096, description="Maximum total tokens for source facts across all observations (-1 = unlimited)"
    )
    max_tokens_per_observation: int = Field(
        default=-1, description="Maximum tokens of source facts per observation (-1 = unlimited)"
    )


class IncludeOptions(BaseModel):
    """Options for including additional data in recall results."""

    entities: EntityIncludeOptions | None = Field(
        default=EntityIncludeOptions(),
        description="Include entity observations. Set to null to disable entity inclusion.",
    )
    chunks: ChunkIncludeOptions | None = Field(
        default=None, description="Include raw chunks. Set to {} to enable, null to disable (default: disabled)."
    )
    source_facts: SourceFactsIncludeOptions | None = Field(
        default=None,
        description="Include source facts for observation-type results. Set to {} to enable, null to disable (default: disabled).",
    )


class RecallRequest(BaseModel):
    """Request model for recall endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "What did Alice say about machine learning?",
                "types": ["world", "experience"],
                "budget": "mid",
                "max_tokens": 4096,
                "trace": True,
                "query_timestamp": "2023-05-30T23:40:00",
                "include": {"entities": {"max_tokens": 500}},
                "tags": ["user_a"],
                "tags_match": "any",
            }
        }
    )

    query: str
    types: list[str] | None = Field(
        default=None,
        description="List of fact types to recall: 'world', 'experience', 'observation'. Defaults to world and experience if not specified.",
    )
    budget: Budget = Budget.MID
    max_tokens: int = 4096
    trace: bool = False
    query_timestamp: str | None = Field(
        default=None, description="ISO format date string (e.g., '2023-05-30T23:40:00')"
    )
    include: IncludeOptions = FieldWithDefault(
        IncludeOptions,
        description="Options for including additional data (entities are included by default)",
    )
    tags: list[str] | None = Field(
        default=None,
        description="Filter memories by tags. If not specified, all memories are returned.",
    )
    tags_match: TagsMatch = Field(
        default="any",
        description="How to match tags: 'any' (OR, includes untagged), 'all' (AND, includes untagged), "
        "'any_strict' (OR, excludes untagged), 'all_strict' (AND, excludes untagged).",
    )


class RecallResult(BaseModel):
    """Single recall result item."""

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "text": "Alice works at Google on the AI team",
                "type": "world",
                "entities": ["Alice", "Google"],
                "context": "work info",
                "occurred_start": "2024-01-15T10:30:00Z",
                "occurred_end": "2024-01-15T10:30:00Z",
                "mentioned_at": "2024-01-15T10:30:00Z",
                "document_id": "session_abc123",
                "metadata": {"source": "slack"},
                "chunk_id": "456e7890-e12b-34d5-a678-901234567890",
                "tags": ["user_a", "user_b"],
            }
        },
    }

    id: str
    text: str
    type: str | None = None  # fact type: world, experience, opinion, observation
    entities: list[str] | None = None  # Entity names mentioned in this fact
    context: str | None = None
    occurred_start: str | None = None  # ISO format date when the event started
    occurred_end: str | None = None  # ISO format date when the event ended
    mentioned_at: str | None = None  # ISO format date when the fact was mentioned
    document_id: str | None = None  # Document this memory belongs to
    metadata: dict[str, str] | None = None  # User-defined metadata
    chunk_id: str | None = None  # Chunk this fact was extracted from
    tags: list[str] | None = None  # Visibility scope tags
    source_fact_ids: list[str] | None = (
        None  # IDs of source facts (observation type only, when source_facts is enabled)
    )


class EntityObservationResponse(BaseModel):
    """An observation about an entity."""

    text: str
    mentioned_at: str | None = None


class EntityStateResponse(BaseModel):
    """Current mental model of an entity."""

    entity_id: str
    canonical_name: str
    observations: list[EntityObservationResponse]


class EntityListItem(BaseModel):
    """Entity list item with summary."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "canonical_name": "John",
                "mention_count": 15,
                "first_seen": "2024-01-15T10:30:00Z",
                "last_seen": "2024-02-01T14:00:00Z",
            }
        }
    )

    id: str
    canonical_name: str
    mention_count: int
    first_seen: str | None = None
    last_seen: str | None = None
    metadata: dict[str, Any] | None = None


class EntityListResponse(BaseModel):
    """Response model for entity list endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": "123e4567-e89b-12d3-a456-426614174000",
                        "canonical_name": "John",
                        "mention_count": 15,
                        "first_seen": "2024-01-15T10:30:00Z",
                        "last_seen": "2024-02-01T14:00:00Z",
                    }
                ],
                "total": 150,
                "limit": 100,
                "offset": 0,
            }
        }
    )

    items: list[EntityListItem]
    total: int
    limit: int
    offset: int


class EntityDetailResponse(BaseModel):
    """Response model for entity detail endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "canonical_name": "John",
                "mention_count": 15,
                "first_seen": "2024-01-15T10:30:00Z",
                "last_seen": "2024-02-01T14:00:00Z",
                "observations": [{"text": "John works at Google", "mentioned_at": "2024-01-15T10:30:00Z"}],
            }
        }
    )

    id: str
    canonical_name: str
    mention_count: int
    first_seen: str | None = None
    last_seen: str | None = None
    metadata: dict[str, Any] | None = None
    observations: list[EntityObservationResponse]


class ChunkData(BaseModel):
    """Chunk data for a single chunk."""

    id: str
    text: str
    chunk_index: int
    truncated: bool = Field(default=False, description="Whether the chunk text was truncated due to token limits")


class RecallResponse(BaseModel):
    """Response model for recall endpoints."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "results": [
                    {
                        "id": "123e4567-e89b-12d3-a456-426614174000",
                        "text": "Alice works at Google on the AI team",
                        "type": "world",
                        "entities": ["Alice", "Google"],
                        "context": "work info",
                        "occurred_start": "2024-01-15T10:30:00Z",
                        "occurred_end": "2024-01-15T10:30:00Z",
                        "chunk_id": "456e7890-e12b-34d5-a678-901234567890",
                    }
                ],
                "trace": {
                    "query": "What did Alice say about machine learning?",
                    "num_results": 1,
                    "time_seconds": 0.123,
                },
                "entities": {
                    "Alice": {
                        "entity_id": "123e4567-e89b-12d3-a456-426614174001",
                        "canonical_name": "Alice",
                        "observations": [
                            {"text": "Alice works at Google on the AI team", "mentioned_at": "2024-01-15T10:30:00Z"}
                        ],
                    }
                },
                "chunks": {
                    "456e7890-e12b-34d5-a678-901234567890": {
                        "id": "456e7890-e12b-34d5-a678-901234567890",
                        "text": "Alice works at Google on the AI team. She's been there for 3 years...",
                        "chunk_index": 0,
                    }
                },
            }
        }
    )

    results: list[RecallResult]
    trace: dict[str, Any] | None = None
    entities: dict[str, EntityStateResponse] | None = Field(
        default=None, description="Entity states for entities mentioned in results"
    )
    chunks: dict[str, ChunkData] | None = Field(default=None, description="Chunks for facts, keyed by chunk_id")
    source_facts: dict[str, RecallResult] | None = Field(
        default=None, description="Source facts for observation-type results, keyed by fact ID"
    )


class EntityInput(BaseModel):
    """Entity to associate with retained content."""

    text: str = Field(description="The entity name/text")
    type: str | None = Field(default=None, description="Optional entity type (e.g., 'PERSON', 'ORG', 'CONCEPT')")


class MemoryItem(BaseModel):
    """Single memory item for retain."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "content": "Alice mentioned she's working on a new ML model",
                "timestamp": "2024-01-15T10:30:00Z",
                "context": "team meeting",
                "metadata": {"source": "slack", "channel": "engineering"},
                "document_id": "meeting_notes_2024_01_15",
                "entities": [{"text": "Alice"}, {"text": "ML model", "type": "CONCEPT"}],
                "tags": ["user_a", "user_b"],
            }
        },
    )

    content: str
    timestamp: datetime | str | None = Field(
        default=None,
        description=(
            "When the content occurred. "
            "Accepts an ISO 8601 datetime string (e.g. '2024-01-15T10:30:00Z'), null/omitted (defaults to now), "
            "or the special string 'unset' to explicitly store without any timestamp "
            "(use this for timeless content such as fictional documents or static reference material)."
        ),
    )
    context: str | None = None
    metadata: dict[str, str] | None = None
    document_id: str | None = Field(default=None, description="Optional document ID for this memory item.")
    entities: list[EntityInput] | None = Field(
        default=None,
        description="Optional entities to combine with auto-extracted entities.",
    )
    tags: list[str] | None = Field(
        default=None,
        description="Optional tags for visibility scoping. Memories with tags can be filtered during recall.",
    )
    observation_scopes: Literal["per_tag", "combined", "all_combinations"] | list[list[str]] | None = Field(
        default=None,
        title="ObservationScopes",
        description=(
            "How to scope observations during consolidation. "
            "'per_tag' runs one consolidation pass per individual tag, creating separate observations for each tag. "
            "'combined' (default) runs a single pass with all tags together. "
            "A list of tag lists runs one pass per inner list, giving full control over which combinations to use."
        ),
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def validate_timestamp(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            if v.lower() == "unset":
                return "unset"
            try:
                # Try parsing as ISO format
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError as e:
                raise ValueError(
                    f"Invalid timestamp/event_date format: '{v}'. Expected ISO format like '2024-01-15T10:30:00' or '2024-01-15T10:30:00Z', or the special value 'unset' to store without a timestamp."
                ) from e
        raise ValueError(f"timestamp must be a string or datetime, got {type(v).__name__}")


class RetainRequest(BaseModel):
    """Request model for retain endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {"content": "Alice works at Google", "context": "work", "document_id": "conversation_123"},
                    {
                        "content": "Bob went hiking yesterday",
                        "timestamp": "2024-01-15T10:00:00Z",
                        "document_id": "conversation_123",
                    },
                ],
                "async": False,
            }
        }
    )

    items: list[MemoryItem]
    async_: bool = Field(
        default=False,
        alias="async",
        description="If true, process asynchronously in background. If false, wait for completion (default: false)",
    )
    document_tags: list[str] | None = Field(
        default=None,
        description="Deprecated. Use item-level tags instead.",
        deprecated=True,
    )


class FileRetainMetadata(BaseModel):
    """Metadata for a single file in file retain request."""

    document_id: str | None = Field(default=None, description="Document ID (auto-generated if not provided)")
    context: str | None = Field(default=None, description="Context for the file")
    metadata: dict[str, Any] | None = Field(default=None, description="Additional metadata")
    tags: list[str] | None = Field(default=None, description="Tags for this file")
    timestamp: str | None = Field(default=None, description="ISO timestamp")
    parser: str | list[str] | None = Field(
        default=None,
        description="Parser or ordered fallback chain for this file (overrides request-level parser). "
        "E.g. 'iris' or ['iris', 'markitdown'].",
    )


class FileRetainRequest(BaseModel):
    """Request model for file retain endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "parser": "iris",
                "files_metadata": [
                    {"document_id": "report_2024", "tags": ["quarterly"]},
                    {"context": "meeting notes", "parser": ["iris", "markitdown"]},
                ],
            }
        }
    )

    parser: str | list[str] | None = Field(
        default=None,
        description="Default parser or ordered fallback chain for all files in this request. "
        "E.g. 'markitdown' or ['iris', 'markitdown']. Falls back to server default if not set. "
        "Per-file 'parser' in files_metadata takes precedence over this value.",
    )
    files_metadata: list[FileRetainMetadata] | None = Field(
        default=None,
        description="Metadata for each file (optional, must match number of files if provided)",
    )


class RetainResponse(BaseModel):
    """Response model for retain endpoint."""

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "success": True,
                "bank_id": "user123",
                "items_count": 2,
                "async": False,
                "usage": {"input_tokens": 500, "output_tokens": 100, "total_tokens": 600},
            }
        },
    )

    success: bool
    bank_id: str
    items_count: int
    is_async: bool = Field(
        alias="async", serialization_alias="async", description="Whether the operation was processed asynchronously"
    )
    operation_id: str | None = Field(
        default=None,
        description="Operation ID for tracking async operations. Use GET /v1/default/banks/{bank_id}/operations to list operations. Only present when async=true.",
    )
    usage: TokenUsage | None = Field(
        default=None,
        description="Token usage metrics for LLM calls during fact extraction (only present for synchronous operations)",
    )


class FileRetainResponse(BaseModel):
    """Response model for file upload endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "operation_ids": [
                    "550e8400-e29b-41d4-a716-446655440000",
                    "550e8400-e29b-41d4-a716-446655440001",
                    "550e8400-e29b-41d4-a716-446655440002",
                ],
            }
        },
    )

    operation_ids: list[str] = Field(
        description="Operation IDs for tracking file conversion operations. Use GET /v1/default/banks/{bank_id}/operations to list operations."
    )


class CodebaseSourceConfigResponse(BaseModel):
    """Normalized source configuration for a codebase."""

    owner: str | None = None
    repo: str | None = None
    repo_url: str | None = None
    ref: str | None = None
    root_path: str | None = None
    include_globs: list[str] = FieldWithDefault(list)
    exclude_globs: list[str] = FieldWithDefault(list)


class CodebaseReviewCountsResponse(BaseModel):
    """Counts of routed review items in the current snapshot."""

    unrouted: int = 0
    memory: int = 0
    research: int = 0
    dismissed: int = 0


class CodebaseSnapshotStatsResponse(BaseModel):
    """Snapshot-level deterministic indexing stats."""

    total_files: int = 0
    indexed_files: int = 0
    retained_files: int = 0
    manifest_only_files: int = 0
    excluded_files: int = 0
    symbol_count: int = 0
    edge_count: int = 0
    added_files: int = 0
    changed_files: int = 0
    unchanged_files: int = 0
    deleted_files: int = 0
    chunk_count: int = 0
    cluster_count: int = 0
    related_chunk_count: int = 0
    parse_coverage: float = 0.0
    review_counts: CodebaseReviewCountsResponse = Field(default_factory=CodebaseReviewCountsResponse)
    error: str | None = None


class CodebaseImportZipRequest(BaseModel):
    """JSON payload for ZIP-based codebase import."""

    name: str
    root_path: str | None = None
    include_globs: list[str] = FieldWithDefault(list)
    exclude_globs: list[str] = FieldWithDefault(list)
    refresh_existing: bool = False


class CodebaseImportGithubRequest(BaseModel):
    """JSON payload for public GitHub-backed codebase import."""

    owner: str | None = None
    repo: str | None = None
    ref: str | None = None
    repo_url: str | None = None
    root_path: str | None = None
    include_globs: list[str] = FieldWithDefault(list)
    exclude_globs: list[str] = FieldWithDefault(list)
    refresh_existing: bool = False

    @staticmethod
    def _parse_repo_url(repo_url: str) -> tuple[str, str, str | None]:
        normalized = repo_url.strip()
        if not normalized:
            raise ValueError("repo_url cannot be empty")

        parsed_ref: str | None = None
        if normalized.startswith("git@github.com:"):
            path = normalized.split(":", 1)[1]
        else:
            parsed = urlparse(normalized)
            if parsed.scheme not in {"http", "https"} or parsed.netloc not in {"github.com", "www.github.com"}:
                raise ValueError("repo_url must be a GitHub repository URL")
            path = parsed.path.lstrip("/")

        parts = [part for part in path.split("/") if part]
        if len(parts) < 2:
            raise ValueError("repo_url must include both owner and repository name")

        owner = parts[0]
        repo = parts[1]
        if repo.endswith(".git"):
            repo = repo[:-4]
        if not owner or not repo:
            raise ValueError("repo_url must include both owner and repository name")

        if len(parts) >= 4 and parts[2] in {"tree", "commit", "blob"}:
            parsed_ref = parts[3]

        return owner, repo, parsed_ref

    @model_validator(mode="after")
    def normalize_repo_source(self) -> "CodebaseImportGithubRequest":
        if self.repo_url:
            owner, repo, parsed_ref = self._parse_repo_url(self.repo_url)
            self.owner = self.owner or owner
            self.repo = self.repo or repo
            self.ref = self.ref or parsed_ref

        if not self.owner or not self.repo:
            raise ValueError("GitHub import requires owner and repo, or a valid GitHub repo_url.")
        return self


class CodebaseImportResponse(BaseModel):
    """Queued codebase import response."""

    codebase_id: str
    snapshot_id: str
    operation_id: str
    status: str


class CodebaseGithubImportResponse(CodebaseImportResponse):
    """Queued GitHub codebase import response."""

    resolved_commit_sha: str


class CodebaseRefreshRequest(BaseModel):
    """Explicit codebase refresh request."""

    ref: str | None = None
    full_rebuild: bool = False


class CodebaseRefreshResponse(BaseModel):
    """Explicit codebase refresh response."""

    snapshot_id: str | None = None
    operation_id: str | None = None
    status: str
    changed_files: int = 0
    added_files: int = 0
    deleted_files: int = 0
    noop: bool = False


class CodebaseApproveRequest(BaseModel):
    """Approve a parsed codebase snapshot for memory hydration."""

    snapshot_id: str | None = None
    memory_ingest_mode: Literal["direct", "retain"] = "direct"


class CodebaseApproveResponse(BaseModel):
    """Queued codebase approval response."""

    codebase_id: str
    snapshot_id: str
    operation_id: str
    status: str
    memory_ingest_mode: Literal["direct", "retain"] = "direct"


class CodebaseResponse(BaseModel):
    """Codebase metadata plus current snapshot summary."""

    id: str
    bank_id: str
    name: str
    source_type: str
    source_config: CodebaseSourceConfigResponse = Field(default_factory=CodebaseSourceConfigResponse)
    current_snapshot_id: str | None = None
    approved_snapshot_id: str | None = None
    source_ref: str | None = None
    source_commit_sha: str | None = None
    snapshot_status: str | None = None
    approved_source_ref: str | None = None
    approved_source_commit_sha: str | None = None
    approved_snapshot_status: str | None = None
    approval_status: str | None = None
    memory_status: str | None = None
    stats: CodebaseSnapshotStatsResponse = Field(default_factory=CodebaseSnapshotStatsResponse)
    review_counts: CodebaseReviewCountsResponse = Field(default_factory=CodebaseReviewCountsResponse)
    cluster_count: int = 0
    related_chunk_count: int = 0
    parse_coverage: float = 0.0
    created_at: str | None = None
    updated_at: str | None = None
    snapshot_created_at: str | None = None
    snapshot_updated_at: str | None = None
    approved_snapshot_updated_at: str | None = None


class CodebaseListResponse(BaseModel):
    """List of codebases for a bank."""

    items: list[CodebaseResponse]


class CodebaseFileItemResponse(BaseModel):
    """Single file entry in a codebase snapshot."""

    path: str
    language: str | None = None
    size_bytes: int
    content_hash: str
    document_id: str | None = None
    status: str
    change_kind: str
    reason: str | None = None
    chunk_count: int = 0


class CodebaseFilesResponse(BaseModel):
    """Codebase file listing response."""

    codebase_id: str
    snapshot_id: str | None = None
    source_ref: str | None = None
    source_commit_sha: str | None = None
    snapshot_status: str | None = None
    items: list[CodebaseFileItemResponse]


class CodebaseSymbolMatchResponse(BaseModel):
    """Single deterministic symbol match."""

    name: str
    kind: str
    fq_name: str
    path: str
    language: str | None = None
    container: str | None = None
    start_line: int
    end_line: int
    match_mode: str | None = None
    chunk_ids: list[str] = FieldWithDefault(list)


class CodebaseChunkItemResponse(BaseModel):
    """Single reviewable code chunk."""

    id: str
    chunk_key: str
    path: str
    language: str | None = None
    kind: str
    label: str
    preview_text: str
    start_line: int
    end_line: int
    container: str | None = None
    parent_symbol: str | None = None
    parent_fq_name: str | None = None
    parse_confidence: float = 0.0
    cluster_id: str | None = None
    cluster_label: str | None = None
    route_target: str
    route_source: str | None = None
    change_kind: str
    related_count: int = 0
    document_id: str | None = None


class CodebaseChunksResponse(BaseModel):
    """Paginated reviewable chunk response."""

    codebase_id: str
    snapshot_id: str | None = None
    items: list[CodebaseChunkItemResponse]
    next_cursor: str | None = None
    has_more: bool = False


class CodebaseReviewDiagnosticResponse(BaseModel):
    """A deterministic review diagnostic bucket."""

    reason: str
    count: int


class CodebaseReviewChangedSummaryResponse(BaseModel):
    """Changed-file summary for the current review snapshot."""

    added_files: int = 0
    changed_files: int = 0
    deleted_files: int = 0


class CodebaseReviewResponse(BaseModel):
    """Review summary for the current codebase snapshot."""

    codebase_id: str
    snapshot_id: str | None = None
    snapshot_status: str | None = None
    approval_status: str | None = None
    memory_status: str | None = None
    review_counts: CodebaseReviewCountsResponse = Field(default_factory=CodebaseReviewCountsResponse)
    cluster_count: int = 0
    related_chunk_count: int = 0
    parse_coverage: float = 0.0
    changed_summary: CodebaseReviewChangedSummaryResponse = Field(default_factory=CodebaseReviewChangedSummaryResponse)
    diagnostics: list[CodebaseReviewDiagnosticResponse] = FieldWithDefault(list)


class CodebaseChunkRelatedItemResponse(BaseModel):
    """Compact related chunk preview."""

    id: str
    label: str
    path: str
    kind: str
    start_line: int
    end_line: int
    cluster_label: str | None = None
    score: float = 0.0


class CodebaseChunkDetailResponse(CodebaseChunkItemResponse):
    """Detailed chunk review payload."""

    snapshot_id: str
    content_text: str
    related_chunks: list[CodebaseChunkRelatedItemResponse] = FieldWithDefault(list)
    symbols: list[CodebaseSymbolMatchResponse] = FieldWithDefault(list)
    impact_edges: list["CodebaseImpactEdgeResponse"] = FieldWithDefault(list)
    cluster_members: list[CodebaseChunkRelatedItemResponse] = FieldWithDefault(list)


class CodebaseRouteRequest(BaseModel):
    """Bulk review-route update request."""

    item_ids: list[str]
    target: Literal["memory", "research", "dismissed", "unrouted"]
    queue_memory_import: bool = False
    memory_ingest_mode: Literal["direct", "retain"] = "direct"


class CodebaseRouteResponse(BaseModel):
    """Bulk review-route update response."""

    codebase_id: str
    snapshot_id: str
    updated_count: int
    target: str
    operation_id: str | None = None
    queued_for_memory: bool = False
    memory_ingest_mode: Literal["direct", "retain"] = "direct"
    review_counts: CodebaseReviewCountsResponse = Field(default_factory=CodebaseReviewCountsResponse)


class CodebaseSymbolsResponse(BaseModel):
    """Symbol search results for a codebase."""

    codebase_id: str
    snapshot_id: str | None = None
    items: list[CodebaseSymbolMatchResponse]


class CodebaseImpactRequest(BaseModel):
    """Impact analysis request for a codebase."""

    path: str | None = None
    symbol: str | None = None
    query: str | None = None
    max_depth: int = Field(default=2, ge=1, le=8)
    limit: int = Field(default=50, ge=1, le=200)


class CodebaseImpactSeedResponse(BaseModel):
    """Seed used to start deterministic impact analysis."""

    type: str
    value: str


class CodebaseImpactFileResponse(BaseModel):
    """Impacted file entry with traversal depth."""

    path: str
    language: str | None = None
    size_bytes: int
    content_hash: str
    document_id: str | None = None
    status: str
    change_kind: str
    chunk_count: int = 0
    depth: int


class CodebaseImpactEdgeResponse(BaseModel):
    """Deterministic code graph edge returned for impact analysis."""

    edge_type: str
    from_path: str
    from_symbol: str | None = None
    to_path: str | None = None
    to_symbol: str | None = None
    target_ref: str | None = None
    label: str | None = None


class CodebaseImpactResponse(BaseModel):
    """Impact analysis response."""

    codebase_id: str
    snapshot_id: str | None = None
    seed: CodebaseImpactSeedResponse | None = None
    impacted_files: list[CodebaseImpactFileResponse]
    matched_symbols: list[CodebaseSymbolMatchResponse]
    edges: list[CodebaseImpactEdgeResponse]
    explanation: str


CodebaseChunkDetailResponse.model_rebuild()


class FactsIncludeOptions(BaseModel):
    """Options for including facts (based_on) in reflect results."""

    pass  # No additional options needed, just enable/disable


class ToolCallsIncludeOptions(BaseModel):
    """Options for including tool calls in reflect results."""

    output: bool = Field(
        default=True,
        description="Include tool outputs in the trace. Set to false to only include inputs (smaller payload).",
    )


class ReflectIncludeOptions(BaseModel):
    """Options for including additional data in reflect results."""

    facts: FactsIncludeOptions | None = Field(
        default=None,
        description="Include facts that the answer is based on. Set to {} to enable, null to disable (default: disabled).",
    )
    tool_calls: ToolCallsIncludeOptions | None = Field(
        default=None,
        description="Include tool calls trace. Set to {} for full trace (input+output), {output: false} for inputs only.",
    )


class ReflectRequest(BaseModel):
    """Request model for reflect endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "What do you think about artificial intelligence?",
                "budget": "low",
                "max_tokens": 4096,
                "include": {"facts": {}},
                "response_schema": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "key_points": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["summary", "key_points"],
                },
                "tags": ["user_a"],
                "tags_match": "any",
            }
        }
    )

    query: str
    budget: Budget = Budget.LOW
    context: str | None = Field(
        default=None,
        description="DEPRECATED: Additional context is now concatenated with the query. "
        "Pass context directly in the query field instead. "
        "If provided, it will be appended to the query for backward compatibility.",
        deprecated=True,
    )
    max_tokens: int = Field(default=4096, description="Maximum tokens for the response")
    include: ReflectIncludeOptions = Field(
        default_factory=ReflectIncludeOptions, description="Options for including additional data (disabled by default)"
    )
    response_schema: dict | None = Field(
        default=None,
        description="Optional JSON Schema for structured output. When provided, the response will include a 'structured_output' field with the LLM response parsed according to this schema.",
    )
    tags: list[str] | None = Field(
        default=None,
        description="Filter memories by tags during reflection. If not specified, all memories are considered.",
    )
    tags_match: TagsMatch = Field(
        default="any",
        description="How to match tags: 'any' (OR, includes untagged), 'all' (AND, includes untagged), "
        "'any_strict' (OR, excludes untagged), 'all_strict' (AND, excludes untagged).",
    )


class ReflectFact(BaseModel):
    """A fact used in think response."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "text": "AI is used in healthcare",
                "type": "world",
                "context": "healthcare discussion",
                "occurred_start": "2024-01-15T10:30:00Z",
                "occurred_end": "2024-01-15T10:30:00Z",
            }
        }
    )

    id: str | None = None
    text: str = Field(
        description="Fact text. When type='observation', this contains markdown-formatted consolidated knowledge"
    )
    type: str | None = None  # fact type: world, experience, observation
    context: str | None = None
    occurred_start: str | None = None
    occurred_end: str | None = None


class ReflectDirective(BaseModel):
    """A directive applied during reflect."""

    id: str = Field(description="Directive ID")
    name: str = Field(description="Directive name")
    content: str = Field(description="Directive content")


class ReflectMentalModel(BaseModel):
    """A mental model used during reflect."""

    id: str = Field(description="Mental model ID")
    text: str = Field(description="Mental model content")
    context: str | None = Field(default=None, description="Additional context")


class ReflectToolCall(BaseModel):
    """A tool call made during reflect agent execution."""

    tool: str = Field(description="Tool name: lookup, recall, learn, expand")
    input: dict = Field(description="Tool input parameters")
    output: dict | None = Field(
        default=None, description="Tool output (only included when include.tool_calls.output is true)"
    )
    duration_ms: int = Field(description="Execution time in milliseconds")
    iteration: int = Field(default=0, description="Iteration number (1-based) when this tool was called")


class ReflectLLMCall(BaseModel):
    """An LLM call made during reflect agent execution."""

    scope: str = Field(description="Call scope: agent_1, agent_2, final, etc.")
    duration_ms: int = Field(description="Execution time in milliseconds")


class ReflectBasedOn(BaseModel):
    """Evidence the response is based on: memories, mental models, and directives."""

    memories: list[ReflectFact] = FieldWithDefault(list, description="Memory facts used to generate the response")
    mental_models: list[ReflectMentalModel] = FieldWithDefault(list, description="Mental models used during reflection")
    directives: list[ReflectDirective] = FieldWithDefault(list, description="Directives applied during reflection")


class ReflectTrace(BaseModel):
    """Execution trace of LLM and tool calls during reflection."""

    tool_calls: list[ReflectToolCall] = FieldWithDefault(list, description="Tool calls made during reflection")
    llm_calls: list[ReflectLLMCall] = FieldWithDefault(list, description="LLM calls made during reflection")


class ReflectResponse(BaseModel):
    """Response model for think endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "text": "## AI Overview\n\nBased on my understanding, AI is a **transformative technology**:\n\n- Used extensively in healthcare\n- Discussed in recent conversations\n- Continues to evolve rapidly",
                "based_on": {
                    "memories": [
                        {"id": "123", "text": "AI is used in healthcare", "type": "world"},
                        {"id": "456", "text": "I discussed AI applications last week", "type": "experience"},
                    ],
                },
                "structured_output": {
                    "summary": "AI is transformative",
                    "key_points": ["Used in healthcare", "Discussed recently"],
                },
                "usage": {"input_tokens": 1500, "output_tokens": 500, "total_tokens": 2000},
                "trace": {
                    "tool_calls": [{"tool": "recall", "input": {"query": "AI"}, "duration_ms": 150}],
                    "llm_calls": [{"scope": "agent_1", "duration_ms": 1200}],
                    "observations": [
                        {
                            "id": "obs-1",
                            "name": "AI Technology",
                            "type": "concept",
                            "subtype": "structural",
                        }
                    ],
                },
            }
        }
    )

    text: str = Field(
        description="The reflect response as well-formatted markdown (headers, lists, bold/italic, code blocks, etc.)"
    )
    based_on: ReflectBasedOn | None = Field(
        default=None,
        description="Evidence used to generate the response. Only present when include.facts is set.",
    )
    structured_output: dict | None = Field(
        default=None,
        description="Structured output parsed according to the request's response_schema. Only present when response_schema was provided in the request.",
    )
    usage: TokenUsage | None = Field(
        default=None,
        description="Token usage metrics for LLM calls during reflection.",
    )
    trace: ReflectTrace | None = Field(
        default=None,
        description="Execution trace of tool and LLM calls. Only present when include.tool_calls is set.",
    )


class DispositionTraits(BaseModel):
    """Disposition traits that influence how memories are formed and interpreted."""

    model_config = ConfigDict(json_schema_extra={"example": {"skepticism": 3, "literalism": 3, "empathy": 3}})

    skepticism: int = Field(ge=1, le=5, description="How skeptical vs trusting (1=trusting, 5=skeptical)")
    literalism: int = Field(ge=1, le=5, description="How literally to interpret information (1=flexible, 5=literal)")
    empathy: int = Field(ge=1, le=5, description="How much to consider emotional context (1=detached, 5=empathetic)")


class BankProfileResponse(BaseModel):
    """Response model for bank profile."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "bank_id": "user123",
                "name": "Alice",
                "disposition": {"skepticism": 3, "literalism": 3, "empathy": 3},
                "mission": "I am a software engineer helping my team stay organized and ship quality code",
            }
        }
    )

    bank_id: str
    name: str
    disposition: DispositionTraits
    mission: str = Field(description="The agent's mission - who they are and what they're trying to accomplish")
    # Deprecated: use mission instead. Kept for backwards compatibility.
    background: str | None = Field(default=None, description="Deprecated: use mission instead")


class UpdateDispositionRequest(BaseModel):
    """Request model for updating disposition traits."""

    disposition: DispositionTraits


class SetMissionRequest(BaseModel):
    """Request model for setting/updating the agent's mission."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"content": "I am a PM helping my engineering team stay organized"}}
    )

    content: str = Field(description="The mission content - who you are and what you're trying to accomplish")


class MissionResponse(BaseModel):
    """Response model for mission update."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "mission": "I am a PM helping my engineering team stay organized and ship quality code.",
            }
        }
    )

    mission: str


class AddBackgroundRequest(BaseModel):
    """Request model for adding/merging background information. Deprecated: use SetMissionRequest instead."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"content": "I was born in Texas", "update_disposition": True}}
    )

    content: str = Field(description="New background information to add or merge")
    update_disposition: bool = Field(
        default=True, description="Deprecated - disposition is no longer auto-inferred from mission"
    )


class BackgroundResponse(BaseModel):
    """Response model for background update. Deprecated: use MissionResponse instead."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "mission": "I was born in Texas. I am a software engineer with 10 years of experience.",
            }
        }
    )

    mission: str
    # Deprecated fields kept for backwards compatibility
    background: str | None = Field(default=None, description="Deprecated: same as mission")
    disposition: DispositionTraits | None = None


class BankListItem(BaseModel):
    """Bank list item with profile summary."""

    bank_id: str
    name: str | None = None
    disposition: DispositionTraits
    mission: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class BankListResponse(BaseModel):
    """Response model for listing all banks."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "banks": [
                    {
                        "bank_id": "user123",
                        "name": "Alice",
                        "disposition": {"skepticism": 3, "literalism": 3, "empathy": 3},
                        "mission": "I am a software engineer helping my team ship quality code",
                        "created_at": "2024-01-15T10:30:00Z",
                        "updated_at": "2024-01-16T14:20:00Z",
                    }
                ]
            }
        }
    )

    banks: list[BankListItem]


class CreateBankRequest(BaseModel):
    """Request model for creating/updating a bank."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "retain_mission": "Always include technical decisions and architectural trade-offs. Ignore meeting logistics.",
                "observations_mission": "Observations are stable facts about people and projects. Always include preferences and skills.",
            }
        }
    )

    # Deprecated fields — kept for backwards compatibility only
    name: str | None = Field(default=None, description="Deprecated: display label only, not advertised")
    disposition: DispositionTraits | None = Field(
        default=None, description="Deprecated: use update_bank_config instead"
    )
    disposition_skepticism: int | None = Field(
        default=None, ge=1, le=5, description="Deprecated: use update_bank_config instead"
    )
    disposition_literalism: int | None = Field(
        default=None, ge=1, le=5, description="Deprecated: use update_bank_config instead"
    )
    disposition_empathy: int | None = Field(
        default=None, ge=1, le=5, description="Deprecated: use update_bank_config instead"
    )
    # Deprecated: use update_bank_config with reflect_mission instead
    mission: str | None = Field(
        default=None, description="Deprecated: use update_bank_config with reflect_mission instead"
    )
    # Deprecated alias for mission
    background: str | None = Field(
        default=None, description="Deprecated: use update_bank_config with reflect_mission instead"
    )

    # Reflect configuration
    reflect_mission: str | None = Field(
        default=None,
        description="Mission/context for Reflect operations. Guides how Reflect interprets and uses memories.",
    )

    # Operational configuration (applied via config resolver)
    retain_mission: str | None = Field(
        default=None,
        description="Steers what gets extracted during retain(). Injected alongside built-in extraction rules.",
    )
    retain_extraction_mode: str | None = Field(
        default=None,
        description="Fact extraction mode: 'concise' (default), 'verbose', or 'custom'.",
    )
    retain_custom_instructions: str | None = Field(
        default=None,
        description="Custom extraction prompt. Only active when retain_extraction_mode is 'custom'.",
    )
    retain_chunk_size: int | None = Field(
        default=None,
        description="Maximum token size for each content chunk during retain.",
    )
    bank_preset: str | None = Field(
        default=None,
        description=(
            "Optional starter kit merged before explicit fields: "
            "'codebase' tunes retain/reflect/observations for repository and ASD chunk ingest, "
            "and idempotently seeds developer-guide mental models plus one evidence-first directive. "
            "Unknown values are ignored."
        ),
    )
    enable_observations: bool | None = Field(
        default=None,
        description="Toggle automatic observation consolidation after retain().",
    )
    observations_mission: str | None = Field(
        default=None,
        description="Controls what gets synthesised into observations. Replaces built-in consolidation rules entirely.",
    )

    def get_config_updates(self) -> dict[str, Any]:
        """Return only the config fields that were explicitly set.

        reflect_mission takes precedence over deprecated mission/background aliases.
        Individual disposition_* fields take priority over the deprecated disposition dict.
        """
        updates: dict[str, Any] = {}
        # Resolve reflect mission: reflect_mission (new) > mission (deprecated) > background (deprecated)
        resolved_reflect_mission = self.reflect_mission or self.mission or self.background
        if resolved_reflect_mission is not None:
            updates["reflect_mission"] = resolved_reflect_mission
        # Disposition: individual fields take priority over legacy disposition dict
        if self.disposition_skepticism is not None:
            updates["disposition_skepticism"] = self.disposition_skepticism
        elif self.disposition is not None:
            updates["disposition_skepticism"] = self.disposition.skepticism
        if self.disposition_literalism is not None:
            updates["disposition_literalism"] = self.disposition_literalism
        elif self.disposition is not None:
            updates["disposition_literalism"] = self.disposition.literalism
        if self.disposition_empathy is not None:
            updates["disposition_empathy"] = self.disposition_empathy
        elif self.disposition is not None:
            updates["disposition_empathy"] = self.disposition.empathy
        for field_name in (
            "retain_mission",
            "retain_extraction_mode",
            "retain_custom_instructions",
            "retain_chunk_size",
            "enable_observations",
            "observations_mission",
        ):
            value = getattr(self, field_name)
            if value is not None:
                updates[field_name] = value
        return merge_bank_preset(self.bank_preset, updates)


class BankConfigUpdate(BaseModel):
    """Request model for updating bank configuration."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "updates": {
                    "llm_model": "claude-sonnet-4-5",
                    "retain_extraction_mode": "verbose",
                    "retain_custom_instructions": "Extract technical details carefully",
                }
            }
        }
    )

    updates: dict[str, Any] = Field(
        description="Configuration overrides. Keys can be in Python field format (llm_provider) "
        "or environment variable format (ATULYA_API_LLM_PROVIDER). "
        "Only hierarchical fields can be overridden per-bank."
    )


class BankConfigResponse(BaseModel):
    """Response model for bank configuration."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "bank_id": "my-bank",
                "config": {
                    "llm_provider": "openai",
                    "llm_model": "gpt-4",
                    "retain_extraction_mode": "verbose",
                },
                "overrides": {
                    "llm_model": "gpt-4",
                    "retain_extraction_mode": "verbose",
                },
            }
        }
    )

    bank_id: str = Field(description="Bank identifier")
    config: dict[str, Any] = Field(
        description="Fully resolved configuration with all hierarchical overrides applied (Python field names)"
    )
    overrides: dict[str, Any] = Field(description="Bank-specific configuration overrides only (Python field names)")


class DreamSubmitRequest(BaseModel):
    trigger_source: str = Field(default="manual", description="manual | event | cron")
    run_type: str = Field(default="dream", description="dream | trance")


class DreamStatsResponse(BaseModel):
    bank_id: str
    total_runs: int
    last_run_at: str | None
    avg_quality: float
    avg_tokens: float
    avg_output_tokens: float
    distillation_pass_rate: float
    distilled_count: int
    validation_rate: float = 0.0
    avg_novelty: float = 0.0
    failed_run_count: int = 0
    duplicate_suppression_count: int = 0
    prediction_confirmation_rate: float = 0.0
    unresolved_prediction_backlog: int = 0


class DreamRunResponse(BaseModel):
    run_id: str
    bank_id: str
    status: str
    run_type: str
    trigger_source: str
    created_at: str
    updated_at: str | None = None
    narrative_html: str | None = None
    summary: str | None = None
    evidence_basis: dict[str, Any] = Field(default_factory=dict)
    signals: dict[str, Any] = Field(default_factory=dict)
    predictions: list[dict[str, Any]] = Field(default_factory=list)
    growth_hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    promotion_proposals: list[dict[str, Any]] = Field(default_factory=list)
    validation_outcomes: list[dict[str, Any]] = Field(default_factory=list)
    confidence: dict[str, Any] = Field(default_factory=dict)
    novelty_score: float = 0.0
    maturity_tier: str = "sparse"
    failure_reason: str | None = None
    quality_score: float = 0.0
    legacy_run: bool = False
    source_artifact_id: str | None = None


class DreamRunListResponse(BaseModel):
    items: list[DreamRunResponse]


class DreamProposalReviewRequest(BaseModel):
    action: Literal["approve", "reject", "request_more_evidence"]
    note: str | None = None


class DreamPredictionOutcomeRequest(BaseModel):
    status: Literal["confirmed", "contradicted", "request_more_evidence"]
    note: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class GraphDataResponse(BaseModel):
    """Response model for graph data endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "nodes": [
                    {"id": "1", "label": "Alice works at Google", "type": "world"},
                    {"id": "2", "label": "Bob went hiking", "type": "world"},
                ],
                "edges": [{"from": "1", "to": "2", "type": "semantic", "weight": 0.8}],
                "table_rows": [
                    {
                        "id": "abc12345...",
                        "text": "Alice works at Google",
                        "context": "Work info",
                        "date": "2024-01-15 10:30",
                        "entities": "Alice (PERSON), Google (ORGANIZATION)",
                    }
                ],
                "total_units": 2,
                "limit": 1000,
            }
        }
    )

    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    table_rows: list[dict[str, Any]]
    total_units: int
    limit: int


class TimelineTemporalResponse(BaseModel):
    anchor_at: str | None = None
    anchor_kind: str
    recorded_at: str | None = None
    direction: str
    confidence: float | None = None
    reference_text: str | None = None


class TimelineItemResponse(BaseModel):
    id: str
    kind: Literal["fact", "observation", "mental_model"]
    fact_type: str
    text: str
    context: str | None = None
    title: str | None = None
    anchor_at: str | None = None
    anchor_kind: str
    recorded_at: str | None = None
    occurred_start: str | None = None
    occurred_end: str | None = None
    temporal_direction: str
    temporal_confidence: float | None = None
    temporal_reference_text: str | None = None
    temporal: TimelineTemporalResponse
    entities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source_memory_ids: list[str] = Field(default_factory=list)
    proof_count: int = 0


class TimelineEdgeResponse(BaseModel):
    source: str
    target: str
    edge_kind: Literal["chronological", "temporal", "semantic", "entity", "causal", "source", "derived"]
    weight: float = 1.0


class TimelineResponse(BaseModel):
    items: list[TimelineItemResponse] = Field(default_factory=list)
    edges: list[TimelineEdgeResponse] = Field(default_factory=list)
    total_items: int
    limit: int


class GraphStateNodeResponse(BaseModel):
    id: str
    title: str
    kind: Literal["entity", "topic"]
    subtitle: str | None = None
    current_state: str
    status: Literal["stable", "changed", "contradictory", "stale"]
    status_reason: str
    confidence: float
    change_score: float
    last_changed_at: str | None = None
    primary_timestamp: str | None = None
    evidence_count: int
    tags: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class GraphRelationEdgeResponse(BaseModel):
    id: str
    source_id: str
    target_id: str
    relation_type: str
    strength: float
    evidence_count: int


class GraphChangeEventResponse(BaseModel):
    id: str
    node_id: str
    change_type: Literal["change", "contradiction", "stale"]
    before_state: str | None = None
    after_state: str
    confidence: float
    time_window: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    summary: str


class GraphEvidencePathStepResponse(BaseModel):
    kind: Literal["node", "event", "memory"]
    id: str
    label: str
    timestamp: str | None = None


class GraphIntelligenceResponse(BaseModel):
    nodes: list[GraphStateNodeResponse]
    edges: list[GraphRelationEdgeResponse]
    change_events: list[GraphChangeEventResponse]
    total_nodes: int
    generated_at: str
    cached: bool = False


class GraphInvestigationRequest(BaseModel):
    query: str
    type: str | None = None
    tags: list[str] | None = None
    tags_match: TagsMatch = Field(default="all_strict")
    confidence_min: float = Field(default=0.55, ge=0.0, le=1.0)
    node_kind: Literal["all", "entity", "topic"] = "all"
    window_days: int | None = Field(default=90, ge=1)
    limit: int = Field(default=18, ge=1, le=100)


class GraphInvestigationResponse(BaseModel):
    answer: str
    focal_node_ids: list[str] = Field(default_factory=list)
    focal_edge_ids: list[str] = Field(default_factory=list)
    change_events: list[GraphChangeEventResponse] = Field(default_factory=list)
    evidence_path: list[GraphEvidencePathStepResponse] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)


class GraphSummaryItemResponse(BaseModel):
    id: str
    kind: Literal["cluster", "node"]
    title: str
    subtitle: str | None = None
    preview_labels: list[str] = Field(default_factory=list)
    member_count: int
    status_tone: Literal["stable", "changed", "contradictory", "stale", "neutral"] = "neutral"
    display_priority: float
    render_mode_hint: Literal["detail", "compact", "overview"]
    cluster_membership: list[str] = Field(default_factory=list)
    node_ref: str | None = None


class GraphSummaryEdgeResponse(BaseModel):
    id: str
    source_id: str
    target_id: str
    weight: float
    label: str | None = None


class GraphSummaryResponse(BaseModel):
    surface: Literal["state", "evidence"]
    mode_hint: Literal["detail", "compact", "overview"]
    total_nodes: int
    total_edges: int
    clusters: list[GraphSummaryItemResponse] = Field(default_factory=list)
    top_nodes: list[GraphSummaryItemResponse] = Field(default_factory=list)
    bundled_edges: list[GraphSummaryEdgeResponse] = Field(default_factory=list)
    initial_focus_ids: list[str] = Field(default_factory=list)
    generated_at: str
    cached: bool = False


class GraphNeighborhoodNodeResponse(BaseModel):
    id: str
    node_type: Literal["state", "event", "evidence"]
    title: str
    subtitle: str | None = None
    preview: str | None = None
    status_label: str | None = None
    status_tone: Literal["stable", "changed", "contradictory", "stale", "neutral"] = "neutral"
    confidence: float | None = None
    evidence_count: int | None = None
    kind_label: str | None = None
    meta: str | None = None
    timestamp_label: str | None = None
    reason: str | None = None
    accent_color: str | None = None
    display_priority: float = 0.0
    node_density_hint: float = 0.0
    cluster_membership: str | None = None
    render_mode_hint: Literal["detail", "compact", "overview"] = "detail"


class GraphNeighborhoodEdgeResponse(BaseModel):
    id: str
    source: str
    target: str
    kind: Literal["relation", "event", "evidence"] = "relation"
    label: str | None = None
    stroke: str | None = None
    dashed: bool = False
    width: float = 1.6
    animated: bool = True
    priority: float = 0.0


class GraphNeighborhoodResponse(BaseModel):
    surface: Literal["state", "evidence"]
    mode_hint: Literal["detail", "compact", "overview"]
    focus_ids: list[str] = Field(default_factory=list)
    nodes: list[GraphNeighborhoodNodeResponse] = Field(default_factory=list)
    edges: list[GraphNeighborhoodEdgeResponse] = Field(default_factory=list)
    total_nodes: int
    total_edges: int
    has_more: bool = False
    cursor: str | None = None
    generated_at: str
    cached: bool = False


class AnomalyCorrectionResponse(BaseModel):
    id: str
    bank_id: str
    anomaly_id: str
    correction_type: str
    target_unit_id: str | None = None
    before_state: dict[str, Any] = Field(default_factory=dict)
    after_state: dict[str, Any] = Field(default_factory=dict)
    confidence_delta: float | None = None
    applied_at: str | None = None
    applied_by: str


class AnomalyEventResponse(BaseModel):
    id: str
    bank_id: str
    anomaly_type: str
    severity: float
    status: Literal["open", "acknowledged", "resolved", "suppressed"]
    unit_ids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    description: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    detected_at: str | None = None
    resolved_at: str | None = None
    resolved_by: str | None = None
    corrections: list[AnomalyCorrectionResponse] = Field(default_factory=list)


class AnomalyIntelligenceRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    status: Literal["open", "acknowledged", "resolved", "suppressed"] | None = None
    anomaly_types: list[str] | None = None
    min_severity: float = Field(default=0.0, ge=0.0, le=1.0)


class AnomalyIntelligenceSummaryResponse(BaseModel):
    total_events: int
    open_events: int
    resolved_events: int
    avg_severity: float = Field(ge=0.0, le=1.0)
    by_type: dict[str, int] = Field(default_factory=dict)


class AnomalyIntelligenceResponse(BaseModel):
    summary: AnomalyIntelligenceSummaryResponse
    events: list[AnomalyEventResponse] = Field(default_factory=list)
    total_events_in_response: int


class ListMemoryUnitsResponse(BaseModel):
    """Response model for list memory units endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "text": "Alice works at Google on the AI team",
                        "context": "Work conversation",
                        "date": "2024-01-15T10:30:00Z",
                        "type": "world",
                        "entities": "Alice (PERSON), Google (ORGANIZATION)",
                    }
                ],
                "total": 150,
                "limit": 100,
                "offset": 0,
            }
        }
    )

    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class ListDocumentsResponse(BaseModel):
    """Response model for list documents endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": "session_1",
                        "bank_id": "user123",
                        "content_hash": "abc123",
                        "created_at": "2024-01-15T10:30:00Z",
                        "updated_at": "2024-01-15T10:30:00Z",
                        "text_length": 5420,
                        "memory_unit_count": 15,
                        "tags": ["user_a", "session_123"],
                    }
                ],
                "total": 50,
                "limit": 100,
                "offset": 0,
            }
        }
    )

    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class TagItem(BaseModel):
    """Single tag with usage count."""

    tag: str = Field(description="The tag value")
    count: int = Field(description="Number of memories with this tag")


class ListTagsResponse(BaseModel):
    """Response model for list tags endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {"tag": "user:alice", "count": 42},
                    {"tag": "user:bob", "count": 15},
                    {"tag": "session:abc123", "count": 8},
                ],
                "total": 25,
                "limit": 100,
                "offset": 0,
            }
        }
    )

    items: list[TagItem]
    total: int
    limit: int
    offset: int


class DocumentResponse(BaseModel):
    """Response model for get document endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "session_1",
                "bank_id": "user123",
                "original_text": "Full document text here...",
                "content_hash": "abc123",
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T10:30:00Z",
                "memory_unit_count": 15,
                "tags": ["user_a", "session_123"],
            }
        }
    )

    id: str
    bank_id: str
    original_text: str
    content_hash: str | None
    created_at: str
    updated_at: str
    memory_unit_count: int
    tags: list[str] = FieldWithDefault(list, description="Tags associated with this document")


class DeleteDocumentResponse(BaseModel):
    """Response model for delete document endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "message": "Document 'session_1' and 5 associated memory units deleted successfully",
                "document_id": "session_1",
                "memory_units_deleted": 5,
            }
        }
    )

    success: bool
    message: str
    document_id: str
    memory_units_deleted: int


class ChunkResponse(BaseModel):
    """Response model for get chunk endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "chunk_id": "user123_session_1_0",
                "document_id": "session_1",
                "bank_id": "user123",
                "chunk_index": 0,
                "chunk_text": "This is the first chunk of the document...",
                "created_at": "2024-01-15T10:30:00Z",
            }
        }
    )

    chunk_id: str
    document_id: str
    bank_id: str
    chunk_index: int
    chunk_text: str
    created_at: str


class DeleteResponse(BaseModel):
    """Response model for delete operations."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"success": True, "message": "Deleted successfully", "deleted_count": 10}}
    )

    success: bool
    message: str | None = None
    deleted_count: int | None = None


class ClearMemoryObservationsResponse(BaseModel):
    """Response model for clearing observations for a specific memory."""

    model_config = ConfigDict(json_schema_extra={"example": {"deleted_count": 3}})

    deleted_count: int


class BankStatsResponse(BaseModel):
    """Response model for bank statistics endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "bank_id": "user123",
                "total_nodes": 150,
                "total_links": 300,
                "total_documents": 10,
                "nodes_by_fact_type": {"fact": 100, "preference": 30, "observation": 20},
                "links_by_link_type": {"temporal": 150, "semantic": 100, "entity": 50},
                "links_by_fact_type": {"fact": 200, "preference": 60, "observation": 40},
                "links_breakdown": {"fact": {"temporal": 100, "semantic": 60, "entity": 40}},
                "pending_operations": 2,
                "failed_operations": 0,
                "last_consolidated_at": "2024-01-15T10:30:00Z",
                "pending_consolidation": 0,
                "total_observations": 45,
            }
        }
    )

    bank_id: str
    total_nodes: int
    total_links: int
    total_documents: int
    nodes_by_fact_type: dict[str, int]
    links_by_link_type: dict[str, int]
    links_by_fact_type: dict[str, int]
    links_breakdown: dict[str, dict[str, int]]
    pending_operations: int
    failed_operations: int
    # Consolidation stats
    last_consolidated_at: str | None = Field(default=None, description="When consolidation last ran (ISO format)")
    pending_consolidation: int = Field(default=0, description="Number of memories not yet processed into observations")
    total_observations: int = Field(default=0, description="Total number of observations")


# Mental Model models


# =========================================================================
# Directive Models
# =========================================================================


class DirectiveResponse(BaseModel):
    """Response model for a directive."""

    id: str
    bank_id: str
    name: str
    content: str
    priority: int = 0
    is_active: bool = True
    tags: list[str] = FieldWithDefault(list)
    created_at: str | None = None
    updated_at: str | None = None


class DirectiveListResponse(BaseModel):
    """Response model for listing directives."""

    items: list[DirectiveResponse]


class CreateDirectiveRequest(BaseModel):
    """Request model for creating a directive."""

    name: str = Field(description="Human-readable name for the directive")
    content: str = Field(description="The directive text to inject into prompts")
    priority: int = Field(default=0, description="Higher priority directives are injected first")
    is_active: bool = Field(default=True, description="Whether this directive is active")
    tags: list[str] = FieldWithDefault(list, description="Tags for filtering")


class UpdateDirectiveRequest(BaseModel):
    """Request model for updating a directive."""

    name: str | None = Field(default=None, description="New name")
    content: str | None = Field(default=None, description="New content")
    priority: int | None = Field(default=None, description="New priority")
    is_active: bool | None = Field(default=None, description="New active status")
    tags: list[str] | None = Field(default=None, description="New tags")


# =========================================================================
# Mental Models (stored reflect responses)
# =========================================================================


class MentalModelTrigger(BaseModel):
    """Trigger settings for a mental model."""

    refresh_after_consolidation: bool = Field(
        default=False,
        description="If true, refresh this mental model after observations consolidation (real-time mode)",
    )


class MentalModelResponse(BaseModel):
    """Response model for a mental model (stored reflect response)."""

    id: str
    bank_id: str
    name: str
    source_query: str
    content: str = Field(
        description="The mental model content as well-formatted markdown (auto-generated from reflect endpoint)"
    )
    tags: list[str] = FieldWithDefault(list)
    max_tokens: int = Field(default=2048)
    trigger: MentalModelTrigger = FieldWithDefault(MentalModelTrigger)
    last_refreshed_at: str | None = None
    created_at: str | None = None
    reflect_response: dict | None = Field(
        default=None,
        description="Full reflect API response payload including based_on facts and observations",
    )


class MentalModelListResponse(BaseModel):
    """Response model for listing mental models."""

    items: list[MentalModelResponse]


class CreateMentalModelRequest(BaseModel):
    """Request model for creating a mental model."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "team-communication",
                "name": "Team Communication Preferences",
                "source_query": "How does the team prefer to communicate?",
                "tags": ["team"],
                "max_tokens": 2048,
                "trigger": {"refresh_after_consolidation": False},
            }
        }
    )

    id: str | None = Field(
        None, description="Optional custom ID for the mental model (alphanumeric lowercase with hyphens)"
    )
    name: str = Field(description="Human-readable name for the mental model")
    source_query: str = Field(description="The query to run to generate content")
    tags: list[str] = FieldWithDefault(list, description="Tags for scoped visibility")
    max_tokens: int = Field(default=2048, ge=256, le=8192, description="Maximum tokens for generated content")
    trigger: MentalModelTrigger = FieldWithDefault(MentalModelTrigger, description="Trigger settings")


class CreateMentalModelResponse(BaseModel):
    """Response model for mental model creation."""

    mental_model_id: str | None = Field(None, description="ID of the created mental model")
    operation_id: str = Field(description="Operation ID to track refresh progress")


class UpdateMentalModelRequest(BaseModel):
    """Request model for updating a mental model."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Updated Team Communication Preferences",
                "source_query": "How does the team prefer to communicate?",
                "max_tokens": 4096,
                "tags": ["team", "communication"],
                "trigger": {"refresh_after_consolidation": True},
            }
        }
    )

    name: str | None = Field(default=None, description="New name for the mental model")
    source_query: str | None = Field(default=None, description="New source query for the mental model")
    max_tokens: int | None = Field(default=None, ge=256, le=8192, description="Maximum tokens for generated content")
    tags: list[str] | None = Field(default=None, description="Tags for scoped visibility")
    trigger: MentalModelTrigger | None = Field(default=None, description="Trigger settings")


class OperationResponse(BaseModel):
    """Response model for a single async operation."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "task_type": "retain",
                "items_count": 5,
                "document_id": None,
                "created_at": "2024-01-15T10:30:00Z",
                "status": "pending",
                "error_message": None,
            }
        }
    )

    id: str
    task_type: str
    items_count: int
    document_id: str | None = None
    created_at: str
    status: str
    error_message: str | None


class ConsolidationResponse(BaseModel):
    """Response model for consolidation trigger endpoint."""

    operation_id: str = Field(description="ID of the async consolidation operation")
    deduplicated: bool = Field(default=False, description="True if an existing pending task was reused")


class OperationsListResponse(BaseModel):
    """Response model for list operations endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "bank_id": "user123",
                "total": 150,
                "limit": 20,
                "offset": 0,
                "operations": [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "task_type": "retain",
                        "created_at": "2024-01-15T10:30:00Z",
                        "status": "pending",
                        "error_message": None,
                    }
                ],
            }
        }
    )

    bank_id: str
    total: int
    limit: int
    offset: int
    operations: list[OperationResponse]


class CancelOperationResponse(BaseModel):
    """Response model for cancel operation endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "message": "Operation 550e8400-e29b-41d4-a716-446655440000 cancelled",
                "operation_id": "550e8400-e29b-41d4-a716-446655440000",
            }
        }
    )

    success: bool
    message: str
    operation_id: str


class ChildOperationStatus(BaseModel):
    """Status of a child operation (for batch operations)."""

    operation_id: str
    status: str
    sub_batch_index: int | None = None
    items_count: int | None = None
    error_message: str | None = None


class OperationStatusResponse(BaseModel):
    """Response model for getting a single operation status."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "operation_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "completed",
                "operation_type": "refresh_mental_models",
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T10:31:30Z",
                "completed_at": "2024-01-15T10:31:30Z",
                "error_message": None,
            }
        }
    )

    operation_id: str
    status: Literal["pending", "completed", "failed", "not_found"]
    operation_type: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    stage: str | None = Field(
        default=None,
        description="High-level progress stage for pending async work, derived from result_metadata.operation_stage.",
    )
    result_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Internal metadata for debugging. Structure may change without notice. Not for production use.",
    )
    child_operations: list[ChildOperationStatus] | None = Field(
        default=None, description="Child operations for batch operations (if applicable)"
    )


class AsyncOperationSubmitResponse(BaseModel):
    """Response model for submitting an async operation."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "operation_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "queued",
            }
        }
    )

    operation_id: str
    status: str


class OperationResultResponse(BaseModel):
    """Response model for retrieving the final result of an async operation."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "operation_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "completed",
                "operation_type": "reflect",
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T10:31:30Z",
                "completed_at": "2024-01-15T10:31:30Z",
                "error_message": None,
                "stage": "persisting_result",
                "result": {"text": "Final answer"},
            }
        }
    )

    operation_id: str
    status: Literal["pending", "completed", "failed", "not_found"]
    operation_type: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    stage: str | None = None
    result: ReflectResponse | dict[str, Any] | None = None


class FeaturesInfo(BaseModel):
    """Feature flags indicating which capabilities are enabled."""

    observations: bool = Field(description="Whether observations (auto-consolidation) are enabled")
    timeline_v2: bool = Field(description="Whether the git-style timeline API/UI is enabled")
    mcp: bool = Field(description="Whether MCP (Model Context Protocol) server is enabled")
    worker: bool = Field(description="Whether the background worker is enabled")
    bank_config_api: bool = Field(description="Whether per-bank configuration API is enabled")
    file_upload_api: bool = Field(description="Whether file upload/conversion API is enabled")
    brain_runtime: bool = Field(description="Whether atulya-brain runtime is enabled")
    sub_routine: bool = Field(description="Whether sub_routine operations are enabled")
    brain_import_export: bool = Field(description="Whether .brain import/export APIs are enabled")


class VersionResponse(BaseModel):
    """Response model for the version/info endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "api_version": "0.4.0",
                "features": {
                    "observations": False,
                    "timeline_v2": False,
                    "mcp": True,
                    "worker": True,
                    "bank_config_api": False,
                    "file_upload_api": True,
                    "brain_runtime": True,
                    "sub_routine": True,
                    "brain_import_export": False,
                },
            }
        }
    )

    api_version: str = Field(description="API version string")
    features: FeaturesInfo = Field(description="Enabled feature flags")


class SubRoutineSubmitRequest(BaseModel):
    mode: Literal["warmup", "incremental", "full_copy"] = Field(default="incremental")
    horizon_hours: int = Field(default=24, ge=1, le=168)
    force_rebuild: bool = Field(default=False)


class BrainRuntimeStatusResponse(BaseModel):
    enabled: bool
    circuit_open: bool
    failure_count: int
    bank_id: str
    file_path: str
    exists: bool
    size_bytes: int
    last_modified_at: str | None = None
    source_snapshot_id: str | None = None
    generated_at: str | None = None
    native_library_loaded: bool
    format_version: int | None = None
    model_signature: str | None = None
    compatibility_reason: str | None = None
    metrics: dict[str, int] = Field(default_factory=dict)


class PredictionPoint(BaseModel):
    hour_utc: int
    score: float


class SubRoutinePredictionResponse(BaseModel):
    bank_id: str
    horizon_hours: int
    predictions: list[PredictionPoint]
    sample_count: int = 0
    source_snapshot_id: str | None = None
    model_signature: str | None = None


class SubRoutineHistogramResponse(BaseModel):
    bank_id: str
    histogram: list[PredictionPoint]
    sample_count: int = 0
    source_snapshot_id: str | None = None
    model_signature: str | None = None


class BrainImportValidationResponse(BaseModel):
    valid: bool
    version: int | None = None
    reason: str | None = None


class BrainImportResponse(BaseModel):
    bank_id: str
    file_path: str
    size_bytes: int
    format_version: int | None = None


class BrainLearnRequest(BaseModel):
    remote_endpoint: str = Field(description="URL of the remote Atulya API (e.g. http://host:8888)")
    remote_bank_id: str = Field(description="Bank ID on the remote instance to learn from")
    remote_api_key: str = Field(default="", description="Optional API key for the remote instance")
    learning_type: Literal["auto", "distilled", "structured", "raw_mirror"] = Field(default="auto")
    mode: Literal["incremental", "full_copy"] = Field(default="incremental")
    horizon_hours: int = Field(default=24, ge=1, le=168)


class BrainLearnResponse(BaseModel):
    operation_id: str
    deduplicated: bool = False


class InfluenceContribution(BaseModel):
    recency: float
    freq: float
    graph: float
    rerank: float
    dream: float


class InfluenceRow(BaseModel):
    id: str
    type: str
    text: str
    access_count: int
    influence_score: float
    contribution: InfluenceContribution
    last_accessed_at: str | None = None


class InfluenceHeatmapPoint(BaseModel):
    weekday: int
    hour_utc: int
    count: int
    score: float


class InfluenceTrendPoint(BaseModel):
    index: int
    raw: float
    ewma: float
    lower: float
    upper: float


class BrainInfluenceResponse(BaseModel):
    bank_id: str
    window_days: int
    entity_type: str
    leaderboard: list[InfluenceRow]
    heatmap: list[InfluenceHeatmapPoint]
    trend: list[InfluenceTrendPoint]
    anomalies: list[dict[str, Any]]
    summary: dict[str, Any]


# =========================================================================
# Webhook Models
# =========================================================================


from atulya_api.webhooks.models import WebhookHttpConfig


class CreateWebhookRequest(BaseModel):
    """Request model for registering a webhook."""

    url: str = Field(description="HTTP(S) endpoint URL to deliver events to")
    secret: str | None = Field(default=None, description="HMAC-SHA256 signing secret (optional)")
    event_types: list[str] = Field(
        default=["consolidation.completed"],
        description="List of event types to deliver. Currently supported: 'consolidation.completed'",
    )
    enabled: bool = Field(default=True, description="Whether this webhook is active")
    http_config: WebhookHttpConfig = Field(
        default_factory=WebhookHttpConfig,
        description="HTTP delivery configuration (method, timeout, headers, params)",
    )


class WebhookResponse(BaseModel):
    """Response model for a webhook."""

    id: str
    bank_id: str | None
    url: str
    secret: str | None = Field(default=None, description="Signing secret (redacted in responses)")
    event_types: list[str]
    enabled: bool
    http_config: WebhookHttpConfig = Field(default_factory=WebhookHttpConfig)
    created_at: str | None = None
    updated_at: str | None = None


class UpdateWebhookRequest(BaseModel):
    """Request model for updating a webhook. Only provided fields are updated."""

    url: str | None = Field(default=None, description="HTTP(S) endpoint URL")
    secret: str | None = Field(
        default=None, description="HMAC-SHA256 signing secret. Omit to keep existing; send null to clear."
    )
    event_types: list[str] | None = Field(default=None, description="List of event types")
    enabled: bool | None = Field(default=None, description="Whether this webhook is active")
    http_config: WebhookHttpConfig | None = Field(default=None, description="HTTP delivery configuration")


class WebhookListResponse(BaseModel):
    """Response model for listing webhooks."""

    items: list[WebhookResponse]


class WebhookDeliveryResponse(BaseModel):
    """Response model for a webhook delivery record."""

    id: str
    webhook_id: str | None
    url: str
    event_type: str
    status: str
    attempts: int
    next_retry_at: str | None = None
    last_error: str | None = None
    last_response_status: int | None = None
    last_response_body: str | None = None
    last_attempt_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_async_operation_row(cls, row: dict) -> "WebhookDeliveryResponse":
        import json as _json

        raw = row["task_payload"]
        if isinstance(raw, str):
            task_payload = _json.loads(raw)
        elif isinstance(raw, dict):
            task_payload = raw
        else:
            task_payload = {}

        raw_meta = row.get("result_metadata")
        if isinstance(raw_meta, str):
            result_metadata = _json.loads(raw_meta) if raw_meta else {}
        elif isinstance(raw_meta, dict):
            result_metadata = raw_meta
        else:
            result_metadata = {}

        return cls(
            id=str(row["operation_id"]),
            webhook_id=task_payload.get("webhook_id"),
            url=task_payload.get("url", ""),
            event_type=task_payload.get("event_type", ""),
            status=row["status"],
            attempts=row["retry_count"] + 1,
            next_retry_at=row["next_retry_at"],
            last_error=row["error_message"],
            last_response_status=result_metadata.get("last_status_code"),
            last_response_body=result_metadata.get("last_response_body"),
            last_attempt_at=result_metadata.get("last_attempt_at"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class WebhookDeliveryListResponse(BaseModel):
    """Response model for listing webhook deliveries."""

    items: list[WebhookDeliveryResponse]
    next_cursor: str | None = None


def create_app(
    memory: MemoryEngine,
    initialize_memory: bool = True,
    http_extension: HttpExtension | None = None,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        memory: MemoryEngine instance (already initialized with required parameters).
                Migrations are controlled by the MemoryEngine's run_migrations parameter.
        initialize_memory: Whether to initialize memory system on startup (default: True)
        http_extension: Optional HTTP extension to mount custom endpoints under /extension/.
                       If None, attempts to load from ATULYA_API_HTTP_EXTENSION env var.

    Returns:
        Configured FastAPI application

    Note:
        When mounting this app as a sub-application, the lifespan events may not fire.
        In that case, you should call memory.initialize() manually before starting the server
        and memory.close() when shutting down.
    """
    # Load HTTP extension from environment if not provided
    if http_extension is None:
        http_extension = load_extension("HTTP", HttpExtension)
        if http_extension:
            logging.info(f"Loaded HTTP extension: {http_extension.__class__.__name__}")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """
        Lifespan context manager for startup and shutdown events.
        Note: This only fires when running the app standalone, not when mounted.
        """
        import asyncio
        import socket

        from atulya_api.config import get_config
        from atulya_api.worker import WorkerPoller

        config = get_config()
        poller = None
        poller_task = None

        # Initialize OpenTelemetry metrics
        try:
            prometheus_reader = initialize_metrics(service_name="atulya-api")
            create_metrics_collector()
            app.state.prometheus_reader = prometheus_reader
            logging.info("Metrics initialized - available at /metrics endpoint")
        except Exception as e:
            logging.warning(f"Failed to initialize metrics: {e}. Metrics will be disabled (using no-op collector).")
            app.state.prometheus_reader = None
            # Metrics collector is already initialized as no-op by default

        # Initialize OpenTelemetry tracing if enabled
        if config.otel_traces_enabled:
            if not config.otel_exporter_otlp_endpoint:
                logging.warning("OTEL tracing enabled but no endpoint configured. Tracing disabled.")
            else:
                from atulya_api.tracing import create_span_recorder, initialize_tracing

                try:
                    initialize_tracing(
                        service_name=config.otel_service_name,
                        endpoint=config.otel_exporter_otlp_endpoint,
                        headers=config.otel_exporter_otlp_headers,
                        deployment_environment=config.otel_deployment_environment,
                    )
                    create_span_recorder()
                    logging.info("OpenTelemetry tracing enabled and configured")
                except Exception as e:
                    logging.error(f"Failed to initialize tracing: {e}")
                    logging.warning("Continuing without tracing")

        # Startup: Initialize database and memory system (migrations run inside initialize if enabled)
        if initialize_memory:
            await memory.initialize()
            logging.info("Memory system initialized")

            # Set up DB pool metrics after memory initialization
            metrics_collector = get_metrics_collector()
            if memory._pool is not None and hasattr(metrics_collector, "set_db_pool"):
                metrics_collector.set_db_pool(memory._pool)
                logging.info("DB pool metrics configured")

        # Optional non-blocking startup warmup for sub_routine
        if config.brain_startup_warmup:

            async def _warmup():
                try:
                    queued = await memory.enqueue_startup_brain_warmup()
                    logging.info("Startup sub_routine warmup queued for %s bank(s)", queued)
                except Exception as exc:
                    logging.warning("Startup sub_routine warmup failed (non-fatal): %s", exc)

            asyncio.create_task(_warmup())

        # Start worker poller if enabled (standalone mode)
        if config.worker_enabled and memory._pool is not None:
            from ..config import DEFAULT_DATABASE_SCHEMA

            worker_id = config.worker_id or socket.gethostname()
            # Convert default schema to None for SQL compatibility (no schema prefix)
            schema = None if config.database_schema == DEFAULT_DATABASE_SCHEMA else config.database_schema
            poller = WorkerPoller(
                pool=memory._pool,
                worker_id=worker_id,
                executor=memory.execute_task,
                poll_interval_ms=config.worker_poll_interval_ms,
                schema=schema,
                tenant_extension=memory._tenant_extension,
                max_slots=config.worker_max_slots,
                consolidation_max_slots=config.worker_consolidation_max_slots,
                sub_routine_max_slots=config.worker_sub_routine_max_slots,
            )
            poller_task = asyncio.create_task(poller.run())
            logging.info(f"Worker poller started (worker_id={worker_id})")

        # Call tenant extension startup hook (e.g. JWKS fetch for Supabase)
        tenant_extension = memory.tenant_extension
        if tenant_extension:
            await tenant_extension.on_startup()
            logging.info("Tenant extension started")

        # Call HTTP extension startup hook
        if http_extension:
            await http_extension.on_startup()
            logging.info("HTTP extension started")

        yield

        # Shutdown worker poller if running
        if poller is not None:
            await poller.shutdown_graceful(timeout=30.0)
            if poller_task is not None:
                poller_task.cancel()
                try:
                    await poller_task
                except asyncio.CancelledError:
                    pass
            logging.info("Worker poller stopped")

        # Call tenant extension shutdown hook
        if tenant_extension:
            await tenant_extension.on_shutdown()
            logging.info("Tenant extension stopped")

        # Call HTTP extension shutdown hook
        if http_extension:
            await http_extension.on_shutdown()
            logging.info("HTTP extension stopped")

        # Shutdown: Cleanup memory system
        await memory.close()
        logging.info("Memory system closed")

    from atulya_api import __version__
    from atulya_api.config import get_config

    config = get_config()

    app = FastAPI(
        title="Atulya HTTP API",
        version=__version__,
        description="HTTP API for Atulya",
        contact={
            "name": "Memory System",
        },
        license_info={
            "name": "Apache 2.0",
            "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
        },
        lifespan=lifespan,
        root_path=config.base_path,
    )

    # IMPORTANT: Set memory on app.state immediately, don't wait for lifespan
    # This is required for mounted sub-applications where lifespan may not fire
    app.state.memory = memory

    # Add HTTP metrics middleware
    @app.middleware("http")
    async def http_metrics_middleware(request, call_next):
        """Record HTTP request metrics."""
        # Normalize endpoint path to reduce cardinality
        # Replace UUIDs and numeric IDs with placeholders
        import re

        from starlette.requests import Request

        path = request.url.path
        # Replace UUIDs
        path = re.sub(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "/{id}", path)
        # Replace numeric IDs
        path = re.sub(r"/\d+(?=/|$)", "/{id}", path)

        status_code = [500]  # Default to 500, will be updated
        metrics_collector = get_metrics_collector()

        with metrics_collector.record_http_request(request.method, path, lambda: status_code[0]):
            try:
                response = await call_next(request)
                status_code[0] = response.status_code
                return response
            except asyncio.CancelledError:
                # Expected during graceful shutdown when in-flight requests are cancelled.
                # Return a client-closed style status to avoid noisy tracebacks.
                status_code[0] = 499
                return Response(status_code=499)

    # Register all routes
    _register_routes(app)

    # Mount HTTP extension router if available
    if http_extension:
        extension_router = http_extension.get_router(memory)
        app.include_router(extension_router, prefix="/ext", tags=["Extension"])
        logging.info("HTTP extension router mounted at /ext/")

        # Mount root router if provided (for well-known endpoints, etc.)
        root_router = http_extension.get_root_router(memory)
        if root_router:
            app.include_router(root_router)
            logging.info("HTTP extension root router mounted")

    return app


def _register_routes(app: FastAPI):
    """Register all API routes on the given app instance."""

    def get_request_context(authorization: str | None = Header(default=None)) -> RequestContext:
        """
        Extract request context from Authorization header.

        Supports:
        - Bearer token: "Bearer <api_key>"
        - Direct API key: "<api_key>"

        Returns RequestContext with extracted API key (may be None if no auth header).
        """
        api_key = None
        if authorization:
            if authorization.lower().startswith("bearer "):
                api_key = authorization[7:].strip()
            else:
                api_key = authorization.strip()
        return RequestContext(api_key=api_key)

    def _codebase_source_config_model(raw: dict[str, Any] | None) -> CodebaseSourceConfigResponse:
        return CodebaseSourceConfigResponse.model_validate(raw or {})

    def _codebase_stats_model(raw: dict[str, Any] | None) -> CodebaseSnapshotStatsResponse:
        return CodebaseSnapshotStatsResponse.model_validate(raw or {})

    def _codebase_response_model(raw: dict[str, Any]) -> CodebaseResponse:
        return CodebaseResponse.model_validate(
            {
                **raw,
                "source_config": _codebase_source_config_model(raw.get("source_config")),
                "stats": _codebase_stats_model(raw.get("stats")),
            }
        )

    # Global exception handler for authentication errors
    @app.exception_handler(AuthenticationError)
    async def authentication_error_handler(request, exc: AuthenticationError):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=401,
            content={"detail": str(exc)},
        )

    @app.get(
        "/health",
        summary="Health check endpoint",
        description="Checks the health of the API and database connection",
        tags=["Monitoring"],
    )
    async def health_endpoint():
        """
        Health check endpoint that verifies database connectivity.

        Returns 200 if healthy, 503 if unhealthy.
        """
        from fastapi.responses import JSONResponse

        health = await app.state.memory.health_check()
        status_code = 200 if health.get("status") == "healthy" else 503
        return JSONResponse(content=health, status_code=status_code)

    @app.get(
        "/version",
        response_model=VersionResponse,
        summary="Get API version and feature flags",
        description="Returns API version information and enabled feature flags. "
        "Use this to check which capabilities are available in this deployment.",
        tags=["Monitoring"],
        operation_id="get_version",
    )
    async def version_endpoint() -> VersionResponse:
        """
        Get API version and enabled features.

        Returns version info and feature flags that can be used by clients
        to determine which capabilities are available.

        Note: observations flag shows the global default. Individual banks
        may override this setting via bank-specific configuration.
        """
        from atulya_api import __version__
        from atulya_api.config import _get_raw_config

        config = _get_raw_config()
        return VersionResponse(
            api_version=__version__,
            features=FeaturesInfo(
                observations=config.enable_observations,
                timeline_v2=config.timeline_v2,
                mcp=config.mcp_enabled,
                worker=config.worker_enabled,
                bank_config_api=config.enable_bank_config_api,
                file_upload_api=config.enable_file_upload_api,
                brain_runtime=config.brain_enabled,
                sub_routine=config.brain_enabled,
                brain_import_export=config.brain_enabled and config.brain_import_export_enabled,
            ),
        )

    @app.get(
        "/metrics",
        summary="Prometheus metrics endpoint",
        description="Exports metrics in Prometheus format for scraping",
        tags=["Monitoring"],
    )
    async def metrics_endpoint():
        """Return Prometheus metrics."""
        from fastapi.responses import Response
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        metrics_data = generate_latest()
        return Response(content=metrics_data, media_type=CONTENT_TYPE_LATEST)

    @app.get(
        "/v1/default/banks/{bank_id}/graph",
        response_model=GraphDataResponse,
        summary="Get memory graph data",
        description="Retrieve graph data for visualization, optionally filtered by type (world/experience/opinion).",
        operation_id="get_graph",
        tags=["Memory"],
    )
    async def api_graph(
        bank_id: str,
        type: str | None = None,
        limit: int = 1000,
        q: str | None = None,
        tags: list[str] | None = Query(None),
        tags_match: str = "all_strict",
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Get graph data from database, filtered by bank_id and optionally by type."""
        try:
            data = await app.state.memory.get_graph_data(
                bank_id, type, limit=limit, q=q, tags=tags, tags_match=tags_match, request_context=request_context
            )
            return data
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/graph: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/timeline",
        response_model=TimelineResponse,
        summary="Get normalized timeline data",
        description="Retrieve git-style timeline items and edges for facts, observations, and mental models.",
        operation_id="get_timeline",
        tags=["Memory"],
    )
    async def api_timeline(
        bank_id: str,
        type: str | None = None,
        limit: int = 500,
        q: str | None = None,
        tags: list[str] | None = Query(None),
        tags_match: TagsMatch = "all_strict",
        request_context: RequestContext = Depends(get_request_context),
    ):
        try:
            data = await app.state.memory.get_timeline(
                bank_id=bank_id,
                fact_type=type,
                limit=limit,
                q=q,
                tags=tags,
                tags_match=tags_match,
                request_context=request_context,
            )
            return data
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/timeline: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/graph/intelligence",
        response_model=GraphIntelligenceResponse,
        summary="Get graph intelligence state graph",
        description="Retrieve a state/topic graph with high-confidence changes, contradictions, and stale signals.",
        operation_id="get_graph_intelligence",
        tags=["Memory"],
    )
    async def api_graph_intelligence(
        bank_id: str,
        type: str | None = None,
        limit: int = 18,
        q: str | None = None,
        tags: list[str] | None = Query(None),
        tags_match: TagsMatch = "all_strict",
        confidence_min: float = Query(0.55, ge=0.0, le=1.0),
        node_kind: Literal["all", "entity", "topic"] = "all",
        window_days: int | None = Query(90, ge=1),
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Return the graph intelligence state graph for a bank."""
        try:
            return await app.state.memory.get_graph_intelligence(
                bank_id,
                fact_type=type,
                limit=limit,
                q=q,
                tags=tags,
                tags_match=tags_match,
                confidence_min=confidence_min,
                node_kind=node_kind,
                window_days=window_days,
                request_context=request_context,
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/graph/intelligence: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/graph/investigate",
        response_model=GraphInvestigationResponse,
        summary="Investigate graph intelligence",
        description="Ask a focused question over the state graph and return the relevant change events, evidence path, and checks.",
        operation_id="investigate_graph",
        tags=["Memory"],
    )
    async def api_graph_investigate(
        bank_id: str,
        request: GraphInvestigationRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Investigate graph signals for a bank using the state graph plus recall seeds."""
        try:
            return await app.state.memory.investigate_graph(
                bank_id,
                query=request.query,
                fact_type=request.type,
                limit=request.limit,
                tags=request.tags,
                tags_match=request.tags_match,
                confidence_min=request.confidence_min,
                node_kind=request.node_kind,
                window_days=request.window_days,
                request_context=request_context,
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/graph/investigate: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/anomaly/intelligence",
        response_model=AnomalyIntelligenceResponse,
        summary="Get anomaly intelligence for bank",
        operation_id="get_anomaly_intelligence",
        tags=["Memory"],
    )
    async def api_anomaly_intelligence(
        bank_id: str,
        request: AnomalyIntelligenceRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        try:
            return await app.state.memory.get_anomaly_intelligence(
                bank_id=bank_id,
                limit=request.limit,
                status=request.status,
                anomaly_types=request.anomaly_types,
                min_severity=request.min_severity,
                request_context=request_context,
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/anomaly/intelligence: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/graph/summary",
        response_model=GraphSummaryResponse,
        summary="Get scalable graph summary",
        description="Retrieve a clustered graph summary and top-use nodes for scalable graph exploration.",
        operation_id="get_graph_summary",
        tags=["Memory"],
    )
    async def api_graph_summary(
        bank_id: str,
        surface: Literal["state", "evidence"] = "state",
        type: str | None = None,
        q: str | None = None,
        tags: list[str] | None = Query(None),
        tags_match: TagsMatch = "all_strict",
        confidence_min: float = Query(0.55, ge=0.0, le=1.0),
        node_kind: Literal["all", "entity", "topic"] = "all",
        window_days: int | None = Query(90, ge=1),
        request_context: RequestContext = Depends(get_request_context),
    ):
        try:
            return await app.state.memory.get_graph_summary(
                bank_id,
                surface=surface,
                fact_type=type,
                q=q,
                tags=tags,
                tags_match=tags_match,
                confidence_min=confidence_min,
                node_kind=node_kind,
                window_days=window_days,
                request_context=request_context,
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/graph/summary: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/graph/neighborhood",
        response_model=GraphNeighborhoodResponse,
        summary="Get focused graph neighborhood",
        description="Retrieve a bounded neighborhood for focused graph exploration and detail rendering.",
        operation_id="get_graph_neighborhood",
        tags=["Memory"],
    )
    async def api_graph_neighborhood(
        bank_id: str,
        surface: Literal["state", "evidence"] = "state",
        type: str | None = None,
        q: str | None = None,
        tags: list[str] | None = Query(None),
        tags_match: TagsMatch = "all_strict",
        confidence_min: float = Query(0.55, ge=0.0, le=1.0),
        node_kind: Literal["all", "entity", "topic"] = "all",
        window_days: int | None = Query(90, ge=1),
        focus_ids: list[str] | None = Query(None),
        depth: int = Query(1, ge=1, le=3),
        limit_nodes: int = Query(60, ge=1, le=120),
        limit_edges: int = Query(140, ge=1, le=300),
        request_context: RequestContext = Depends(get_request_context),
    ):
        try:
            return await app.state.memory.get_graph_neighborhood(
                bank_id,
                surface=surface,
                fact_type=type,
                q=q,
                tags=tags,
                tags_match=tags_match,
                confidence_min=confidence_min,
                node_kind=node_kind,
                window_days=window_days,
                focus_ids=focus_ids,
                depth=depth,
                limit_nodes=limit_nodes,
                limit_edges=limit_edges,
                request_context=request_context,
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/graph/neighborhood: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/memories/list",
        response_model=ListMemoryUnitsResponse,
        summary="List memory units",
        description="List memory units with pagination and optional full-text search. Supports filtering by type. Results are sorted by most recent first (mentioned_at DESC, then created_at DESC).",
        operation_id="list_memories",
        tags=["Memory"],
    )
    async def api_list(
        bank_id: str,
        type: str | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """
        List memory units for table view with optional full-text search.

        Results are ordered by most recent first, using mentioned_at timestamp
        (when the memory was mentioned/learned), falling back to created_at.

        Args:
            bank_id: Memory Bank ID (from path)
            type: Filter by fact type (world, experience, opinion)
            q: Search query for full-text search (searches text and context)
            limit: Maximum number of results (default: 100)
            offset: Offset for pagination (default: 0)
        """
        try:
            data = await app.state.memory.list_memory_units(
                bank_id=bank_id,
                fact_type=type,
                search_query=q,
                limit=limit,
                offset=offset,
                request_context=request_context,
            )
            return data
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/memories/list: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/memories/{memory_id}",
        summary="Get memory unit",
        description="Get a single memory unit by ID with all its metadata including entities and tags. Note: the 'history' field is deprecated and always returns an empty list - use GET /memories/{memory_id}/history instead.",
        operation_id="get_memory",
        tags=["Memory"],
    )
    async def api_get_memory(
        bank_id: str,
        memory_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Get a single memory unit by ID."""
        try:
            data = await app.state.memory.get_memory_unit(
                bank_id=bank_id,
                memory_id=memory_id,
                request_context=request_context,
            )
            if data is None:
                raise HTTPException(status_code=404, detail=f"Memory unit '{memory_id}' not found")
            return data
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/memories/{memory_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/memories/{memory_id}/history",
        summary="Get observation history",
        description="Get the full history of an observation, with each change's source facts resolved to their text.",
        operation_id="get_observation_history",
        tags=["Memory"],
    )
    async def api_get_observation_history(
        bank_id: str,
        memory_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Get the history of a single observation by ID."""
        try:
            data = await app.state.memory.get_observation_history(
                bank_id=bank_id,
                memory_id=memory_id,
                request_context=request_context,
            )
            if data is None:
                raise HTTPException(status_code=404, detail=f"Memory unit '{memory_id}' not found")
            return data
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/memories/{memory_id}/history: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/memories/recall",
        response_model=RecallResponse,
        summary="Recall memory",
        description="Recall memory using semantic similarity and spreading activation.\n\n"
        "The type parameter is optional and must be one of:\n"
        "- `world`: General knowledge about people, places, events, and things that happen\n"
        "- `experience`: Memories about experience, conversations, actions taken, and tasks performed",
        operation_id="recall_memories",
        tags=["Memory"],
    )
    async def api_recall(
        bank_id: str, request: RecallRequest, request_context: RequestContext = Depends(get_request_context)
    ):
        """Run a recall and return results with trace."""
        import time

        handler_start = time.time()
        metrics = get_metrics_collector()

        # Validate query length to prevent expensive operations on oversized queries
        encoding = _get_tiktoken_encoding()
        query_tokens = len(encoding.encode(request.query))
        if query_tokens > MAX_QUERY_TOKENS:
            raise HTTPException(
                status_code=400,
                detail=f"Query too long: {query_tokens} tokens exceeds maximum of {MAX_QUERY_TOKENS}. Please shorten your query.",
            )

        try:
            # Default to world and experience if not specified (exclude observation)
            fact_types = request.types if request.types else list(VALID_RECALL_FACT_TYPES)

            # Parse query_timestamp if provided
            question_date = None
            if request.query_timestamp:
                try:
                    question_date = datetime.fromisoformat(request.query_timestamp.replace("Z", "+00:00"))
                except ValueError as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid query_timestamp format. Expected ISO format (e.g., '2023-05-30T23:40:00'): {str(e)}",
                    )

            # Determine entity inclusion settings
            include_entities = request.include.entities is not None
            max_entity_tokens = request.include.entities.max_tokens if include_entities else 500

            # Determine chunk inclusion settings
            include_chunks = request.include.chunks is not None
            max_chunk_tokens = request.include.chunks.max_tokens if include_chunks else 8192

            # Determine source facts inclusion settings
            include_source_facts = request.include.source_facts is not None
            max_source_facts_tokens = request.include.source_facts.max_tokens if include_source_facts else 4096
            max_source_facts_tokens_per_observation = (
                request.include.source_facts.max_tokens_per_observation if include_source_facts else -1
            )

            pre_recall = time.time() - handler_start
            # Run recall with tracing (record metrics)
            with metrics.record_operation(
                "recall", bank_id=bank_id, source="api", budget=request.budget.value, max_tokens=request.max_tokens
            ):
                recall_start = time.time()
                core_result = await app.state.memory.recall_async(
                    bank_id=bank_id,
                    query=request.query,
                    budget=request.budget,
                    max_tokens=request.max_tokens,
                    enable_trace=request.trace,
                    fact_type=fact_types,
                    question_date=question_date,
                    include_entities=include_entities,
                    max_entity_tokens=max_entity_tokens,
                    include_chunks=include_chunks,
                    max_chunk_tokens=max_chunk_tokens,
                    include_source_facts=include_source_facts,
                    max_source_facts_tokens=max_source_facts_tokens,
                    max_source_facts_tokens_per_observation=max_source_facts_tokens_per_observation,
                    request_context=request_context,
                    tags=request.tags,
                    tags_match=request.tags_match,
                )

            # Convert core MemoryFact objects to API RecallResult objects (excluding internal metrics)
            def _fact_to_result(fact: "MemoryFact") -> RecallResult:
                return RecallResult(
                    id=fact.id,
                    text=fact.text,
                    type=fact.fact_type,
                    entities=fact.entities,
                    context=fact.context,
                    occurred_start=fact.occurred_start,
                    occurred_end=fact.occurred_end,
                    mentioned_at=fact.mentioned_at,
                    document_id=fact.document_id,
                    chunk_id=fact.chunk_id,
                    tags=fact.tags,
                    source_fact_ids=fact.source_fact_ids,
                )

            recall_results = [_fact_to_result(fact) for fact in core_result.results]

            # Convert chunks from engine to HTTP API format
            chunks_response = None
            if core_result.chunks:
                chunks_response = {}
                for chunk_id, chunk_info in core_result.chunks.items():
                    chunks_response[chunk_id] = ChunkData(
                        id=chunk_id,
                        text=chunk_info.chunk_text,
                        chunk_index=chunk_info.chunk_index,
                        truncated=chunk_info.truncated,
                    )

            # Convert core EntityState objects to API EntityStateResponse objects
            entities_response = None
            if core_result.entities:
                entities_response = {}
                for name, state in core_result.entities.items():
                    entities_response[name] = EntityStateResponse(
                        entity_id=state.entity_id,
                        canonical_name=state.canonical_name,
                        observations=[
                            EntityObservationResponse(text=obs.text, mentioned_at=obs.mentioned_at)
                            for obs in state.observations
                        ],
                    )

            # Convert source facts dict to API format
            source_facts_response = None
            if core_result.source_facts:
                source_facts_response = {
                    fact_id: _fact_to_result(fact) for fact_id, fact in core_result.source_facts.items()
                }

            response = RecallResponse(
                results=recall_results,
                trace=core_result.trace,
                entities=entities_response,
                chunks=chunks_response,
                source_facts=source_facts_response,
            )

            handler_duration = time.time() - handler_start
            recall_duration = time.time() - recall_start
            post_recall = handler_duration - pre_recall - recall_duration
            if handler_duration > 1.0:
                logging.info(
                    f"[RECALL HTTP] bank={bank_id} handler_total={handler_duration:.3f}s "
                    f"pre={pre_recall:.3f}s recall={recall_duration:.3f}s post={post_recall:.3f}s "
                    f"results={len(recall_results)} entities={len(entities_response) if entities_response else 0}"
                )

            return response
        except HTTPException:
            raise
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except (asyncio.TimeoutError, TimeoutError):
            handler_duration = time.time() - handler_start
            logger.error(
                f"[RECALL TIMEOUT] bank={bank_id} handler_duration={handler_duration:.3f}s - database query timed out"
            )
            raise HTTPException(
                status_code=504,
                detail="Request timed out while searching memories. Try a shorter or more specific query.",
            )
        except Exception as e:
            import traceback

            handler_duration = time.time() - handler_start
            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(
                f"[RECALL ERROR] bank={bank_id} handler_duration={handler_duration:.3f}s error={str(e)}\n{error_detail}"
            )
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/reflect",
        response_model=ReflectResponse,
        summary="Reflect and generate answer",
        description="Reflect and formulate an answer using bank identity, world facts, and opinions.\n\n"
        "This endpoint:\n"
        "1. Retrieves experience (conversations and events)\n"
        "2. Retrieves world facts relevant to the query\n"
        "3. Retrieves existing opinions (bank's perspectives)\n"
        "4. Uses LLM to formulate a contextual answer\n"
        "5. Returns plain text answer and the facts used",
        operation_id="reflect",
        tags=["Memory"],
    )
    async def api_reflect(
        bank_id: str, request: ReflectRequest, request_context: RequestContext = Depends(get_request_context)
    ):
        metrics = get_metrics_collector()

        try:
            query = compose_reflect_query(request.query, request.context)

            # Use the memory system's reflect_async method (record metrics)
            with metrics.record_operation("reflect", bank_id=bank_id, source="api", budget=request.budget.value):
                core_result = await app.state.memory.reflect_async(
                    bank_id=bank_id,
                    query=query,
                    budget=request.budget,
                    context=None,  # Deprecated, now concatenated with query
                    max_tokens=request.max_tokens,
                    response_schema=request.response_schema,
                    request_context=request_context,
                    tags=request.tags,
                    tags_match=request.tags_match,
                )

            return serialize_reflect_response(
                core_result,
                include_facts=request.include.facts is not None,
                include_tool_calls=request.include.tool_calls is not None,
                include_tool_call_output=request.include.tool_calls.output
                if request.include.tool_calls is not None
                else True,
            )

        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/reflect: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/reflect/submit",
        response_model=AsyncOperationSubmitResponse,
        summary="Submit async reflect",
        description="Queue a reflect operation for background execution and retrieve the result via the operations API.",
        operation_id="submit_async_reflect",
        tags=["Memory"],
    )
    async def api_submit_async_reflect(
        bank_id: str, request: ReflectRequest, request_context: RequestContext = Depends(get_request_context)
    ):
        if not get_config().worker_enabled:
            raise HTTPException(
                status_code=503,
                detail="Async reflect requires the background worker to be enabled.",
            )

        try:
            query = compose_reflect_query(request.query, request.context)
            result = await app.state.memory.submit_async_reflect(
                bank_id=bank_id,
                query=query,
                budget=request.budget,
                max_tokens=request.max_tokens,
                include_facts=request.include.facts is not None,
                include_tool_calls=request.include.tool_calls is not None,
                include_tool_call_output=request.include.tool_calls.output
                if request.include.tool_calls is not None
                else True,
                response_schema=request.response_schema,
                tags=request.tags,
                tags_match=request.tags_match,
                request_context=request_context,
            )
            return AsyncOperationSubmitResponse(operation_id=result["operation_id"], status="queued")
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/reflect/submit: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks",
        response_model=BankListResponse,
        summary="List all memory banks",
        description="Get a list of all agents with their profiles",
        operation_id="list_banks",
        tags=["Banks"],
    )
    async def api_list_banks(request_context: RequestContext = Depends(get_request_context)):
        """Get list of all banks with their profiles."""
        try:
            banks = await app.state.memory.list_banks(request_context=request_context)
            return BankListResponse(banks=banks)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/stats",
        response_model=BankStatsResponse,
        summary="Get statistics for memory bank",
        description="Get statistics about nodes and links for a specific agent",
        operation_id="get_agent_stats",
        tags=["Banks"],
    )
    async def api_stats(
        bank_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Get statistics about memory nodes and links for a memory bank."""
        try:
            stats = await app.state.memory.get_bank_stats(bank_id, request_context=request_context)
            nodes_by_type = stats["node_counts"]
            links_by_type = stats["link_counts"]
            links_by_fact_type = stats["link_counts_by_fact_type"]
            links_breakdown: dict[str, dict[str, int]] = {}
            for row in stats["link_breakdown"]:
                ft = row["fact_type"]
                if ft not in links_breakdown:
                    links_breakdown[ft] = {}
                links_breakdown[ft][row["link_type"]] = row["count"]
            ops = stats["operations"]
            return BankStatsResponse(
                bank_id=bank_id,
                total_nodes=sum(nodes_by_type.values()),
                total_links=sum(links_by_type.values()),
                total_documents=stats["total_documents"],
                nodes_by_fact_type=nodes_by_type,
                links_by_link_type=links_by_type,
                links_by_fact_type=links_by_fact_type,
                links_breakdown=links_breakdown,
                pending_operations=ops.get("pending", 0),
                failed_operations=ops.get("failed", 0),
                last_consolidated_at=stats["last_consolidated_at"],
                pending_consolidation=stats["pending_consolidation"],
                total_observations=stats["total_observations"],
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/stats: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/entities",
        response_model=EntityListResponse,
        summary="List entities",
        description="List all entities (people, organizations, etc.) known by the bank, ordered by mention count. Supports pagination.",
        operation_id="list_entities",
        tags=["Entities"],
    )
    async def api_list_entities(
        bank_id: str,
        limit: int = Query(default=100, description="Maximum number of entities to return"),
        offset: int = Query(default=0, description="Offset for pagination"),
        request_context: RequestContext = Depends(get_request_context),
    ):
        """List entities for a memory bank with pagination."""
        try:
            data = await app.state.memory.list_entities(
                bank_id, limit=limit, offset=offset, request_context=request_context
            )
            return EntityListResponse(
                items=[EntityListItem(**e) for e in data["items"]],
                total=data["total"],
                limit=data["limit"],
                offset=data["offset"],
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/entities: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/entities/{entity_id}",
        response_model=EntityDetailResponse,
        summary="Get entity details",
        description="Get detailed information about an entity including observations (mental model).",
        operation_id="get_entity",
        tags=["Entities"],
    )
    async def api_get_entity(
        bank_id: str, entity_id: str, request_context: RequestContext = Depends(get_request_context)
    ):
        """Get entity details with observations."""
        try:
            entity = await app.state.memory.get_entity(bank_id, entity_id, request_context=request_context)

            if entity is None:
                raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")

            return EntityDetailResponse(
                id=entity["id"],
                canonical_name=entity["canonical_name"],
                mention_count=entity["mention_count"],
                first_seen=entity["first_seen"],
                last_seen=entity["last_seen"],
                metadata=_parse_metadata(entity["metadata"]),
                observations=[
                    EntityObservationResponse(text=obs.text, mentioned_at=obs.mentioned_at)
                    for obs in entity["observations"]
                ],
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/entities/{entity_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/entities/{entity_id}/regenerate",
        response_model=EntityDetailResponse,
        summary="Regenerate entity observations (deprecated)",
        description="This endpoint is deprecated. Entity observations have been replaced by mental models.",
        operation_id="regenerate_entity_observations",
        tags=["Entities"],
        deprecated=True,
    )
    async def api_regenerate_entity_observations(
        bank_id: str,
        entity_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Regenerate observations for an entity. DEPRECATED."""
        raise HTTPException(
            status_code=410,
            detail="This endpoint is deprecated. Entity observations are no longer supported.",
        )

    # =========================================================================
    # =========================================================================
    # MENTAL MODELS ENDPOINTS (stored reflect responses)
    # =========================================================================

    @app.get(
        "/v1/default/banks/{bank_id}/mental-models",
        response_model=MentalModelListResponse,
        summary="List mental models",
        description="List user-curated living documents that stay current.",
        operation_id="list_mental_models",
        tags=["Mental Models"],
    )
    async def api_list_mental_models(
        bank_id: str,
        tags_filter: list[str] | None = Query(None, alias="tags", description="Filter by tags"),
        tags_match: Literal["any", "all", "exact"] = Query("any", description="How to match tags"),
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        request_context: RequestContext = Depends(get_request_context),
    ):
        """List mental models for a bank."""
        try:
            mental_models = await app.state.memory.list_mental_models(
                bank_id=bank_id,
                tags=tags_filter,
                tags_match=tags_match,
                limit=limit,
                offset=offset,
                request_context=request_context,
            )
            return MentalModelListResponse(items=[MentalModelResponse(**m) for m in mental_models])
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in GET /v1/default/banks/{bank_id}/mental-models: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/mental-models/{mental_model_id}",
        response_model=MentalModelResponse,
        summary="Get mental model",
        description="Get a specific mental model by ID.",
        operation_id="get_mental_model",
        tags=["Mental Models"],
    )
    async def api_get_mental_model(
        bank_id: str,
        mental_model_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Get a mental model by ID."""
        try:
            mental_model = await app.state.memory.get_mental_model(
                bank_id=bank_id,
                mental_model_id=mental_model_id,
                request_context=request_context,
            )
            if mental_model is None:
                raise HTTPException(status_code=404, detail=f"Mental model '{mental_model_id}' not found")

            return MentalModelResponse(**mental_model)
        except (AuthenticationError, HTTPException):
            raise
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in GET /v1/default/banks/{bank_id}/mental-models/{mental_model_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/mental-models/{mental_model_id}/history",
        summary="Get mental model history",
        description="Get the refresh history of a mental model, showing content changes over time.",
        operation_id="get_mental_model_history",
        tags=["Mental Models"],
    )
    async def api_get_mental_model_history(
        bank_id: str,
        mental_model_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Get the refresh history of a mental model."""
        try:
            data = await app.state.memory.get_mental_model_history(
                bank_id=bank_id,
                mental_model_id=mental_model_id,
                request_context=request_context,
            )
            if data is None:
                raise HTTPException(status_code=404, detail=f"Mental model '{mental_model_id}' not found")
            return data
        except (AuthenticationError, HTTPException):
            raise
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(
                f"Error in GET /v1/default/banks/{bank_id}/mental-models/{mental_model_id}/history: {error_detail}"
            )
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/mental-models",
        response_model=CreateMentalModelResponse,
        summary="Create mental model",
        description="Create a mental model by running reflect with the source query in the background. "
        "Returns an operation ID to track progress. The content is auto-generated by the reflect endpoint. "
        "Use the operations endpoint to check completion status.",
        operation_id="create_mental_model",
        tags=["Mental Models"],
    )
    async def api_create_mental_model(
        bank_id: str,
        body: CreateMentalModelRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Create a mental model (async - returns operation_id)."""
        try:
            # 1. Create the mental model with placeholder content
            mental_model = await app.state.memory.create_mental_model(
                bank_id=bank_id,
                name=body.name,
                source_query=body.source_query,
                content="Generating content...",
                mental_model_id=body.id if body.id else None,
                tags=body.tags if body.tags else None,
                max_tokens=body.max_tokens,
                trigger=body.trigger.model_dump() if body.trigger else None,
                request_context=request_context,
            )
            # 2. Schedule a refresh to generate the actual content
            result = await app.state.memory.submit_async_refresh_mental_model(
                bank_id=bank_id,
                mental_model_id=mental_model["id"],
                request_context=request_context,
            )
            return CreateMentalModelResponse(mental_model_id=mental_model["id"], operation_id=result["operation_id"])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except (AuthenticationError, HTTPException):
            raise
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in POST /v1/default/banks/{bank_id}/mental-models: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/mental-models/{mental_model_id}/refresh",
        response_model=AsyncOperationSubmitResponse,
        summary="Refresh mental model",
        description="Submit an async task to re-run the source query through reflect and update the content.",
        operation_id="refresh_mental_model",
        tags=["Mental Models"],
    )
    async def api_refresh_mental_model(
        bank_id: str,
        mental_model_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Refresh a mental model by re-running its source query (async)."""
        try:
            result = await app.state.memory.submit_async_refresh_mental_model(
                bank_id=bank_id,
                mental_model_id=mental_model_id,
                request_context=request_context,
            )
            return AsyncOperationSubmitResponse(operation_id=result["operation_id"], status="queued")
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except (AuthenticationError, HTTPException):
            raise
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(
                f"Error in POST /v1/default/banks/{bank_id}/mental-models/{mental_model_id}/refresh: {error_detail}"
            )
            raise HTTPException(status_code=500, detail=str(e))

    @app.patch(
        "/v1/default/banks/{bank_id}/mental-models/{mental_model_id}",
        response_model=MentalModelResponse,
        summary="Update mental model",
        description="Update a mental model's name and/or source query.",
        operation_id="update_mental_model",
        tags=["Mental Models"],
    )
    async def api_update_mental_model(
        bank_id: str,
        mental_model_id: str,
        body: UpdateMentalModelRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Update a mental model."""
        try:
            mental_model = await app.state.memory.update_mental_model(
                bank_id=bank_id,
                mental_model_id=mental_model_id,
                name=body.name,
                source_query=body.source_query,
                max_tokens=body.max_tokens,
                tags=body.tags,
                trigger=body.trigger.model_dump() if body.trigger else None,
                request_context=request_context,
            )
            if mental_model is None:
                raise HTTPException(status_code=404, detail=f"Mental model '{mental_model_id}' not found")
            return MentalModelResponse(**mental_model)
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in PATCH /v1/default/banks/{bank_id}/mental-models/{mental_model_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete(
        "/v1/default/banks/{bank_id}/mental-models/{mental_model_id}",
        summary="Delete mental model",
        description="Delete a mental model.",
        operation_id="delete_mental_model",
        tags=["Mental Models"],
    )
    async def api_delete_mental_model(
        bank_id: str,
        mental_model_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Delete a mental model."""
        try:
            deleted = await app.state.memory.delete_mental_model(
                bank_id=bank_id,
                mental_model_id=mental_model_id,
                request_context=request_context,
            )
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Mental model '{mental_model_id}' not found")
            return {"status": "deleted"}
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in DELETE /v1/default/banks/{bank_id}/mental-models/{mental_model_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    # =========================================================================
    # DIRECTIVES ENDPOINTS
    # =========================================================================

    @app.get(
        "/v1/default/banks/{bank_id}/directives",
        response_model=DirectiveListResponse,
        summary="List directives",
        description="List hard rules that are injected into prompts.",
        operation_id="list_directives",
        tags=["Directives"],
    )
    async def api_list_directives(
        bank_id: str,
        tags_filter: list[str] | None = Query(None, alias="tags", description="Filter by tags"),
        tags_match: Literal["any", "all", "exact"] = Query("any", description="How to match tags"),
        active_only: bool = Query(True, description="Only return active directives"),
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        request_context: RequestContext = Depends(get_request_context),
    ):
        """List directives for a bank."""
        try:
            directives = await app.state.memory.list_directives(
                bank_id=bank_id,
                tags=tags_filter,
                tags_match=tags_match,
                active_only=active_only,
                limit=limit,
                offset=offset,
                request_context=request_context,
            )
            return DirectiveListResponse(items=[DirectiveResponse(**d) for d in directives])
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in GET /v1/default/banks/{bank_id}/directives: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/directives/{directive_id}",
        response_model=DirectiveResponse,
        summary="Get directive",
        description="Get a specific directive by ID.",
        operation_id="get_directive",
        tags=["Directives"],
    )
    async def api_get_directive(
        bank_id: str,
        directive_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Get a directive by ID."""
        try:
            directive = await app.state.memory.get_directive(
                bank_id=bank_id,
                directive_id=directive_id,
                request_context=request_context,
            )
            if directive is None:
                raise HTTPException(status_code=404, detail=f"Directive '{directive_id}' not found")
            return DirectiveResponse(**directive)
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in GET /v1/default/banks/{bank_id}/directives/{directive_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/directives",
        response_model=DirectiveResponse,
        summary="Create directive",
        description="Create a hard rule that will be injected into prompts.",
        operation_id="create_directive",
        tags=["Directives"],
    )
    async def api_create_directive(
        bank_id: str,
        body: CreateDirectiveRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Create a directive."""
        try:
            directive = await app.state.memory.create_directive(
                bank_id=bank_id,
                name=body.name,
                content=body.content,
                priority=body.priority,
                is_active=body.is_active,
                tags=body.tags,
                request_context=request_context,
            )
            return DirectiveResponse(**directive)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in POST /v1/default/banks/{bank_id}/directives: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.patch(
        "/v1/default/banks/{bank_id}/directives/{directive_id}",
        response_model=DirectiveResponse,
        summary="Update directive",
        description="Update a directive's properties.",
        operation_id="update_directive",
        tags=["Directives"],
    )
    async def api_update_directive(
        bank_id: str,
        directive_id: str,
        body: UpdateDirectiveRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Update a directive."""
        try:
            directive = await app.state.memory.update_directive(
                bank_id=bank_id,
                directive_id=directive_id,
                name=body.name,
                content=body.content,
                priority=body.priority,
                is_active=body.is_active,
                tags=body.tags,
                request_context=request_context,
            )
            if directive is None:
                raise HTTPException(status_code=404, detail=f"Directive '{directive_id}' not found")
            return DirectiveResponse(**directive)
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in PATCH /v1/default/banks/{bank_id}/directives/{directive_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete(
        "/v1/default/banks/{bank_id}/directives/{directive_id}",
        summary="Delete directive",
        description="Delete a directive.",
        operation_id="delete_directive",
        tags=["Directives"],
    )
    async def api_delete_directive(
        bank_id: str,
        directive_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Delete a directive."""
        try:
            deleted = await app.state.memory.delete_directive(
                bank_id=bank_id,
                directive_id=directive_id,
                request_context=request_context,
            )
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Directive '{directive_id}' not found")
            return {"status": "deleted"}
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in DELETE /v1/default/banks/{bank_id}/directives/{directive_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/documents",
        response_model=ListDocumentsResponse,
        summary="List documents",
        description="List documents with pagination and optional search. Documents are the source content from which memory units are extracted.",
        operation_id="list_documents",
        tags=["Documents"],
    )
    async def api_list_documents(
        bank_id: str,
        q: str | None = Query(
            None, description="Case-insensitive substring filter on document ID (e.g. 'report' matches 'report-2024')"
        ),
        tags: list[str] | None = Query(None, description="Filter documents by tags"),
        tags_match: str = Query(
            "any_strict", description="How to match tags: 'any', 'all', 'any_strict', 'all_strict'"
        ),
        limit: int = 100,
        offset: int = 0,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """
        List documents for a memory bank with optional search.

        Args:
            bank_id: Memory Bank ID (from path)
            q: Case-insensitive substring filter on document ID
            tags: Filter documents by tags
            tags_match: How to match tags (any, all, any_strict, all_strict)
            limit: Maximum number of results (default: 100)
            offset: Offset for pagination (default: 0)
        """
        try:
            data = await app.state.memory.list_documents(
                bank_id=bank_id,
                search_query=q,
                tags=tags,
                tags_match=tags_match,
                limit=limit,
                offset=offset,
                request_context=request_context,
            )
            return data
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/documents: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/documents/{document_id:path}",
        response_model=DocumentResponse,
        summary="Get document details",
        description="Get a specific document including its original text",
        operation_id="get_document",
        tags=["Documents"],
    )
    async def api_get_document(
        bank_id: str, document_id: str, request_context: RequestContext = Depends(get_request_context)
    ):
        """
        Get a specific document with its original text.

        Args:
            bank_id: Memory Bank ID (from path)
            document_id: Document ID (from path)
        """
        try:
            document = await app.state.memory.get_document(document_id, bank_id, request_context=request_context)
            if not document:
                raise HTTPException(status_code=404, detail="Document not found")
            return document
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/documents/{document_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/tags",
        response_model=ListTagsResponse,
        summary="List tags",
        description="List all unique tags in a memory bank with usage counts. "
        "Supports wildcard search using '*' (e.g., 'user:*', '*-fred', 'tag*-2'). Case-insensitive.",
        operation_id="list_tags",
        tags=["Memory"],
    )
    async def api_list_tags(
        bank_id: str,
        q: str | None = Query(
            default=None,
            description="Wildcard pattern to filter tags (e.g., 'user:*' for user:alice, '*-admin' for role-admin). "
            "Use '*' as wildcard. Case-insensitive.",
        ),
        limit: int = Query(default=100, description="Maximum number of tags to return"),
        offset: int = Query(default=0, description="Offset for pagination"),
        request_context: RequestContext = Depends(get_request_context),
    ):
        """
        List all unique tags in a memory bank.

        Use this endpoint to discover available tags or expand wildcard patterns.
        Supports '*' wildcards for flexible matching (case-insensitive):
        - 'user:*' matches user:alice, user:bob
        - '*-admin' matches role-admin, super-admin
        - 'env*-prod' matches env-prod, environment-prod

        Args:
            bank_id: Memory Bank ID (from path)
            q: Wildcard pattern to filter tags (use '*' as wildcard)
            limit: Maximum number of tags to return (default: 100)
            offset: Offset for pagination (default: 0)
        """
        try:
            data = await app.state.memory.list_tags(
                bank_id=bank_id,
                pattern=q,
                limit=limit,
                offset=offset,
                request_context=request_context,
            )
            return data
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/tags: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/chunks/{chunk_id:path}",
        response_model=ChunkResponse,
        summary="Get chunk details",
        description="Get a specific chunk by its ID",
        operation_id="get_chunk",
        tags=["Documents"],
    )
    async def api_get_chunk(chunk_id: str, request_context: RequestContext = Depends(get_request_context)):
        """
        Get a specific chunk with its text.

        Args:
            chunk_id: Chunk ID (from path, format: bank_id_document_id_chunk_index)
        """
        try:
            chunk = await app.state.memory.get_chunk(chunk_id, request_context=request_context)
            if not chunk:
                raise HTTPException(status_code=404, detail="Chunk not found")
            return chunk
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/chunks/{chunk_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete(
        "/v1/default/banks/{bank_id}/documents/{document_id:path}",
        response_model=DeleteDocumentResponse,
        summary="Delete a document",
        description="Delete a document and all its associated memory units and links.\n\n"
        "This will cascade delete:\n"
        "- The document itself\n"
        "- All memory units extracted from this document\n"
        "- All links (temporal, semantic, entity) associated with those memory units\n\n"
        "This operation cannot be undone.",
        operation_id="delete_document",
        tags=["Documents"],
    )
    async def api_delete_document(
        bank_id: str, document_id: str, request_context: RequestContext = Depends(get_request_context)
    ):
        """
        Delete a document and all its associated memory units and links.

        Args:
            bank_id: Memory Bank ID (from path)
            document_id: Document ID to delete (from path)
        """
        try:
            result = await app.state.memory.delete_document(document_id, bank_id, request_context=request_context)

            if result["document_deleted"] == 0:
                raise HTTPException(status_code=404, detail="Document not found")

            return DeleteDocumentResponse(
                success=True,
                message=f"Document '{document_id}' and {result['memory_units_deleted']} associated memory units deleted successfully",
                document_id=document_id,
                memory_units_deleted=result["memory_units_deleted"],
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/documents/{document_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/operations",
        response_model=OperationsListResponse,
        summary="List async operations",
        description="Get a list of async operations for a specific agent, with optional filtering by status and operation type. Results are sorted by most recent first.",
        operation_id="list_operations",
        tags=["Operations"],
    )
    async def api_list_operations(
        bank_id: str,
        status: str | None = Query(default=None, description="Filter by status: pending, completed, or failed"),
        operation_type: str | None = Query(
            default=None,
            alias="type",
            description="Filter by operation type: retain, reflect, consolidation, refresh_mental_model, file_convert_retain, codebase_import, codebase_refresh, codebase_approve, webhook_delivery",
        ),
        limit: int = Query(default=20, ge=1, le=100, description="Maximum number of operations to return"),
        offset: int = Query(default=0, ge=0, description="Number of operations to skip"),
        request_context: RequestContext = Depends(get_request_context),
    ):
        """List async operations for a memory bank with optional filtering and pagination."""
        try:
            result = await app.state.memory.list_operations(
                bank_id,
                status=status,
                task_type=operation_type,
                limit=limit,
                offset=offset,
                request_context=request_context,
            )
            return OperationsListResponse(
                bank_id=bank_id,
                total=result["total"],
                limit=limit,
                offset=offset,
                operations=[OperationResponse(**op) for op in result["operations"]],
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/operations: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/operations/{operation_id}",
        response_model=OperationStatusResponse,
        summary="Get operation status",
        description="Get the status of a specific async operation. Returns 'pending', 'completed', or 'failed'. "
        "Completed operations are removed from storage, so 'completed' means the operation finished successfully.",
        operation_id="get_operation_status",
        tags=["Operations"],
    )
    async def api_get_operation_status(
        bank_id: str, operation_id: str, request_context: RequestContext = Depends(get_request_context)
    ):
        """Get the status of an async operation."""
        try:
            # Validate UUID format
            try:
                uuid.UUID(operation_id)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid operation_id format: {operation_id}")

            result = await app.state.memory.get_operation_status(bank_id, operation_id, request_context=request_context)
            return OperationStatusResponse(**result)
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in GET /v1/default/banks/{bank_id}/operations/{operation_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/operations/{operation_id}/result",
        response_model=OperationResultResponse,
        summary="Get operation result",
        description="Get the final user-facing result payload for an async operation.",
        operation_id="get_operation_result",
        tags=["Operations"],
    )
    async def api_get_operation_result(
        bank_id: str, operation_id: str, request_context: RequestContext = Depends(get_request_context)
    ):
        """Get the final result payload for an async operation."""
        try:
            try:
                uuid.UUID(operation_id)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid operation_id format: {operation_id}")

            result = await app.state.memory.get_operation_result(bank_id, operation_id, request_context=request_context)
            return OperationResultResponse(**result)
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in GET /v1/default/banks/{bank_id}/operations/{operation_id}/result: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete(
        "/v1/default/banks/{bank_id}/operations/{operation_id}",
        response_model=CancelOperationResponse,
        summary="Cancel a pending async operation",
        description="Cancel a pending async operation by removing it from the queue",
        operation_id="cancel_operation",
        tags=["Operations"],
    )
    async def api_cancel_operation(
        bank_id: str, operation_id: str, request_context: RequestContext = Depends(get_request_context)
    ):
        """Cancel a pending async operation."""
        try:
            # Validate UUID format
            try:
                uuid.UUID(operation_id)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid operation_id format: {operation_id}")

            result = await app.state.memory.cancel_operation(bank_id, operation_id, request_context=request_context)
            return CancelOperationResponse(**result)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/operations/{operation_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/profile",
        response_model=BankProfileResponse,
        summary="Get memory bank profile",
        description="Get disposition traits and mission for a memory bank. Auto-creates agent with defaults if not exists.",
        operation_id="get_bank_profile",
        tags=["Banks"],
        deprecated=True,
    )
    async def api_get_bank_profile(bank_id: str, request_context: RequestContext = Depends(get_request_context)):
        """Get memory bank profile (disposition + mission)."""
        try:
            profile = await app.state.memory.get_bank_profile(bank_id, request_context=request_context)
            # Convert DispositionTraits object to dict for Pydantic
            disposition_dict = (
                profile["disposition"].model_dump()
                if hasattr(profile["disposition"], "model_dump")
                else dict(profile["disposition"])
            )
            mission = profile.get("mission") or ""
            return BankProfileResponse(
                bank_id=bank_id,
                name=profile["name"],
                disposition=DispositionTraits(**disposition_dict),
                mission=mission,
                background=mission,  # Backwards compat
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/profile: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.put(
        "/v1/default/banks/{bank_id}/profile",
        response_model=BankProfileResponse,
        summary="Update memory bank disposition",
        description="Update bank's disposition traits (skepticism, literalism, empathy)",
        operation_id="update_bank_disposition",
        tags=["Banks"],
        deprecated=True,
    )
    async def api_update_bank_disposition(
        bank_id: str, request: UpdateDispositionRequest, request_context: RequestContext = Depends(get_request_context)
    ):
        """Update bank disposition traits."""
        try:
            # Update disposition
            await app.state.memory.update_bank_disposition(
                bank_id, request.disposition.model_dump(), request_context=request_context
            )

            # Get updated profile
            profile = await app.state.memory.get_bank_profile(bank_id, request_context=request_context)
            disposition_dict = (
                profile["disposition"].model_dump()
                if hasattr(profile["disposition"], "model_dump")
                else dict(profile["disposition"])
            )
            mission = profile.get("mission") or ""
            return BankProfileResponse(
                bank_id=bank_id,
                name=profile["name"],
                disposition=DispositionTraits(**disposition_dict),
                mission=mission,
                background=mission,  # Backwards compat
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/profile: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/background",
        response_model=BackgroundResponse,
        summary="Add/merge memory bank background (deprecated)",
        description="Deprecated: Use PUT /mission instead. This endpoint now updates the mission field.",
        operation_id="add_bank_background",
        tags=["Banks"],
        deprecated=True,
    )
    async def api_add_bank_background(
        bank_id: str, request: AddBackgroundRequest, request_context: RequestContext = Depends(get_request_context)
    ):
        """Deprecated: Add or merge bank background. Now updates mission field."""
        try:
            result = await app.state.memory.merge_bank_mission(
                bank_id, request.content, request_context=request_context
            )
            mission = result.get("mission") or ""
            return BackgroundResponse(mission=mission, background=mission)
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/background: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.put(
        "/v1/default/banks/{bank_id}",
        response_model=BankProfileResponse,
        summary="Create or update memory bank",
        description="Create a new agent or update existing agent with disposition and mission. Auto-fills missing fields with defaults.",
        operation_id="create_or_update_bank",
        tags=["Banks"],
    )
    async def api_create_or_update_bank(
        bank_id: str, request: CreateBankRequest, request_context: RequestContext = Depends(get_request_context)
    ):
        """Create or update an agent with disposition and mission."""
        try:
            # Ensure bank exists by getting profile (auto-creates with defaults)
            await app.state.memory.get_bank_profile(bank_id, request_context=request_context)

            # Update name if provided (stored in DB for display only, deprecated)
            if request.name is not None:
                await app.state.memory.update_bank(
                    bank_id,
                    name=request.name,
                    request_context=request_context,
                )

            # Apply all config overrides (includes reflect_mission, disposition, retain settings)
            config_updates = request.get_config_updates()
            if config_updates:
                await app.state.memory._config_resolver.update_bank_config(bank_id, config_updates, request_context)

            if (request.bank_preset or "").strip().lower() == "codebase":
                try:
                    await app.state.memory.seed_bank_preset_playbooks(
                        bank_id, preset="codebase", request_context=request_context
                    )
                except Exception as exc:
                    logger.warning(
                        "bank_preset codebase seed failed for bank_id=%s: %s",
                        bank_id,
                        exc,
                    )

            # Get final profile
            final_profile = await app.state.memory.get_bank_profile(bank_id, request_context=request_context)
            disposition_dict = (
                final_profile["disposition"].model_dump()
                if hasattr(final_profile["disposition"], "model_dump")
                else dict(final_profile["disposition"])
            )
            mission = final_profile.get("mission") or ""
            return BankProfileResponse(
                bank_id=bank_id,
                name=final_profile["name"],
                disposition=DispositionTraits(**disposition_dict),
                mission=mission,
                background=mission,  # Backwards compat
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.patch(
        "/v1/default/banks/{bank_id}",
        response_model=BankProfileResponse,
        summary="Partial update memory bank",
        description="Partially update an agent's profile. Only provided fields will be updated.",
        operation_id="update_bank",
        tags=["Banks"],
    )
    async def api_update_bank(
        bank_id: str, request: CreateBankRequest, request_context: RequestContext = Depends(get_request_context)
    ):
        """Partially update an agent's profile (name, mission, disposition)."""
        try:
            # Ensure bank exists
            await app.state.memory.get_bank_profile(bank_id, request_context=request_context)

            # Update name if provided (stored in DB for display only, deprecated)
            if request.name is not None:
                await app.state.memory.update_bank(
                    bank_id,
                    name=request.name,
                    request_context=request_context,
                )

            # Apply all config overrides (includes reflect_mission, disposition, retain settings)
            config_updates = request.get_config_updates()
            if config_updates:
                await app.state.memory._config_resolver.update_bank_config(bank_id, config_updates, request_context)

            if (request.bank_preset or "").strip().lower() == "codebase":
                try:
                    await app.state.memory.seed_bank_preset_playbooks(
                        bank_id, preset="codebase", request_context=request_context
                    )
                except Exception as exc:
                    logger.warning(
                        "bank_preset codebase seed failed for bank_id=%s: %s",
                        bank_id,
                        exc,
                    )

            # Get final profile
            final_profile = await app.state.memory.get_bank_profile(bank_id, request_context=request_context)
            disposition_dict = (
                final_profile["disposition"].model_dump()
                if hasattr(final_profile["disposition"], "model_dump")
                else dict(final_profile["disposition"])
            )
            mission = final_profile.get("mission") or ""
            return BankProfileResponse(
                bank_id=bank_id,
                name=final_profile["name"],
                disposition=DispositionTraits(**disposition_dict),
                mission=mission,
                background=mission,  # Backwards compat
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in PATCH /v1/default/banks/{bank_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete(
        "/v1/default/banks/{bank_id}",
        response_model=DeleteResponse,
        summary="Delete memory bank",
        description="Delete an entire memory bank including all memories, entities, documents, and the bank profile itself. "
        "This is a destructive operation that cannot be undone.",
        operation_id="delete_bank",
        tags=["Banks"],
    )
    async def api_delete_bank(bank_id: str, request_context: RequestContext = Depends(get_request_context)):
        """Delete an entire memory bank and all its data."""
        try:
            result = await app.state.memory.delete_bank(bank_id, request_context=request_context)
            return DeleteResponse(
                success=True,
                message=f"Bank '{bank_id}' and all associated data deleted successfully",
                deleted_count=result.get("memory_units_deleted", 0)
                + result.get("entities_deleted", 0)
                + result.get("documents_deleted", 0),
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in DELETE /v1/default/banks/{bank_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete(
        "/v1/default/banks/{bank_id}/observations",
        response_model=DeleteResponse,
        summary="Clear all observations",
        description="Delete all observations for a memory bank. This is useful for resetting the consolidated knowledge.",
        operation_id="clear_observations",
        tags=["Banks"],
    )
    async def api_clear_observations(bank_id: str, request_context: RequestContext = Depends(get_request_context)):
        """Clear all observations for a bank."""
        try:
            result = await app.state.memory.clear_observations(bank_id, request_context=request_context)
            return DeleteResponse(
                success=True,
                message=f"Cleared {result.get('deleted_count', 0)} observations",
                deleted_count=result.get("deleted_count", 0),
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in DELETE /v1/default/banks/{bank_id}/observations: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete(
        "/v1/default/banks/{bank_id}/memories/{memory_id}/observations",
        response_model=ClearMemoryObservationsResponse,
        summary="Clear observations for a memory",
        description="Delete all observations derived from a specific memory and reset it for re-consolidation. "
        "The memory itself is not deleted. A consolidation job is triggered automatically so the memory "
        "will produce fresh observations on the next consolidation run.",
        operation_id="clear_memory_observations",
        tags=["Memory"],
    )
    async def api_clear_memory_observations(
        bank_id: str,
        memory_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Clear all observations derived from a specific memory."""
        try:
            result = await app.state.memory.clear_observations_for_memory(
                bank_id=bank_id,
                memory_id=memory_id,
                request_context=request_context,
            )
            return ClearMemoryObservationsResponse(deleted_count=result["deleted_count"])
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(
                f"Error in DELETE /v1/default/banks/{bank_id}/memories/{memory_id}/observations: {error_detail}"
            )
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/config",
        response_model=BankConfigResponse,
        summary="Get bank configuration",
        description="Get fully resolved configuration for a bank including all hierarchical overrides (global → tenant → bank). "
        "The 'config' field contains all resolved config values. The 'overrides' field shows only bank-specific overrides.",
        operation_id="get_bank_config",
        tags=["Banks"],
    )
    async def api_get_bank_config(bank_id: str, request_context: RequestContext = Depends(get_request_context)):
        """Get configuration for a bank with all hierarchical overrides applied."""
        if not get_config().enable_bank_config_api:
            raise HTTPException(
                status_code=404,
                detail="Bank configuration API is disabled. Set ATULYA_API_ENABLE_BANK_CONFIG_API=true to re-enable.",
            )
        try:
            # Authenticate and set schema context for multi-tenant DB queries
            await app.state.memory._authenticate_tenant(request_context)
            if app.state.memory._operation_validator:
                from atulya_api.extensions import BankReadContext

                ctx = BankReadContext(bank_id=bank_id, operation="get_bank_config", request_context=request_context)
                await app.state.memory._validate_operation(
                    app.state.memory._operation_validator.validate_bank_read(ctx)
                )

            # Get resolved config from config resolver
            config_dict = await app.state.memory._config_resolver.get_bank_config(bank_id, request_context)

            # Get bank-specific overrides only
            bank_overrides = await app.state.memory._config_resolver._load_bank_config(bank_id)

            return BankConfigResponse(bank_id=bank_id, config=config_dict, overrides=bank_overrides)
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in GET /v1/default/banks/{bank_id}/config: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.patch(
        "/v1/default/banks/{bank_id}/config",
        response_model=BankConfigResponse,
        summary="Update bank configuration",
        description="Update configuration overrides for a bank. Only hierarchical fields can be overridden (LLM settings, retention parameters, etc.). "
        "Keys can be provided in Python field format (llm_provider) or environment variable format (ATULYA_API_LLM_PROVIDER).",
        operation_id="update_bank_config",
        tags=["Banks"],
    )
    async def api_update_bank_config(
        bank_id: str, request: BankConfigUpdate, request_context: RequestContext = Depends(get_request_context)
    ):
        """Update configuration overrides for a bank."""
        if not get_config().enable_bank_config_api:
            raise HTTPException(
                status_code=404,
                detail="Bank configuration API is disabled. Set ATULYA_API_ENABLE_BANK_CONFIG_API=true to re-enable.",
            )
        try:
            # Authenticate and set schema context for multi-tenant DB queries
            await app.state.memory._authenticate_tenant(request_context)
            if app.state.memory._operation_validator:
                from atulya_api.extensions import BankWriteContext

                ctx = BankWriteContext(bank_id=bank_id, operation="update_bank_config", request_context=request_context)
                await app.state.memory._validate_operation(
                    app.state.memory._operation_validator.validate_bank_write(ctx)
                )

            # Update config via config resolver (validates configurable fields and permissions)
            await app.state.memory._config_resolver.update_bank_config(bank_id, request.updates, request_context)

            # Return updated config
            config_dict = await app.state.memory._config_resolver.get_bank_config(bank_id, request_context)
            bank_overrides = await app.state.memory._config_resolver._load_bank_config(bank_id)

            return BankConfigResponse(bank_id=bank_id, config=config_dict, overrides=bank_overrides)
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except ValueError as e:
            # Validation error (e.g., trying to override static field)
            raise HTTPException(status_code=400, detail=str(e))
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in PATCH /v1/default/banks/{bank_id}/config: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete(
        "/v1/default/banks/{bank_id}/config",
        response_model=BankConfigResponse,
        summary="Reset bank configuration",
        description="Reset bank configuration to defaults by removing all bank-specific overrides. "
        "The bank will then use global and tenant-level configuration only.",
        operation_id="reset_bank_config",
        tags=["Banks"],
    )
    async def api_reset_bank_config(bank_id: str, request_context: RequestContext = Depends(get_request_context)):
        """Reset bank configuration to defaults (remove all overrides)."""
        if not get_config().enable_bank_config_api:
            raise HTTPException(
                status_code=404,
                detail="Bank configuration API is disabled. Set ATULYA_API_ENABLE_BANK_CONFIG_API=true to re-enable.",
            )
        try:
            # Authenticate and set schema context for multi-tenant DB queries
            await app.state.memory._authenticate_tenant(request_context)
            if app.state.memory._operation_validator:
                from atulya_api.extensions import BankWriteContext

                ctx = BankWriteContext(bank_id=bank_id, operation="reset_bank_config", request_context=request_context)
                await app.state.memory._validate_operation(
                    app.state.memory._operation_validator.validate_bank_write(ctx)
                )

            # Reset config via config resolver
            await app.state.memory._config_resolver.reset_bank_config(bank_id)

            # Return updated config (should match defaults now)
            config_dict = await app.state.memory._config_resolver.get_bank_config(bank_id, request_context)
            bank_overrides = await app.state.memory._config_resolver._load_bank_config(bank_id)

            return BankConfigResponse(bank_id=bank_id, config=config_dict, overrides=bank_overrides)
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in DELETE /v1/default/banks/{bank_id}/config: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/consolidate",
        response_model=ConsolidationResponse,
        summary="Trigger consolidation",
        description="Run memory consolidation to create/update observations from recent memories.",
        operation_id="trigger_consolidation",
        tags=["Banks"],
    )
    async def api_trigger_consolidation(bank_id: str, request_context: RequestContext = Depends(get_request_context)):
        """Trigger consolidation for a bank (async)."""
        try:
            result = await app.state.memory.submit_async_consolidation(bank_id=bank_id, request_context=request_context)
            return ConsolidationResponse(
                operation_id=result["operation_id"],
                deduplicated=result.get("deduplicated", False),
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in POST /v1/default/banks/{bank_id}/consolidate: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/sub-routine",
        response_model=ConsolidationResponse,
        summary="Trigger sub_routine",
        description="Queue a sub_routine operation for atulya-brain cache refresh and activity-time learning.",
        operation_id="trigger_sub_routine",
        tags=["Banks"],
    )
    async def api_trigger_sub_routine(
        bank_id: str,
        request: SubRoutineSubmitRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Trigger sub_routine for a bank (async)."""
        config = get_config()
        if not config.brain_enabled:
            raise HTTPException(status_code=404, detail="Brain runtime is disabled")
        try:
            result = await app.state.memory.submit_async_sub_routine(
                bank_id=bank_id,
                mode=request.mode,
                horizon_hours=request.horizon_hours,
                force_rebuild=request.force_rebuild,
                request_context=request_context,
            )
            return ConsolidationResponse(
                operation_id=result["operation_id"],
                deduplicated=result.get("deduplicated", False),
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in POST /v1/default/banks/{bank_id}/sub-routine: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/dreams/trigger",
        response_model=ConsolidationResponse,
        summary="Trigger Dream/Trance generation",
        operation_id="trigger_dream_generation",
        tags=["Banks"],
    )
    async def api_trigger_dream_generation(
        bank_id: str,
        request: DreamSubmitRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        try:
            result = await app.state.memory.submit_async_dream_generation(
                bank_id=bank_id,
                request_context=request_context,
                trigger_source=request.trigger_source,
                run_type=request.run_type,
            )
            return ConsolidationResponse(
                operation_id=result["operation_id"],
                deduplicated=result.get("deduplicated", False),
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/dreams",
        response_model=DreamRunListResponse,
        summary="List dream artifacts",
        operation_id="list_dream_artifacts",
        tags=["Banks"],
    )
    async def api_list_dream_artifacts(
        bank_id: str,
        limit: int = Query(20, ge=1, le=100),
        request_context: RequestContext = Depends(get_request_context),
    ):
        try:
            items = await app.state.memory.list_dream_artifacts(
                bank_id=bank_id,
                limit=limit,
                request_context=request_context,
            )
            return DreamRunListResponse(items=[DreamRunResponse(**item) for item in items])
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/dreams/proposals/{proposal_id}/review",
        summary="Review a dream proposal",
        operation_id="review_dream_proposal",
        tags=["Banks"],
    )
    async def api_review_dream_proposal(
        bank_id: str,
        proposal_id: str,
        body: DreamProposalReviewRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        try:
            result = await app.state.memory.review_dream_proposal(
                bank_id=bank_id,
                proposal_id=proposal_id,
                action=body.action,
                note=body.note,
                request_context=request_context,
            )
            return result
        except ValueError as e:
            raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/dreams/predictions/{prediction_id}/outcome",
        summary="Update dream prediction outcome",
        operation_id="update_dream_prediction_outcome",
        tags=["Banks"],
    )
    async def api_update_dream_prediction_outcome(
        bank_id: str,
        prediction_id: str,
        body: DreamPredictionOutcomeRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        try:
            result = await app.state.memory.update_dream_prediction_outcome(
                bank_id=bank_id,
                prediction_id=prediction_id,
                status=body.status,
                note=body.note,
                evidence_ids=body.evidence_ids,
                request_context=request_context,
            )
            return result
        except ValueError as e:
            raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/dreams/stats",
        response_model=DreamStatsResponse,
        summary="Get dream generation stats",
        operation_id="get_dream_stats",
        tags=["Banks"],
    )
    async def api_get_dream_stats(
        bank_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        try:
            data = await app.state.memory.get_dream_stats(
                bank_id=bank_id,
                request_context=request_context,
            )
            return DreamStatsResponse(**data)
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/brain/status",
        response_model=BrainRuntimeStatusResponse,
        summary="Get brain runtime status",
        description="Return current brain cache state for the bank.",
        operation_id="get_brain_runtime_status",
        tags=["Banks"],
    )
    async def api_get_brain_status(
        bank_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Get brain runtime status for a bank."""
        config = get_config()
        if not config.brain_enabled:
            raise HTTPException(status_code=404, detail="Brain runtime is disabled")
        try:
            result = await app.state.memory.get_brain_runtime_status(bank_id=bank_id, request_context=request_context)
            return BrainRuntimeStatusResponse(**result)
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in GET /v1/default/banks/{bank_id}/brain/status: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/sub-routine/predictions",
        response_model=SubRoutinePredictionResponse,
        summary="Get activity-time predictions",
        description="Return model predictions for likely active hours for this bank.",
        operation_id="get_sub_routine_predictions",
        tags=["Banks"],
    )
    async def api_get_sub_routine_predictions(
        bank_id: str,
        horizon_hours: int = Query(24, ge=1, le=168),
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Get sub_routine activity-time predictions for a bank."""
        config = get_config()
        if not config.brain_enabled:
            raise HTTPException(status_code=404, detail="Brain runtime is disabled")
        try:
            result = await app.state.memory.get_sub_routine_predictions(
                bank_id=bank_id,
                horizon_hours=horizon_hours,
                request_context=request_context,
            )
            return SubRoutinePredictionResponse(**result)
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in GET /v1/default/banks/{bank_id}/sub-routine/predictions: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/sub-routine/histogram",
        response_model=SubRoutineHistogramResponse,
        summary="Get full activity histogram",
        description="Return all 24 hourly activity probabilities from the current sub_routine model.",
        operation_id="get_sub_routine_histogram",
        tags=["Banks"],
    )
    async def api_get_sub_routine_histogram(
        bank_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Get full 24-hour sub_routine histogram for a bank."""
        config = get_config()
        if not config.brain_enabled:
            raise HTTPException(status_code=404, detail="Brain runtime is disabled")
        try:
            result = await app.state.memory.get_sub_routine_histogram(
                bank_id=bank_id,
                request_context=request_context,
            )
            return SubRoutineHistogramResponse(**result)
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in GET /v1/default/banks/{bank_id}/sub-routine/histogram: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/brain/influence",
        response_model=BrainInfluenceResponse,
        summary="Get brain influence analytics",
        operation_id="get_brain_influence",
        tags=["Banks"],
    )
    async def api_get_brain_influence(
        bank_id: str,
        window_days: int = Query(14, ge=1, le=90),
        top_k: int = Query(12, ge=5, le=50),
        entity_type: str = Query("all"),
        request_context: RequestContext = Depends(get_request_context),
    ):
        config = get_config()
        if not config.brain_enabled:
            raise HTTPException(status_code=404, detail="Brain runtime is disabled")
        try:
            result = await app.state.memory.get_brain_influence_analytics(
                bank_id=bank_id,
                window_days=window_days,
                top_k=top_k,
                entity_type=entity_type,
                request_context=request_context,
            )
            return BrainInfluenceResponse(**result)
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/brain/export",
        summary="Export current .brain snapshot",
        description="Export validated brain snapshot for this bank.",
        operation_id="export_brain_snapshot",
        tags=["Banks"],
    )
    async def api_export_brain_snapshot(
        bank_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        config = get_config()
        if not (config.brain_enabled and config.brain_import_export_enabled):
            raise HTTPException(status_code=404, detail="Brain import/export is disabled")
        try:
            raw = await app.state.memory.export_brain_snapshot(bank_id=bank_id, request_context=request_context)
            return Response(
                content=raw,
                media_type="application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="{bank_id}.brain"'},
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in GET /v1/default/banks/{bank_id}/brain/export: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/brain/import/validate",
        response_model=BrainImportValidationResponse,
        summary="Validate .brain import payload",
        description="Validate schema/version/checksum compatibility before importing.",
        operation_id="validate_brain_import",
        tags=["Banks"],
    )
    async def api_validate_brain_import(
        bank_id: str,
        file: UploadFile = File(..., description="Brain snapshot payload"),
        request_context: RequestContext = Depends(get_request_context),
    ):
        config = get_config()
        if not (config.brain_enabled and config.brain_import_export_enabled):
            raise HTTPException(status_code=404, detail="Brain import/export is disabled")
        try:
            raw = await file.read()
            result = await app.state.memory.validate_brain_import(
                bank_id=bank_id,
                raw=raw,
                request_context=request_context,
            )
            return BrainImportValidationResponse(**result)
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in POST /v1/default/banks/{bank_id}/brain/import/validate: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/brain/import",
        response_model=BrainImportResponse,
        summary="Import .brain snapshot",
        description="Import a validated brain snapshot into this bank cache path.",
        operation_id="import_brain_snapshot",
        tags=["Banks"],
    )
    async def api_import_brain_snapshot(
        bank_id: str,
        file: UploadFile = File(..., description="Brain snapshot payload"),
        request_context: RequestContext = Depends(get_request_context),
    ):
        config = get_config()
        if not (config.brain_enabled and config.brain_import_export_enabled):
            raise HTTPException(status_code=404, detail="Brain import/export is disabled")
        try:
            raw = await file.read()
            result = await app.state.memory.import_brain_snapshot(
                bank_id=bank_id,
                raw=raw,
                request_context=request_context,
            )
            return BrainImportResponse(**result)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in POST /v1/default/banks/{bank_id}/brain/import: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/brain/learn",
        response_model=BrainLearnResponse,
        summary="Learn from a remote brain",
        description="Connect to another Atulya instance and distill its knowledge into this bank's brain.",
        operation_id="brain_learn_from_remote",
        tags=["Banks"],
    )
    async def api_brain_learn(
        bank_id: str,
        request: BrainLearnRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        config = get_config()
        if not config.brain_enabled:
            raise HTTPException(status_code=404, detail="Brain runtime is disabled")
        try:
            result = await app.state.memory.submit_brain_learn(
                bank_id=bank_id,
                remote_endpoint=request.remote_endpoint,
                remote_bank_id=request.remote_bank_id,
                remote_api_key=request.remote_api_key,
                learning_type=request.learning_type,
                mode=request.mode,
                horizon_hours=request.horizon_hours,
                request_context=request_context,
            )
            return BrainLearnResponse(
                operation_id=result["operation_id"],
                deduplicated=result.get("deduplicated", False),
            )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in POST /v1/default/banks/{bank_id}/brain/learn: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    # =========================================================================
    # Webhook Endpoints
    # =========================================================================

    @app.post(
        "/v1/default/banks/{bank_id}/webhooks",
        response_model=WebhookResponse,
        summary="Register webhook",
        description="Register a webhook endpoint to receive event notifications for this bank.",
        operation_id="create_webhook",
        tags=["Webhooks"],
        status_code=201,
    )
    async def api_create_webhook(
        bank_id: str,
        request: CreateWebhookRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Register a webhook for a bank."""
        try:
            pool = await app.state.memory._get_pool()
            from atulya_api.engine.memory_engine import fq_table

            webhook_id = uuid.uuid4()
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            row = await pool.fetchrow(
                f"""
                INSERT INTO {fq_table("webhooks")}
                (id, bank_id, url, secret, event_types, enabled, http_config, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, NOW(), NOW())
                RETURNING id, bank_id, url, secret, event_types, enabled,
                          http_config::text, created_at::text, updated_at::text
                """,
                webhook_id,
                bank_id,
                request.url,
                request.secret,
                request.event_types,
                request.enabled,
                request.http_config.model_dump_json(),
            )
            return WebhookResponse(
                id=str(row["id"]),
                bank_id=row["bank_id"],
                url=row["url"],
                secret=None,  # Never return secret in responses
                event_types=list(row["event_types"]) if row["event_types"] else [],
                enabled=row["enabled"],
                http_config=WebhookHttpConfig.model_validate_json(row["http_config"])
                if row["http_config"]
                else WebhookHttpConfig(),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in POST /v1/default/banks/{bank_id}/webhooks: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/webhooks",
        response_model=WebhookListResponse,
        summary="List webhooks",
        description="List all webhooks registered for a bank.",
        operation_id="list_webhooks",
        tags=["Webhooks"],
    )
    async def api_list_webhooks(
        bank_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """List webhooks for a bank."""
        try:
            pool = await app.state.memory._get_pool()
            from atulya_api.engine.memory_engine import fq_table

            rows = await pool.fetch(
                f"""
                SELECT id, bank_id, url, secret, event_types, enabled,
                       http_config::text, created_at::text, updated_at::text
                FROM {fq_table("webhooks")}
                WHERE bank_id = $1
                ORDER BY created_at
                """,
                bank_id,
            )
            return WebhookListResponse(
                items=[
                    WebhookResponse(
                        id=str(row["id"]),
                        bank_id=row["bank_id"],
                        url=row["url"],
                        secret=None,  # Never return secret in responses
                        event_types=list(row["event_types"]) if row["event_types"] else [],
                        enabled=row["enabled"],
                        http_config=WebhookHttpConfig.model_validate_json(row["http_config"])
                        if row["http_config"]
                        else WebhookHttpConfig(),
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                    for row in rows
                ]
            )
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in GET /v1/default/banks/{bank_id}/webhooks: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete(
        "/v1/default/banks/{bank_id}/webhooks/{webhook_id}",
        response_model=DeleteResponse,
        summary="Delete webhook",
        description="Remove a registered webhook.",
        operation_id="delete_webhook",
        tags=["Webhooks"],
    )
    async def api_delete_webhook(
        bank_id: str,
        webhook_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Delete a webhook."""
        try:
            pool = await app.state.memory._get_pool()
            from atulya_api.engine.memory_engine import fq_table

            result = await pool.execute(
                f"DELETE FROM {fq_table('webhooks')} WHERE id = $1 AND bank_id = $2",
                uuid.UUID(webhook_id),
                bank_id,
            )
            deleted = int(result.split()[-1]) if result else 0
            if deleted == 0:
                raise HTTPException(status_code=404, detail="Webhook not found")
            return DeleteResponse(success=True)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in DELETE /v1/default/banks/{bank_id}/webhooks/{webhook_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.patch(
        "/v1/default/banks/{bank_id}/webhooks/{webhook_id}",
        response_model=WebhookResponse,
        summary="Update webhook",
        description="Update one or more fields of a registered webhook. Only provided fields are changed.",
        operation_id="update_webhook",
        tags=["Webhooks"],
    )
    async def api_update_webhook(
        bank_id: str,
        webhook_id: str,
        request: UpdateWebhookRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Update a webhook's fields (PATCH semantics — only sent fields are updated)."""
        try:
            pool = await app.state.memory._get_pool()
            from atulya_api.engine.memory_engine import fq_table

            set_clauses: list[str] = []
            params: list = [uuid.UUID(webhook_id), bank_id]

            fields = request.model_fields_set
            if "url" in fields:
                params.append(request.url)
                set_clauses.append(f"url = ${len(params)}")
            if "secret" in fields:
                params.append(request.secret)
                set_clauses.append(f"secret = ${len(params)}")
            if "event_types" in fields:
                params.append(request.event_types)
                set_clauses.append(f"event_types = ${len(params)}")
            if "enabled" in fields:
                params.append(request.enabled)
                set_clauses.append(f"enabled = ${len(params)}")
            if "http_config" in fields:
                params.append(request.http_config.model_dump_json())
                set_clauses.append(f"http_config = ${len(params)}::jsonb")

            if not set_clauses:
                raise HTTPException(status_code=422, detail="No fields provided to update")

            set_clauses.append("updated_at = NOW()")
            row = await pool.fetchrow(
                f"""
                UPDATE {fq_table("webhooks")}
                SET {", ".join(set_clauses)}
                WHERE id = $1 AND bank_id = $2
                RETURNING id, bank_id, url, secret, event_types, enabled,
                          http_config::text, created_at::text, updated_at::text
                """,
                *params,
            )
            if not row:
                raise HTTPException(status_code=404, detail="Webhook not found")
            return WebhookResponse(
                id=str(row["id"]),
                bank_id=row["bank_id"],
                url=row["url"],
                secret=None,
                event_types=list(row["event_types"]) if row["event_types"] else [],
                enabled=row["enabled"],
                http_config=WebhookHttpConfig.model_validate_json(row["http_config"])
                if row["http_config"]
                else WebhookHttpConfig(),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in PATCH /v1/default/banks/{bank_id}/webhooks/{webhook_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/webhooks/{webhook_id}/deliveries",
        response_model=WebhookDeliveryListResponse,
        summary="List webhook deliveries",
        description="Inspect delivery history for a webhook (useful for debugging).",
        operation_id="list_webhook_deliveries",
        tags=["Webhooks"],
    )
    async def api_list_webhook_deliveries(
        bank_id: str,
        webhook_id: str,
        limit: int = Query(default=50, le=200, description="Maximum number of deliveries to return"),
        cursor: str | None = Query(default=None, description="Pagination cursor (created_at of last item)"),
        request_context: RequestContext = Depends(get_request_context),
    ):
        """List deliveries for a specific webhook, newest first. Use next_cursor for pagination."""
        try:
            pool = await app.state.memory._get_pool()
            from atulya_api.engine.memory_engine import fq_table

            # Verify webhook belongs to this bank
            webhook_row = await pool.fetchrow(
                f"SELECT id FROM {fq_table('webhooks')} WHERE id = $1 AND bank_id = $2",
                uuid.UUID(webhook_id),
                bank_id,
            )
            if not webhook_row:
                raise HTTPException(status_code=404, detail="Webhook not found")

            # Fetch limit+1 to detect if there's a next page
            fetch_limit = limit + 1
            if cursor:
                rows = await pool.fetch(
                    f"""
                    SELECT operation_id, status, retry_count, next_retry_at::text,
                           error_message, task_payload, result_metadata::text, created_at::text, updated_at::text
                    FROM {fq_table("async_operations")}
                    WHERE operation_type = 'webhook_delivery'
                      AND bank_id = $1
                      AND task_payload->>'webhook_id' = $2
                      AND created_at < $3::timestamptz
                    ORDER BY created_at DESC
                    LIMIT $4
                    """,
                    bank_id,
                    webhook_id,
                    cursor,
                    fetch_limit,
                )
            else:
                rows = await pool.fetch(
                    f"""
                    SELECT operation_id, status, retry_count, next_retry_at::text,
                           error_message, task_payload, result_metadata::text, created_at::text, updated_at::text
                    FROM {fq_table("async_operations")}
                    WHERE operation_type = 'webhook_delivery'
                      AND bank_id = $1
                      AND task_payload->>'webhook_id' = $2
                    ORDER BY created_at DESC
                    LIMIT $3
                    """,
                    bank_id,
                    webhook_id,
                    fetch_limit,
                )

            has_more = len(rows) > limit
            page = rows[:limit]
            next_cursor = page[-1]["created_at"] if has_more and page else None
            return WebhookDeliveryListResponse(
                items=[WebhookDeliveryResponse.from_async_operation_row(dict(row)) for row in page],
                next_cursor=next_cursor,
            )
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in GET /v1/default/banks/{bank_id}/webhooks/{webhook_id}/deliveries: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/memories",
        response_model=RetainResponse,
        summary="Retain memories",
        description="Retain memory items with automatic fact extraction.\n\n"
        "This is the main endpoint for storing memories. It supports both synchronous and asynchronous processing via the `async` parameter.\n\n"
        "**Features:**\n"
        "- Efficient batch processing\n"
        "- Automatic fact extraction from natural language\n"
        "- Entity recognition and linking\n"
        "- Document tracking with automatic upsert (when document_id is provided)\n"
        "- Temporal and semantic linking\n"
        "- Optional asynchronous processing\n\n"
        "**The system automatically:**\n"
        "1. Extracts semantic facts from the content\n"
        "2. Generates embeddings\n"
        "3. Deduplicates similar facts\n"
        "4. Creates temporal, semantic, and entity links\n"
        "5. Tracks document metadata\n\n"
        "**When `async=true`:** Returns immediately after queuing. Use the operations endpoint to monitor progress.\n\n"
        "**When `async=false` (default):** Waits for processing to complete.\n\n"
        "**Note:** If a memory item has a `document_id` that already exists, the old document and its memory units will be deleted before creating new ones (upsert behavior).",
        operation_id="retain_memories",
        tags=["Memory"],
    )
    async def api_retain(
        bank_id: str, request: RetainRequest, request_context: RequestContext = Depends(get_request_context)
    ):
        """Retain memories with optional async processing."""
        metrics = get_metrics_collector()

        try:
            # Prepare contents for processing
            contents = []
            for item in request.items:
                content_dict = {"content": item.content}
                if item.timestamp == "unset":
                    content_dict["event_date"] = None
                elif item.timestamp:
                    content_dict["event_date"] = item.timestamp
                if item.context:
                    content_dict["context"] = item.context
                if item.metadata:
                    content_dict["metadata"] = item.metadata
                if item.document_id:
                    content_dict["document_id"] = item.document_id
                if item.entities:
                    content_dict["entities"] = [{"text": e.text, "type": e.type or "CONCEPT"} for e in item.entities]
                if item.tags:
                    content_dict["tags"] = item.tags
                if item.observation_scopes is not None:
                    content_dict["observation_scopes"] = item.observation_scopes
                contents.append(content_dict)

            if request.async_:
                # Async processing: queue task and return immediately
                result = await app.state.memory.submit_async_retain(
                    bank_id, contents, document_tags=request.document_tags, request_context=request_context
                )
                return RetainResponse.model_validate(
                    {
                        "success": True,
                        "bank_id": bank_id,
                        "items_count": result["items_count"],
                        "async": True,
                        "operation_id": result["operation_id"],
                    }
                )
            else:
                # Check if batch API is enabled - if so, require async mode
                from atulya_api.config import get_config

                config = get_config()
                if config.retain_batch_enabled:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Batch API is enabled (ATULYA_API_RETAIN_BATCH_ENABLED=true) but async=false. "
                            "Batch operations can take several minutes to hours and will timeout in synchronous mode. "
                            "Please set async=true in your request to use background processing, or disable batch API "
                            "by setting ATULYA_API_RETAIN_BATCH_ENABLED=false in your environment."
                        ),
                    )

                # Synchronous processing: wait for completion (record metrics)
                with metrics.record_operation("retain", bank_id=bank_id, source="api"):
                    result, usage = await app.state.memory.retain_batch_async(
                        bank_id=bank_id,
                        contents=contents,
                        document_tags=request.document_tags,
                        request_context=request_context,
                        return_usage=True,
                        outbox_callback=app.state.memory._build_retain_outbox_callback(
                            bank_id=bank_id,
                            contents=contents,
                            operation_id=None,
                            schema=_current_schema.get(),
                        ),
                    )

                return RetainResponse.model_validate(
                    {"success": True, "bank_id": bank_id, "items_count": len(contents), "async": False, "usage": usage}
                )
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            # Create a summary of the input for debugging
            input_summary = []
            for i, item in enumerate(request.items):
                content_preview = item.content[:100] + "..." if len(item.content) > 100 else item.content
                input_summary.append(
                    f"  [{i}] content={content_preview!r}, context={item.context}, timestamp={item.timestamp}"
                )
            input_debug = "\n".join(input_summary)

            error_detail = (
                f"{str(e)}\n\n"
                f"Input ({len(request.items)} items):\n{input_debug}\n\n"
                f"Traceback:\n{traceback.format_exc()}"
            )
            logger.error(f"Error in /v1/default/banks/{bank_id}/memories (retain): {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/files/retain",
        response_model=FileRetainResponse,
        summary="Convert files to memories",
        description="Upload files (PDF, DOCX, etc.), convert them to markdown, and retain as memories.\n\n"
        "This endpoint handles file upload, conversion, and memory creation in a single operation.\n\n"
        "**Features:**\n"
        "- Supports PDF, DOCX, PPTX, XLSX, images (with OCR), audio (with transcription)\n"
        "- Automatic file-to-markdown conversion using pluggable parsers\n"
        "- Files stored in object storage (PostgreSQL by default, S3 for production)\n"
        "- Each file becomes a separate document with optional metadata/tags\n"
        "- Always processes asynchronously — returns operation IDs immediately\n\n"
        "**The system automatically:**\n"
        "1. Stores uploaded files in object storage\n"
        "2. Converts files to markdown\n"
        "3. Creates document records with file metadata\n"
        "4. Extracts facts and creates memory units (same as regular retain)\n\n"
        "Use the operations endpoint to monitor progress.\n\n"
        "**Request format:** multipart/form-data with:\n"
        "- `files`: One or more files to upload\n"
        "- `request`: JSON string with FileRetainRequest model\n\n"
        "**Parser selection:**\n"
        "- Set `parser` in the request body to override the server default for all files.\n"
        "- Set `parser` inside a `files_metadata` entry for per-file control.\n"
        "- Pass a list (e.g. `['iris', 'markitdown']`) to define an ordered fallback chain — "
        "each parser is tried in sequence until one succeeds.\n"
        "- Falls back to the server default (`ATULYA_API_FILE_PARSER`) if not specified.\n"
        "- Only parsers enabled on the server may be requested; others return HTTP 400.",
        operation_id="file_retain",
        tags=["Files"],
    )
    async def api_file_retain(
        bank_id: str,
        files: list[UploadFile] = File(..., description="Files to upload and convert"),
        request: str = Form(..., description="JSON string with FileRetainRequest model"),
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Upload and convert files to memories."""
        from atulya_api.config import get_config

        config = get_config()

        # Check if file upload API is enabled
        if not config.enable_file_upload_api:
            raise HTTPException(
                status_code=404,
                detail="File upload API is disabled. Set ATULYA_API_ENABLE_FILE_UPLOAD_API=true to enable.",
            )

        try:
            # Parse request JSON
            try:
                request_data = FileRetainRequest.model_validate_json(request)
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid request JSON: {str(e)}",
                )

            # Validate file count
            if len(files) > config.file_conversion_max_batch_size:
                raise HTTPException(
                    status_code=400,
                    detail=f"Too many files. Maximum {config.file_conversion_max_batch_size} files per request.",
                )

            # Validate files_metadata count matches files count if provided
            if request_data.files_metadata and len(request_data.files_metadata) != len(files):
                raise HTTPException(
                    status_code=400,
                    detail=f"files_metadata count ({len(request_data.files_metadata)}) must match files count ({len(files)})",
                )

            # Resolve the registered parser names for allowlist validation
            registered_parsers = app.state.memory._parser_registry.list_parsers()
            allowlist = config.file_parser_allowlist if config.file_parser_allowlist is not None else registered_parsers

            def _resolve_parser(raw: str | list[str] | None) -> list[str]:
                """Normalize parser value to a non-empty list of names."""
                if raw is None:
                    return config.file_parser
                return [raw] if isinstance(raw, str) else list(raw)

            def _validate_parsers(parsers: list[str], context: str) -> None:
                """Raise HTTP 400 if any parser name is not in the allowlist."""
                disallowed = [p for p in parsers if p not in allowlist]
                if disallowed:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Parser(s) not available ({context}): {disallowed}. Available: {allowlist}",
                    )

            # Validate request-level parser early (before reading files)
            if request_data.parser is not None:
                _validate_parsers(_resolve_parser(request_data.parser), "request-level parser")

            # Prepare file items and calculate total batch size
            import io

            file_items = []
            total_batch_size = 0

            for i, file in enumerate(files):
                # Read file content to check size
                file_content = await file.read()
                total_batch_size += len(file_content)

                # Create a mock UploadFile with the necessary attributes
                class FileWrapper:
                    def __init__(self, content, filename, content_type):
                        self._content = content
                        self.filename = filename
                        self.content_type = content_type

                    async def read(self):
                        return self._content

                wrapped_file = FileWrapper(file_content, file.filename, file.content_type)

                # Get per-file metadata
                file_meta = request_data.files_metadata[i] if request_data.files_metadata else FileRetainMetadata()
                doc_id = file_meta.document_id or f"file_{uuid.uuid4()}"

                # Resolve and validate per-file parser chain
                # Priority: per-file > request-level > server default
                raw_parser = file_meta.parser if file_meta.parser is not None else request_data.parser
                parser_chain = _resolve_parser(raw_parser)
                _validate_parsers(parser_chain, f"file '{file.filename}'")

                item = {
                    "file": wrapped_file,
                    "document_id": doc_id,
                    "context": file_meta.context,
                    "metadata": file_meta.metadata or {},
                    "tags": file_meta.tags or [],
                    "timestamp": file_meta.timestamp,
                    "parser": parser_chain,
                }
                file_items.append(item)

            # Check total batch size after processing all files
            if total_batch_size > config.file_conversion_max_batch_size_bytes:
                total_mb = total_batch_size / (1024 * 1024)
                raise HTTPException(
                    status_code=400,
                    detail=f"Total batch size ({total_mb:.1f}MB) exceeds maximum of {config.file_conversion_max_batch_size_mb}MB",
                )

            result = await app.state.memory.submit_async_file_retain(
                bank_id=bank_id,
                file_items=file_items,
                document_tags=None,
                request_context=request_context,
            )
            return FileRetainResponse.model_validate(
                {
                    "operation_ids": result["operation_ids"],
                }
            )

        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/files/retain: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/codebases/import/zip",
        response_model=CodebaseImportResponse,
        summary="Import a codebase from ZIP",
        description="Upload a repository ZIP archive and build a deterministic codebase snapshot without cloning or LLM indexing.",
        operation_id="import_codebase_zip",
        tags=["Codebases"],
    )
    async def api_codebase_import_zip(
        bank_id: str,
        archive: UploadFile = File(..., description="Repository ZIP archive"),
        request: str = Form(..., description="JSON string with CodebaseImportZipRequest model"),
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Import a ZIP-backed codebase into a bank."""
        try:
            try:
                request_data = CodebaseImportZipRequest.model_validate_json(request)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid request JSON: {str(e)}")

            archive_bytes = await archive.read()
            result = await app.state.memory.submit_async_codebase_zip_import(
                bank_id=bank_id,
                name=request_data.name,
                archive_name=archive.filename or "archive.zip",
                archive_bytes=archive_bytes,
                root_path=request_data.root_path,
                include_globs=request_data.include_globs,
                exclude_globs=request_data.exclude_globs,
                refresh_existing=request_data.refresh_existing,
                request_context=request_context,
            )
            return CodebaseImportResponse.model_validate(result)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/codebases/import/zip: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/codebases/import/github",
        response_model=CodebaseGithubImportResponse,
        summary="Import a public GitHub codebase",
        description="Resolve a public GitHub ref, download its archive, and build a deterministic codebase snapshot.",
        operation_id="import_codebase_github",
        tags=["Codebases"],
    )
    async def api_codebase_import_github(
        bank_id: str,
        request: CodebaseImportGithubRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Import a public GitHub-backed codebase into a bank."""
        try:
            result = await app.state.memory.submit_async_codebase_github_import(
                bank_id=bank_id,
                owner=request.owner,
                repo=request.repo,
                ref=request.ref,
                root_path=request.root_path,
                include_globs=request.include_globs,
                exclude_globs=request.exclude_globs,
                refresh_existing=request.refresh_existing,
                request_context=request_context,
            )
            return CodebaseGithubImportResponse.model_validate(result)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/codebases/import/github: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/codebases/{codebase_id}/refresh",
        response_model=CodebaseRefreshResponse,
        summary="Refresh a codebase snapshot",
        description="Refresh a GitHub-backed codebase by resolving the latest commit SHA and rebuilding a new reviewable ASD snapshot.",
        operation_id="refresh_codebase",
        tags=["Codebases"],
    )
    async def api_codebase_refresh(
        bank_id: str,
        codebase_id: str,
        request: CodebaseRefreshRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Refresh a codebase snapshot."""
        try:
            result = await app.state.memory.submit_async_codebase_refresh(
                bank_id=bank_id,
                codebase_id=codebase_id,
                ref=request.ref,
                full_rebuild=request.full_rebuild,
                request_context=request_context,
            )
            return CodebaseRefreshResponse.model_validate(result)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/codebases/{codebase_id}/refresh: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/codebases/{codebase_id}/approve",
        response_model=CodebaseApproveResponse,
        summary="Approve a codebase snapshot for memory hydration",
        description="Explicitly approve the current or selected reviewable codebase snapshot so Atulya can hydrate source-file text into memory.",
        operation_id="approve_codebase",
        tags=["Codebases"],
    )
    async def api_codebase_approve(
        bank_id: str,
        codebase_id: str,
        request: CodebaseApproveRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Queue a human-approved codebase memory hydration operation."""
        try:
            result = await app.state.memory.submit_async_codebase_approval(
                bank_id=bank_id,
                codebase_id=codebase_id,
                snapshot_id=request.snapshot_id,
                memory_ingest_mode=request.memory_ingest_mode,
                request_context=request_context,
            )
            return CodebaseApproveResponse.model_validate(result)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/codebases/{codebase_id}/approve: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/codebases",
        response_model=CodebaseListResponse,
        summary="List codebases",
        description="List imported codebases for a bank.",
        operation_id="list_codebases",
        tags=["Codebases"],
    )
    async def api_list_codebases(bank_id: str, request_context: RequestContext = Depends(get_request_context)):
        """List codebases for a bank."""
        try:
            items = await app.state.memory.list_codebases(bank_id, request_context=request_context)
            return CodebaseListResponse(items=[_codebase_response_model(item) for item in items])
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/codebases: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/codebases/{codebase_id}",
        response_model=CodebaseResponse,
        summary="Get codebase",
        description="Get codebase metadata plus current snapshot summary.",
        operation_id="get_codebase",
        tags=["Codebases"],
    )
    async def api_get_codebase(
        bank_id: str,
        codebase_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Get a codebase by ID."""
        try:
            codebase = await app.state.memory.get_codebase(bank_id, codebase_id, request_context=request_context)
            if not codebase:
                raise HTTPException(status_code=404, detail=f"Codebase {codebase_id} not found in bank {bank_id}")
            return _codebase_response_model(codebase)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/codebases/{codebase_id}: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/codebases/{codebase_id}/review",
        response_model=CodebaseReviewResponse,
        summary="Get codebase review summary",
        description="Return review queue counts, parse coverage, related chunk counts, and deterministic diagnostics for the current snapshot.",
        operation_id="get_codebase_review",
        tags=["Codebases"],
    )
    async def api_get_codebase_review(
        bank_id: str,
        codebase_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Get review summary for a codebase."""
        try:
            result = await app.state.memory.get_codebase_review(
                bank_id,
                codebase_id,
                request_context=request_context,
            )
            return CodebaseReviewResponse.model_validate(result)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/codebases/{codebase_id}/review: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/codebases/{codebase_id}/chunks",
        response_model=CodebaseChunksResponse,
        summary="List codebase review chunks",
        description="Return cursor-paginated semantic chunks for the current codebase snapshot.",
        operation_id="list_codebase_chunks",
        tags=["Codebases"],
    )
    async def api_list_codebase_chunks(
        bank_id: str,
        codebase_id: str,
        path_prefix: str | None = Query(default=None),
        language: str | None = Query(default=None),
        cluster_id: str | None = Query(default=None),
        route_target: str | None = Query(default=None),
        changed_only: bool = Query(default=False),
        kind: str | None = Query(default=None),
        q: str | None = Query(default=None),
        limit: int = Query(default=25, ge=1, le=100),
        cursor: str | None = Query(default=None),
        snapshot_id: str | None = Query(default=None),
        request_context: RequestContext = Depends(get_request_context),
    ):
        """List semantic chunks for a codebase snapshot."""
        try:
            result = await app.state.memory.list_codebase_chunks(
                bank_id,
                codebase_id,
                path_prefix=path_prefix,
                language=language,
                cluster_id=cluster_id,
                route_target=route_target,
                changed_only=changed_only,
                kind=kind,
                q=q,
                limit=limit,
                cursor=cursor,
                snapshot_id=snapshot_id,
                request_context=request_context,
            )
            return CodebaseChunksResponse.model_validate(
                {
                    **result,
                    "items": [CodebaseChunkItemResponse.model_validate(item) for item in result["items"]],
                }
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/codebases/{codebase_id}/chunks: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/codebases/{codebase_id}/chunks/{chunk_id}",
        response_model=CodebaseChunkDetailResponse,
        summary="Get codebase chunk detail",
        description="Return detailed code preview, related chunks, symbols, and impact edges for one chunk.",
        operation_id="get_codebase_chunk_detail",
        tags=["Codebases"],
    )
    async def api_get_codebase_chunk_detail(
        bank_id: str,
        codebase_id: str,
        chunk_id: str,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Get one review chunk in detail."""
        try:
            result = await app.state.memory.get_codebase_chunk_detail(
                bank_id,
                codebase_id,
                chunk_id,
                request_context=request_context,
            )
            return CodebaseChunkDetailResponse.model_validate(result)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(
                f"Error in /v1/default/banks/{bank_id}/codebases/{codebase_id}/chunks/{chunk_id}: {error_detail}"
            )
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/codebases/{codebase_id}/review/route",
        response_model=CodebaseRouteResponse,
        summary="Route review items",
        description="Bulk-route chunk review items to memory, research, dismissed, or back to unrouted.",
        operation_id="route_codebase_review_items",
        tags=["Codebases"],
    )
    async def api_route_codebase_review_items(
        bank_id: str,
        codebase_id: str,
        request: CodebaseRouteRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Route codebase review items in bulk."""
        try:
            result = await app.state.memory.route_codebase_review_items(
                bank_id,
                codebase_id,
                item_ids=request.item_ids,
                target=request.target,
                queue_memory_import=request.queue_memory_import,
                memory_ingest_mode=request.memory_ingest_mode,
                request_context=request_context,
            )
            return CodebaseRouteResponse.model_validate(result)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/codebases/{codebase_id}/review/route: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/codebases/{codebase_id}/research",
        response_model=CodebaseChunksResponse,
        summary="List research queue items",
        description="Return chunks currently routed to the codebase research queue.",
        operation_id="list_codebase_research_queue",
        tags=["Codebases"],
    )
    async def api_list_codebase_research_queue(
        bank_id: str,
        codebase_id: str,
        cursor: str | None = Query(default=None),
        limit: int = Query(default=25, ge=1, le=100),
        request_context: RequestContext = Depends(get_request_context),
    ):
        """List research queue items."""
        try:
            result = await app.state.memory.list_codebase_research_queue(
                bank_id,
                codebase_id,
                cursor=cursor,
                limit=limit,
                request_context=request_context,
            )
            return CodebaseChunksResponse.model_validate(
                {
                    **result,
                    "items": [CodebaseChunkItemResponse.model_validate(item) for item in result["items"]],
                }
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/codebases/{codebase_id}/research: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/codebases/{codebase_id}/files",
        response_model=CodebaseFilesResponse,
        summary="List codebase files",
        description="Return the repo map and filtered file listing for a codebase snapshot.",
        operation_id="list_codebase_files",
        tags=["Codebases"],
    )
    async def api_list_codebase_files(
        bank_id: str,
        codebase_id: str,
        path_prefix: str | None = Query(default=None, description="Only include files under this path prefix"),
        language: str | None = Query(default=None, description="Filter by detected language"),
        changed_only: bool = Query(default=False, description="Only include changed or added files"),
        snapshot_id: str | None = Query(default=None, description="Optional snapshot override"),
        request_context: RequestContext = Depends(get_request_context),
    ):
        """List files for a codebase snapshot."""
        try:
            result = await app.state.memory.list_codebase_files(
                bank_id,
                codebase_id,
                path_prefix=path_prefix,
                language=language,
                changed_only=changed_only,
                snapshot_id=snapshot_id,
                request_context=request_context,
            )
            codebase = await app.state.memory.get_codebase(bank_id, codebase_id, request_context=request_context)
            if not codebase:
                raise HTTPException(status_code=404, detail=f"Codebase {codebase_id} not found in bank {bank_id}")
            return CodebaseFilesResponse.model_validate(
                {
                    **result,
                    "source_ref": codebase.get("source_ref"),
                    "source_commit_sha": codebase.get("source_commit_sha"),
                    "snapshot_status": codebase.get("snapshot_status"),
                    "items": [CodebaseFileItemResponse.model_validate(item) for item in result["items"]],
                }
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/codebases/{codebase_id}/files: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/default/banks/{bank_id}/codebases/{codebase_id}/symbols",
        response_model=CodebaseSymbolsResponse,
        summary="Search codebase symbols",
        description="Search deterministic symbols by exact, prefix, or fuzzy match.",
        operation_id="search_codebase_symbols",
        tags=["Codebases"],
    )
    async def api_search_codebase_symbols(
        bank_id: str,
        codebase_id: str,
        q: str = Query(..., min_length=1, description="Symbol query"),
        kind: str | None = Query(default=None, description="Optional symbol kind filter"),
        path_prefix: str | None = Query(default=None, description="Only search under this path prefix"),
        language: str | None = Query(default=None, description="Filter by detected language"),
        limit: int = Query(default=50, ge=1, le=200, description="Maximum number of symbol matches"),
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Search symbols in a codebase snapshot."""
        try:
            result = await app.state.memory.search_codebase_symbols(
                bank_id,
                codebase_id,
                q=q,
                kind=kind,
                path_prefix=path_prefix,
                language=language,
                limit=limit,
                request_context=request_context,
            )
            return CodebaseSymbolsResponse.model_validate(
                {
                    **result,
                    "items": [CodebaseSymbolMatchResponse.model_validate(item) for item in result["items"]],
                }
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/codebases/{codebase_id}/symbols: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post(
        "/v1/default/banks/{bank_id}/codebases/{codebase_id}/impact",
        response_model=CodebaseImpactResponse,
        summary="Analyze codebase impact",
        description="Run deterministic impact analysis from a path, symbol, or query over the codebase graph.",
        operation_id="analyze_codebase_impact",
        tags=["Codebases"],
    )
    async def api_codebase_impact(
        bank_id: str,
        codebase_id: str,
        request: CodebaseImpactRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Analyze impact within a codebase snapshot."""
        provided = [value for value in (request.path, request.symbol, request.query) if value]
        if len(provided) != 1:
            raise HTTPException(status_code=400, detail="Exactly one of path, symbol, or query is required.")

        try:
            result = await app.state.memory.analyze_codebase_impact(
                bank_id,
                codebase_id,
                path=request.path,
                symbol=request.symbol,
                query=request.query,
                max_depth=request.max_depth,
                limit=request.limit,
                request_context=request_context,
            )
            return CodebaseImpactResponse.model_validate(
                {
                    **result,
                    "seed": (
                        CodebaseImpactSeedResponse.model_validate(result["seed"])
                        if result.get("seed") is not None
                        else None
                    ),
                    "impacted_files": [
                        CodebaseImpactFileResponse.model_validate(item) for item in result["impacted_files"]
                    ],
                    "matched_symbols": [
                        CodebaseSymbolMatchResponse.model_validate(item) for item in result["matched_symbols"]
                    ],
                    "edges": [CodebaseImpactEdgeResponse.model_validate(item) for item in result["edges"]],
                }
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/codebases/{codebase_id}/impact: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete(
        "/v1/default/banks/{bank_id}/memories",
        response_model=DeleteResponse,
        summary="Clear memory bank memories",
        description="Delete memory units for a memory bank. Optionally filter by type (world, experience, opinion) to delete only specific types. This is a destructive operation that cannot be undone. The bank profile (disposition and background) will be preserved.",
        operation_id="clear_bank_memories",
        tags=["Memory"],
    )
    async def api_clear_bank_memories(
        bank_id: str,
        type: str | None = Query(None, description="Optional fact type filter (world, experience, opinion)"),
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Clear memories for a memory bank, optionally filtered by type."""
        try:
            await app.state.memory.delete_bank(bank_id, fact_type=type, request_context=request_context)

            return DeleteResponse(success=True)
        except OperationValidationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.reason)
        except (AuthenticationError, HTTPException):
            raise
        except Exception as e:
            import traceback

            error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.error(f"Error in /v1/default/banks/{bank_id}/memories: {error_detail}")
            raise HTTPException(status_code=500, detail=str(e))
