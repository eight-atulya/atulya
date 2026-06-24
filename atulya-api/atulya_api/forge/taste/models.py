"""Pydantic models for Taste Studio."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

TasteSchemaType = Literal["openai_chat", "qa_pair", "custom"]
TasteSetStatus = Literal["draft", "ready", "retained", "archived"]
TasteTransformOpId = Literal["raw", "spellfix_llm", "tone_shift"]


class TransformLogEntry(BaseModel):
    op_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    before_hash: str
    after_hash: str
    at: datetime
    model: str | None = None


class TransformOpSpec(BaseModel):
    op: TasteTransformOpId
    params: dict[str, Any] = Field(default_factory=dict)


class TasteDataset(BaseModel):
    id: str
    bank_id: str
    name: str
    description: str | None = None
    schema_type: TasteSchemaType = "openai_chat"
    taste_tags: list[str] = Field(default_factory=list)
    taste_profile_json: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    set_count: int = 0


class TasteSet(BaseModel):
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
    entity_ids: list[str] = Field(default_factory=list)
    memory_unit_ids: list[str] = Field(default_factory=list)
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
    dataset_id: str
    set_ids: list[str] = Field(default_factory=list)
    chain_id: str | None = None
    ops: list[TransformOpSpec] = Field(default_factory=list)
    preview: bool = False


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
