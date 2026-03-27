"""
Remote brain extraction client.

Connects to another Atulya instance's API to fetch distilled knowledge
(mental models, memory units, entities, activity timestamps) for
brain-to-brain learning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 30.0
MAX_PAGES = 20
LearningType = Literal["auto", "distilled", "structured", "raw_mirror"]


@dataclass(slots=True)
class RemoteBrainSource:
    """Configuration for a remote Atulya brain endpoint."""

    endpoint_url: str
    bank_id: str
    api_key: str = ""
    label: str = ""

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @property
    def base_url(self) -> str:
        return self.endpoint_url.rstrip("/")


@dataclass(slots=True)
class RemoteBrainPayload:
    """Extracted knowledge from a remote brain."""

    source: RemoteBrainSource
    mental_models: list[dict[str, Any]] = field(default_factory=list)
    memories: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    events: list[datetime] = field(default_factory=list)
    brain_snapshot_raw: bytes | None = None
    fetched_at: str = ""
    errors: list[str] = field(default_factory=list)
    capabilities: dict[str, Any] = field(default_factory=dict)
    learning_type_requested: LearningType = "auto"
    learning_type_effective: LearningType = "auto"


async def probe_remote_brain(source: RemoteBrainSource) -> dict[str, Any]:
    """Probe remote endpoint capabilities for robust strategy selection."""
    headers = source._headers()
    base = source.base_url
    bank = source.bank_id
    result: dict[str, Any] = {
        "version_ok": False,
        "banks_ok": False,
        "brain_export_ok": False,
        "mental_models_ok": False,
        "memories_ok": False,
        "entities_ok": False,
        "status_codes": {},
    }

    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT) as client:
        checks = {
            "version_ok": (f"{base}/v1/version", {}),
            "banks_ok": (f"{base}/v1/default/banks", {"limit": 1}),
            "brain_export_ok": (f"{base}/v1/default/banks/{bank}/brain/export", {}),
            "mental_models_ok": (f"{base}/v1/default/banks/{bank}/mental-models", {"limit": 1}),
            "memories_ok": (f"{base}/v1/default/banks/{bank}/memories/list", {"limit": 1}),
            "entities_ok": (f"{base}/v1/default/banks/{bank}/entities", {"limit": 1}),
        }
        for key, (url, params) in checks.items():
            try:
                resp = await client.get(url, headers=headers, params=params or None)
                result["status_codes"][key] = resp.status_code
                result[key] = resp.status_code == 200
            except Exception:
                result["status_codes"][key] = None
                result[key] = False
    return result


async def fetch_remote_brain(
    source: RemoteBrainSource,
    *,
    model_limit: int = 200,
    memory_limit: int = 500,
    learning_type: LearningType = "auto",
) -> RemoteBrainPayload:
    """
    Fetch knowledge from a remote Atulya instance.

    Tries multiple data sources in order of richness:
    1. .brain export (if enabled on remote — single request, fully distilled)
    2. Mental models + memory units + entities (REST API pagination)

    Timestamps from memory units are collected for activity model merging.
    """
    payload = RemoteBrainPayload(
        source=source,
        fetched_at=datetime.now(UTC).isoformat(),
        learning_type_requested=learning_type,
        learning_type_effective=learning_type,
    )
    headers = source._headers()
    base = source.base_url
    bank = source.bank_id

    # Always probe capabilities first so caller can explain fallback decisions.
    try:
        payload.capabilities = await probe_remote_brain(source)
    except Exception as exc:
        payload.errors.append(f"probe: {exc}")
        payload.capabilities = {}

    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT) as client:
        should_try_distilled = learning_type in ("auto", "distilled")
        should_try_structured = learning_type in ("auto", "structured")
        should_try_raw_mirror = learning_type == "raw_mirror"

        if should_try_distilled:
            # Try .brain export first (most efficient — single binary blob)
            try:
                resp = await client.get(f"{base}/v1/default/banks/{bank}/brain/export", headers=headers)
                if resp.status_code == 200:
                    payload.brain_snapshot_raw = resp.content
                    payload.learning_type_effective = "distilled"
                    logger.info("[REMOTE_BRAIN] Fetched .brain export from %s (%d bytes)", base, len(resp.content))
                elif learning_type == "distilled":
                    payload.errors.append(f"brain_export: status {resp.status_code}")
            except Exception as exc:
                if learning_type == "distilled":
                    payload.errors.append(f"brain_export: {exc}")
                logger.debug("[REMOTE_BRAIN] .brain export not available from %s: %s", base, exc)

        # Explicit distilled mode should not fallback into other fetch paths
        if learning_type == "distilled":
            return payload

        if should_try_structured:
            # Fetch mental models
            try:
                resp = await client.get(
                    f"{base}/v1/default/banks/{bank}/mental-models",
                    headers=headers,
                    params={"limit": model_limit},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", data) if isinstance(data, dict) else data
                    if isinstance(items, list):
                        payload.mental_models = items[:model_limit]
                        payload.learning_type_effective = "structured"
                        logger.info("[REMOTE_BRAIN] Fetched %d mental models from %s", len(payload.mental_models), base)
                else:
                    payload.errors.append(f"mental_models: status {resp.status_code}")
            except Exception as exc:
                payload.errors.append(f"mental_models: {exc}")
                logger.warning("[REMOTE_BRAIN] Failed to fetch mental models from %s: %s", base, exc)

        # Fetch memory units with pagination
        try:
            offset = 0
            page_size = min(memory_limit, 100)
            pages = 0
            while offset < memory_limit and pages < MAX_PAGES:
                resp = await client.get(
                    f"{base}/v1/default/banks/{bank}/memories/list",
                    headers=headers,
                    params={"limit": page_size, "offset": offset},
                )
                if resp.status_code != 200:
                    break
                data = resp.json()
                items = data.get("items", data) if isinstance(data, dict) else data
                if not isinstance(items, list) or not items:
                    break
                for item in items:
                    payload.memories.append(item)
                    ts = item.get("mentioned_at") or item.get("created_at")
                    if ts:
                        try:
                            if isinstance(ts, str):
                                parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            else:
                                parsed = ts
                            payload.events.append(parsed if isinstance(parsed, datetime) else datetime.now(UTC))
                        except (ValueError, TypeError):
                            pass
                offset += len(items)
                pages += 1
                if len(items) < page_size:
                    break
            if payload.learning_type_effective == "auto" and payload.memories:
                payload.learning_type_effective = "raw_mirror" if should_try_raw_mirror else "structured"
            logger.info(
                "[REMOTE_BRAIN] Fetched %d memories (%d events) from %s",
                len(payload.memories),
                len(payload.events),
                base,
            )
        except Exception as exc:
            payload.errors.append(f"memories: {exc}")
            logger.warning("[REMOTE_BRAIN] Failed to fetch memories from %s: %s", base, exc)

        if should_try_structured:
            # Fetch entities
            try:
                resp = await client.get(
                    f"{base}/v1/default/banks/{bank}/entities",
                    headers=headers,
                    params={"limit": 200},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", data) if isinstance(data, dict) else data
                    if isinstance(items, list):
                        payload.entities = items[:200]
                        logger.info("[REMOTE_BRAIN] Fetched %d entities from %s", len(payload.entities), base)
                else:
                    payload.errors.append(f"entities: status {resp.status_code}")
            except Exception as exc:
                payload.errors.append(f"entities: {exc}")
                logger.warning("[REMOTE_BRAIN] Failed to fetch entities from %s: %s", base, exc)

    return payload
