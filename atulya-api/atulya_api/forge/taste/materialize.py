"""Map Taste sets to AtulyaTrainingRecord for export."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from atulya_api.forge.models import (
    AtulyaTrainingRecord,
    LineageBlock,
    ProvenanceBlock,
    QualityScore,
    TimelineEpisode,
    TimelineSession,
    TimelineTurn,
    TrainingLabels,
    TrainingTask,
)

from .models import TasteSchemaType, TasteSet


def payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _payload_to_turns(payload: dict[str, Any], schema_type: TasteSchemaType) -> list[TimelineTurn]:
    if schema_type == "openai_chat":
        messages = payload.get("messages") or []
        return [
            TimelineTurn(role=str(msg.get("role", "user")), content=str(msg.get("content", "")))
            for msg in messages
            if isinstance(msg, dict)
        ]
    if schema_type == "qa_pair":
        question = str(payload.get("question", ""))
        answer = str(payload.get("answer", ""))
        return [
            TimelineTurn(role="user", content=question),
            TimelineTurn(role="assistant", content=answer),
        ]
    text = json.dumps(payload, ensure_ascii=False)
    return [TimelineTurn(role="user", content=text)]


def materialize_taste_set(
    taste_set: TasteSet,
    *,
    schema_type: TasteSchemaType,
    dataset_id: str,
    bank_id: str,
) -> AtulyaTrainingRecord:
    turns = _payload_to_turns(taste_set.working_payload, schema_type)
    now = datetime.now(timezone.utc)
    labels = TrainingLabels()
    if schema_type == "qa_pair":
        labels.answer = str(taste_set.working_payload.get("answer", ""))
        labels.gold_answer = str(taste_set.source_payload.get("answer", ""))
    elif schema_type == "openai_chat":
        messages = taste_set.working_payload.get("messages") or []
        assistant = next((m for m in reversed(messages) if m.get("role") == "assistant"), None)
        if assistant:
            labels.answer = str(assistant.get("content", ""))

    issues: list[str] = []
    if not turns or not any(t.content.strip() for t in turns):
        issues.append("empty_content")

    quality = QualityScore(
        overall=1.0 if not issues else 0.5,
        provenance_complete=True,
        temporal_coherent=True,
        citation_valid=True,
        exportable=not issues,
        issues=issues,
    )

    return AtulyaTrainingRecord(
        record_id=f"taste_{taste_set.id}",
        forge_job_id=f"taste_dataset_{dataset_id}",
        bank_id=bank_id,
        recipe_id="taste_studio",
        domain_tags=list(taste_set.taste_tags),
        timeline=TimelineEpisode(
            sessions=[
                TimelineSession(
                    session_id=taste_set.set_key,
                    event_date=now,
                    tags=list(taste_set.taste_tags),
                    turns=turns,
                )
            ]
        ),
        tasks=[
            TrainingTask(
                task_type="taste_curation",
                query=taste_set.set_key,
                metadata={
                    "dataset_id": dataset_id,
                    "set_id": taste_set.id,
                    "parent_set_id": taste_set.parent_set_id,
                    "variant_index": taste_set.variant_index,
                    "schema_type": schema_type,
                },
            )
        ],
        labels=labels,
        provenance=ProvenanceBlock(ingest_adapter="taste_studio"),
        quality=quality,
        lineage=LineageBlock(
            recipe_id="taste_studio",
            recipe_version="1",
            adapter_version="taste_studio_v1",
            snapshot_hash=payload_hash(taste_set.working_payload),
            exported_at=now,
        ),
    )


def materialize_taste_sets(
    taste_sets: list[TasteSet],
    *,
    schema_type: TasteSchemaType,
    dataset_id: str,
    bank_id: str,
) -> list[AtulyaTrainingRecord]:
    return [
        materialize_taste_set(row, schema_type=schema_type, dataset_id=dataset_id, bank_id=bank_id)
        for row in taste_sets
    ]
