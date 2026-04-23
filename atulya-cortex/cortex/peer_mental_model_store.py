"""peer_mental_model_store.py — file-backed mirror of peer mental models.

For remote channels (especially WhatsApp), operators often want an on-disk
artifact alongside DB state. This module writes one JSON file per peer under:

    ~/.atulya/cortex/whatsapp/mental-models/<phone-or-peer>.json

The file stores current mental models plus a local delta log.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MentalModelSnapshot:
    model_id: str
    name: str
    content: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BankEntitySnapshot:
    entity_id: str
    kind: str
    text: str
    usage_score: float = 0.0


def sync_peer_mental_model_file(
    *,
    directory: Path,
    peer_key: str,
    bank_id: str,
    models: list[MentalModelSnapshot],
    entities: list[BankEntitySnapshot] | None = None,
    max_delta_entries: int = 500,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_peer_file_stem(peer_key)}.json"
    old = _read_json(path)
    old_models = _index_models(old.get("mental_models", []))

    current = {m.model_id: m for m in models}
    delta = list(old.get("delta", [])) if isinstance(old.get("delta", []), list) else []
    now = _iso_now()

    for model_id, model in current.items():
        prev = old_models.get(model_id)
        if prev is None:
            delta.append(
                {
                    "at": now,
                    "change": "created",
                    "mental_model_id": model_id,
                    "name": model.name,
                    "new_hash": model.content_hash,
                }
            )
            continue
        if prev.get("content_hash") != model.content_hash:
            delta.append(
                {
                    "at": now,
                    "change": "updated",
                    "mental_model_id": model_id,
                    "name": model.name,
                    "old_hash": prev.get("content_hash", ""),
                    "new_hash": model.content_hash,
                }
            )

    for model_id, prev in old_models.items():
        if model_id not in current:
            delta.append(
                {
                    "at": now,
                    "change": "deleted",
                    "mental_model_id": model_id,
                    "name": prev.get("name", ""),
                    "old_hash": prev.get("content_hash", ""),
                }
            )

    entities = list(entities or [])
    entities_hash = _entities_hash(entities)
    old_entities_hash = str(old.get("top_entities_hash", "")).strip()
    if entities_hash != old_entities_hash:
        delta.append(
            {
                "at": now,
                "change": "entities_updated",
                "entities_count": len(entities),
                "old_hash": old_entities_hash,
                "new_hash": entities_hash,
            }
        )

    if max_delta_entries > 0 and len(delta) > max_delta_entries:
        delta = delta[-max_delta_entries:]

    payload = {
        "schema_version": 1,
        "peer_key": peer_key,
        "phone_number": _extract_phone_digits(peer_key),
        "bank_id": bank_id,
        "synced_at": now,
        "mental_models": [
            {
                "mental_model_id": m.model_id,
                "name": m.name,
                "content": m.content,
                "content_hash": m.content_hash,
            }
            for m in models
        ],
        "top_entities": [
            {
                "entity_id": e.entity_id,
                "kind": e.kind,
                "text": e.text,
                "usage_score": round(float(e.usage_score), 6),
            }
            for e in entities
        ],
        "top_entities_hash": entities_hash,
        "delta": delta,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def _peer_file_stem(peer_key: str) -> str:
    phone = _extract_phone_digits(peer_key)
    if phone:
        return phone
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", peer_key).strip("_")
    return stem[:80] or "unknown-peer"


def _extract_phone_digits(peer_key: str) -> str:
    head = (peer_key or "").split("@", 1)[0]
    digits = "".join(ch for ch in head if ch.isdigit())
    return digits[:24]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _index_models(items: list[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("mental_model_id", "")).strip()
        if not model_id:
            continue
        out[model_id] = item
    return out


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _entities_hash(entities: list[BankEntitySnapshot]) -> str:
    raw = [
        {
            "entity_id": e.entity_id,
            "kind": e.kind,
            "text": e.text,
            "usage_score": round(float(e.usage_score), 6),
        }
        for e in entities
    ]
    return hashlib.sha256(json.dumps(raw, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()


__all__ = ["BankEntitySnapshot", "MentalModelSnapshot", "sync_peer_mental_model_file"]

