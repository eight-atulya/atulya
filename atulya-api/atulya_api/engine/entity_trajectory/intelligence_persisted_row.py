"""Normalize persisted entity intelligence rows for API consumers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from atulya_api.engine.jsonb_compat import decode_jsonb


def _json_obj(raw: Any) -> dict[str, Any]:
    data = decode_jsonb(raw, {})
    return data if isinstance(data, dict) else {}


def entity_intelligence_payload_from_record(row: Mapping[str, Any]) -> dict[str, Any]:
    computed = row.get("computed_at")
    if isinstance(computed, datetime):
        computed_at = computed.isoformat()
    elif isinstance(computed, str):
        computed_at = computed
    else:
        computed_at = None

    return {
        "bank_id": row.get("bank_id") or "",
        "computed_at": computed_at,
        "entity_count": int(row.get("entity_count") or 0),
        "source_entity_count": int(row.get("source_entity_count") or 0),
        "entity_snapshot_hash": row.get("entity_snapshot_hash") or "",
        "content": row.get("content") or "",
        "structured_content": _json_obj(row.get("structured_content")),
        "entity_context": _json_obj(row.get("entity_context")),
        "delta_metadata": _json_obj(row.get("delta_metadata")),
        "llm_model": row.get("llm_model") or "",
        "prompt_version": row.get("prompt_version") or "",
    }
