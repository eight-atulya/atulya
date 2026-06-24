"""Retain taste sets into bank memory."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from atulya_api.forge.adapters.chat import _normalize_turn

from .errors import TasteValidationError
from .models import TasteSchemaType, TasteSet
from .store import update_set_after_retain

if TYPE_CHECKING:
    from atulya_api.engine.memory_engine import MemoryEngine
    from atulya_api.models import RequestContext


def taste_set_to_retain_item(
    taste_set: TasteSet,
    *,
    schema_type: TasteSchemaType,
    dataset_id: str,
    extra_tags: list[str] | None = None,
) -> dict[str, Any]:
    payload = taste_set.working_payload
    tags = list(extra_tags or []) + list(taste_set.taste_tags)
    tags.extend(
        [
            f"taste:dataset:{dataset_id}",
            f"taste:set:{taste_set.set_key}",
            "source:taste_studio",
        ]
    )

    if schema_type == "openai_chat":
        turns_raw = payload.get("messages") or []
        turns = [_normalize_turn(t) for t in turns_raw if isinstance(t, dict)]
        content = json.dumps(turns)
        context = f"Taste Studio set {taste_set.set_key}"
    elif schema_type == "qa_pair":
        turns = [
            _normalize_turn({"role": "user", "content": str(payload.get("question", ""))}),
            _normalize_turn({"role": "assistant", "content": str(payload.get("answer", ""))}),
        ]
        content = json.dumps(turns)
        context = f"Taste Studio Q&A {taste_set.set_key}"
    else:
        content = json.dumps(payload, ensure_ascii=False)
        context = f"Taste Studio custom {taste_set.set_key}"

    return {
        "content": content,
        "context": context,
        "event_date": datetime.now(timezone.utc),
        "document_id": f"taste_{taste_set.set_key}_{uuid.uuid4().hex[:8]}",
        "tags": tags,
    }


async def retain_taste_sets(
    memory_engine: "MemoryEngine",
    bank_id: str,
    *,
    taste_sets: list[TasteSet],
    schema_type: TasteSchemaType,
    dataset_id: str,
    request_context: "RequestContext",
) -> dict[str, Any]:
    already_retained = [row.set_key for row in taste_sets if row.status == "retained"]
    if already_retained:
        raise TasteValidationError(
            "One or more sets are already retained",
            field="set_ids",
            details={"set_keys": already_retained},
        )

    items = [taste_set_to_retain_item(row, schema_type=schema_type, dataset_id=dataset_id) for row in taste_sets]
    result = await memory_engine.retain_batch_async(
        bank_id=bank_id,
        contents=items,
        request_context=request_context,
    )
    unit_id_groups: list[list[str]] = result if isinstance(result, list) else []

    updated_sets: list[dict[str, Any]] = []
    flat_unit_ids: list[str] = []
    for idx, taste_set in enumerate(taste_sets):
        group = unit_id_groups[idx] if idx < len(unit_id_groups) else []
        memory_ids = [str(x) for x in group]
        flat_unit_ids.extend(memory_ids)
        updated = await update_set_after_retain(
            memory_engine,
            bank_id,
            taste_set.id,
            memory_unit_ids=memory_ids,
        )
        updated_sets.append(updated.model_dump(mode="json"))

    return {
        "retained_count": len(updated_sets),
        "memory_unit_ids": flat_unit_ids,
        "sets": updated_sets,
    }
