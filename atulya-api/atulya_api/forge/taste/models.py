"""Pydantic models for Taste Studio.

Purpose
    Request/response and persistence contracts for Taste Studio datasets, sets,
    transform chains, and operation payloads. Shared by HTTP layer, engine,
    store, and OpenAPI generation.

Trigger path
    - Validated at HTTP boundary and re-validated in worker job handlers.
    - ``TasteSet`` / ``TasteDataset`` constructed from DB rows in ``store.py``.

Inputs
    - JSON request bodies and asyncpg row fields mapped into these models.

Outputs
    - Serialized JSON via ``model_dump(mode="json")`` for API responses.
    - Type constraints enforced at parse time (schema types, status literals).

Side effects
    None at the model layer — pure data contracts.

Mutability
    - ``source_payload`` is the immutable import baseline; ``working_payload``
      is the editable copy transforms mutate.
    - ``transform_log`` grows append-only until revert clears it in store.

Impact radius
    - OpenAPI spec, control-plane TypeScript types, and all taste submodules.
    - Changing field names requires migration + client regeneration.

Core logic
    - Literal types encode allowed schema types, set statuses, and transform op IDs.
    - ``TasteTransformRequest.preview`` controls dry-run vs persist behavior.

Failure modes
    - Pydantic validation errors surface as 422 from FastAPI routes.

Maintenance notes
    - Good: add optional fields with defaults to preserve backward compatibility.
    - Bad: rename ``working_payload`` / ``source_payload`` without DB migration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

TasteSchemaType = Literal["openai_chat", "qa_pair", "custom"]
TasteSetStatus = Literal["draft", "ready", "retained", "archived"]
TasteTransformOpId = Literal["raw", "spellfix_llm", "tone_shift"]


class TransformLogEntry(BaseModel):
    """Audit entry for one transform op applied to a set's working payload."""

    op_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    before_hash: str  # payload_hash of working_payload before this op
    after_hash: str  # payload_hash after this op
    at: datetime
    model: str | None = None  # LLM model name when op used an LLM


class TransformOpSpec(BaseModel):
    """Single transform step: op id plus op-specific params."""

    op: TasteTransformOpId
    params: dict[str, Any] = Field(default_factory=dict)


class TasteDataset(BaseModel):
    """Container for curated training examples sharing one payload schema."""

    id: str
    bank_id: str
    name: str
    description: str | None = None
    schema_type: TasteSchemaType = "openai_chat"
    taste_tags: list[str] = Field(default_factory=list)
    taste_profile_json: dict[str, Any] | None = None  # optional style/profile metadata
    created_at: datetime | None = None
    updated_at: datetime | None = None
    set_count: int = 0  # denormalized count from store queries


class TasteSet(BaseModel):
    """One training example (or variant) within a dataset.

    ``source_payload`` is the imported baseline; ``working_payload`` is the
    editable copy. Variants share ``set_key`` with parent and differ by
    ``variant_index``.
    """

    id: str
    dataset_id: str
    bank_id: str
    set_key: str
    parent_set_id: str | None = None
    variant_index: int = 0
    source_payload: dict[str, Any]
    working_payload: dict[str, Any]
    transform_log: list[TransformLogEntry] = Field(default_factory=list)
    taste_tags: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)  # populated after retain
    memory_unit_ids: list[str] = Field(default_factory=list)  # populated after retain
    status: TasteSetStatus = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TasteTransformChain(BaseModel):
    id: str
    bank_id: str
    name: str
    ops: list[TransformOpSpec] = Field(default_factory=list)
    is_default: bool = False
    created_at: datetime | None = None


class TasteCatalogResponse(BaseModel):
    schema_types: list[dict[str, str]]
    transform_ops: list[dict[str, Any]]
    exporters: list[dict[str, str]]


class CreateTasteDatasetRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    schema_type: TasteSchemaType = "openai_chat"
    taste_tags: list[str] = Field(default_factory=list)


class UpdateTasteDatasetRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    taste_tags: list[str] | None = None
    taste_profile_json: dict[str, Any] | None = None


class ImportTasteSetsRequest(BaseModel):
    sets: list[dict[str, Any]] = Field(default_factory=list)
    jsonl: str | None = None
    taste_tags: list[str] = Field(default_factory=list)
    set_key_prefix: str | None = None


class UpdateTasteSetRequest(BaseModel):
    working_payload: dict[str, Any] | None = None
    taste_tags: list[str] | None = None
    status: TasteSetStatus | None = None


class TasteTransformRequest(BaseModel):
    """Transform request; empty ``set_ids`` means all sets in the dataset."""

    dataset_id: str
    set_ids: list[str] = Field(default_factory=list)
    chain_id: str | None = None  # mutually exclusive with inline ops
    ops: list[TransformOpSpec] = Field(default_factory=list)
    preview: bool = False  # when True, no DB writes


class TasteGenerateRequest(BaseModel):
    set_ids: list[str] = Field(default_factory=list)
    count: int = Field(default=8, ge=1, le=32)
    options: dict[str, Any] = Field(default_factory=dict)


class TasteRetainRequest(BaseModel):
    set_ids: list[str] = Field(min_length=1)


class TasteExportRequest(BaseModel):
    dataset_id: str
    set_ids: list[str] = Field(default_factory=list)
    adapter_id: str = "openai_chat_jsonl"
    options: dict[str, Any] = Field(default_factory=dict)


class TasteTransformPreviewItem(BaseModel):
    set_id: str
    set_key: str
    before: dict[str, Any]
    after: dict[str, Any]


class TasteTransformResult(BaseModel):
    preview: bool
    items: list[TasteTransformPreviewItem] = Field(default_factory=list)
    updated_count: int = 0
    operation_id: str | None = None
