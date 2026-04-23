"""peer_memory.py — atulya-embed bank per (cortex profile, peer).

Wires `memory.Hippocampus` + `memory.Recall` with one bank id per remote
contact. Creation is lazy: first interaction calls `acreate_bank` once,
then retains and recalls against that bank.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import os

from cortex.bus import MemoryKind, Recollection, Stimulus
from cortex.peer_mental_model_store import (
    BankEntitySnapshot,
    MentalModelSnapshot,
    sync_peer_mental_model_file,
)
from memory.hippocampus import Hippocampus
from memory.recall import Recall

logger = logging.getLogger(__name__)


@dataclass
class PeerMemoryBridge:
    """Holds an `AtulyaEmbedded` client plus encoder/recall organs."""

    embedded: Any
    hippocampus: Hippocampus
    recall: Recall
    recall_top_k: int
    whatsapp_mental_models_dir: Path | None = None
    whatsapp_memory_raw_dir: Path | None = None
    _ensured: set[str] = field(default_factory=set)
    _mental_prompt_cache: dict[str, tuple[float, str]] = field(default_factory=dict)
    _mental_prompt_ttl_s: float = 0.0

    async def ensure_bank(self, bank_id: str) -> None:
        """Create the bank if we have not seen this id in-process yet."""

        if bank_id in self._ensured:
            return
        try:
            await self.embedded.acreate_bank(
                bank_id,
                retain_mission="Store conversational turns and durable facts about this person.",
            )
        except Exception as exc:
            logger.warning("peer bank ensure failed for %s: %s", bank_id, exc)
            return
        self._ensured.add(bank_id)

    async def bank_mental_model_prompt(
        self,
        bank_id: str,
        *,
        peer_key: str = "",
        channel_root: str = "",
        max_models: int = 3,
        max_chars_per_model: int = 600,
        max_entities: int = 88,
    ) -> str:
        """Render a compact prompt block from this bank's mental models.

        This is used as peer-specific steering context in `Cortex._build_messages`.
        Empty string means "no bank-level mental model available".
        """

        cache_key = f"{channel_root}:{peer_key}:{bank_id}"
        cached = self._mental_prompt_cache.get(cache_key)
        now = time.monotonic()
        if cached is not None and (now - cached[0]) <= self._mental_prompt_ttl_s:
            return cached[1]

        await self.ensure_bank(bank_id)
        try:
            items = await self._list_mental_models(bank_id)
        except Exception as exc:
            logger.warning("peer mental-model list failed bank=%s: %s", bank_id, exc)
            self._mental_prompt_cache[cache_key] = (now, "")
            return ""

        lines: list[str] = []
        snapshots: list[MentalModelSnapshot] = []
        for item in items[: max(0, int(max_models))]:
            model_id = _pick(item, "id")
            name = _pick(item, "name") or "mental-model"
            content = _pick(item, "content")
            if not content and model_id:
                try:
                    detail = await self._get_mental_model(bank_id, model_id)
                    content = _pick(detail, "content")
                except Exception:
                    content = ""
            text = _squash_whitespace(str(content or ""))
            if not text:
                continue
            snapshots.append(MentalModelSnapshot(model_id=model_id or name, name=name, content=text))
            if len(text) > max_chars_per_model:
                text = text[: max_chars_per_model - 3].rstrip() + "..."
            lines.append(f"- {name}: {text}")

        top_entities = await self._top_used_bank_entities(bank_id, limit=max_entities)
        entity_lines: list[str] = []
        for entity in top_entities:
            snippet = entity.text
            if len(snippet) > 180:
                snippet = snippet[:177].rstrip() + "..."
            entity_lines.append(f"- [{entity.kind}] {entity.entity_id}: {snippet}")

        if (
            self.whatsapp_mental_models_dir is not None
            and peer_key
            and channel_root == "whatsapp"
        ):
            try:
                sync_peer_mental_model_file(
                    directory=self.whatsapp_mental_models_dir,
                    peer_key=peer_key,
                    bank_id=bank_id,
                    models=snapshots,
                    entities=top_entities,
                )
            except Exception as exc:
                logger.warning("peer mental-model file sync failed bank=%s peer=%s: %s", bank_id, peer_key, exc)

        if not lines and not entity_lines:
            self._mental_prompt_cache[cache_key] = (now, "")
            return ""

        sections: list[str] = []
        if lines:
            sections.append(
                "Peer bank mental model (primary guidance for this peer):\n"
                + "\n".join(lines)
                + "\nTreat this as the default stance for this peer unless the user explicitly overrides it."
            )
        if entity_lines:
            sections.append(
                "Top used entities from this peer bank (capped at 88):\n"
                + "\n".join(entity_lines[:max_entities])
            )
        block = "\n\n".join(sections)
        self._mental_prompt_cache[cache_key] = (now, block)
        return block

    async def _top_used_bank_entities(self, bank_id: str, *, limit: int = 88) -> list[BankEntitySnapshot]:
        cap = max(1, int(limit))
        try:
            items = await self._list_bank_memories(bank_id, limit=max(120, cap * 3), offset=0)
        except Exception as exc:
            logger.warning("peer entities list failed bank=%s: %s", bank_id, exc)
            return []

        scored: list[tuple[float, BankEntitySnapshot]] = []
        for idx, item in enumerate(items):
            entity_id = _pick(item, "id") or _pick(item, "memory_id") or _pick(item, "document_id") or f"mem-{idx}"
            kind = _pick(item, "type") or _pick(item, "kind") or "memory"
            text = _pick(item, "content") or _pick(item, "text") or _pick(item, "summary")
            if not text:
                continue
            usage = _usage_score(item, rank_index=idx)
            scored.append((usage, BankEntitySnapshot(entity_id=entity_id, kind=kind, text=_squash_whitespace(text), usage_score=usage)))

        scored.sort(key=lambda pair: (-pair[0], pair[1].entity_id))
        return [row for _, row in scored[:cap]]

    async def _list_mental_models(self, bank_id: str) -> list[Any]:
        client = _base_client(self.embedded)
        low = getattr(client, "_mental_models_api", None)
        if low is not None and hasattr(low, "list_mental_models"):
            timeout = getattr(client, "_timeout", None)
            out = await low.list_mental_models(bank_id, _request_timeout=timeout)
            return list(getattr(out, "items", []) or [])
        # Fallback for clients without low-level async API.
        listed = await asyncio.to_thread(self.embedded.mental_models.list, bank_id)
        return list(getattr(listed, "items", []) or [])

    async def _get_mental_model(self, bank_id: str, model_id: str) -> Any:
        client = _base_client(self.embedded)
        low = getattr(client, "_mental_models_api", None)
        if low is not None and hasattr(low, "get_mental_model"):
            timeout = getattr(client, "_timeout", None)
            return await low.get_mental_model(bank_id, model_id, _request_timeout=timeout)
        return await asyncio.to_thread(self.embedded.mental_models.get, bank_id, model_id)

    async def _list_bank_memories(self, bank_id: str, *, limit: int, offset: int) -> list[Any]:
        client = _base_client(self.embedded)
        low = getattr(client, "_memory_api", None)
        if low is not None and hasattr(low, "list_memories"):
            timeout = getattr(client, "_timeout", None)
            out = await low.list_memories(
                bank_id,
                limit=int(limit),
                offset=int(offset),
                _request_timeout=timeout,
            )
            return list(getattr(out, "items", []) or [])
        listed = await asyncio.to_thread(
            self.embedded.memories.list,
            bank_id,
            None,
            None,
            int(limit),
            int(offset),
        )
        return list(getattr(listed, "items", []) or [])

    async def cortex_recall(
        self,
        query: str,
        kind: str,
        bank_id: str | None,
    ) -> list[Recollection]:
        """Recall used by `Cortex.hold` — no bank => no API round-trip."""

        if not bank_id or not query.strip():
            return []
        await self.ensure_bank(bank_id)
        mk: MemoryKind = kind  # type: ignore[assignment]
        try:
            out = await self.recall.recall(
                query,
                kinds=[mk],
                bank=bank_id,
                top_k=self.recall_top_k,
            )
            await self._append_raw_memory_event(
                bank_id=bank_id,
                event="recall",
                payload={
                    "query": query,
                    "kind": kind,
                    "results": [
                        {
                            "kind": r.kind,
                            "text": r.text,
                            "score": r.score,
                            "source": r.source,
                        }
                        for r in out
                    ],
                },
            )
            return out
        except Exception as exc:
            logger.warning("peer recall failed bank=%s: %s", bank_id, exc)
            await self._append_raw_memory_event(
                bank_id=bank_id,
                event="recall_error",
                payload={"query": query, "kind": kind, "error": f"{type(exc).__name__}: {exc}"},
            )
            return []

    async def retain_turn(
        self,
        stimulus: Stimulus,
        user: str,
        assistant: str,
        bank_id: str,
    ) -> None:
        """Append one episodic retain for the completed turn (best-effort)."""

        await self.ensure_bank(bank_id)
        text = f"User: {user}\nAssistant: {assistant}".strip()
        if not text:
            return
        st = Stimulus(
            channel=stimulus.channel,
            sender=stimulus.sender,
            text=text,
            received_at=stimulus.received_at,
        )
        try:
            await self.hippocampus.encode(st, kind="episodic", bank=bank_id)
            await self._append_raw_memory_event(
                bank_id=bank_id,
                event="retain",
                payload={
                    "channel": stimulus.channel,
                    "sender": stimulus.sender,
                    "user": user,
                    "assistant": assistant,
                    "raw_chunk": text,
                },
            )
        except Exception as exc:
            logger.warning("peer retain failed bank=%s: %s", bank_id, exc)
            await self._append_raw_memory_event(
                bank_id=bank_id,
                event="retain_error",
                payload={
                    "channel": stimulus.channel,
                    "sender": stimulus.sender,
                    "error": f"{type(exc).__name__}: {exc}",
                    "raw_chunk": text,
                },
            )

    async def aclose(self) -> None:
        """Best-effort async close for underlying client resources."""

        target = self.embedded
        close_async = getattr(target, "aclose", None)
        if callable(close_async):
            try:
                await close_async()
                return
            except Exception:
                pass
        close_sync = getattr(target, "close", None)
        if callable(close_sync):
            try:
                close_sync()
            except Exception:
                pass

    async def startup_healthcheck(self, *, probe_bank_id: str) -> tuple[bool, str]:
        """Run a lightweight read/write probe for peer-memory backend."""

        try:
            await self.ensure_bank(probe_bank_id)
            _ = await self.cortex_recall("healthcheck", "episodic", probe_bank_id)
            await self.embedded.aretain(
                bank_id=probe_bank_id,
                content="cortex peer-memory startup probe",
                tags=["cortex:healthcheck", "cortex:peer-memory"],
            )
            return True, f"peer-memory backend ok (bank={probe_bank_id})"
        except Exception as exc:
            return False, f"peer-memory backend unhealthy ({type(exc).__name__}: {exc})"

    async def _append_raw_memory_event(self, *, bank_id: str, event: str, payload: dict[str, Any]) -> None:
        if self.whatsapp_memory_raw_dir is None:
            return
        record = {
            "at": datetime.now(UTC).isoformat(),
            "event": event,
            "bank_id": bank_id,
            "payload": payload,
        }
        path = self.whatsapp_memory_raw_dir / f"{_safe_bank_filename(bank_id)}.jsonl"

        def _write() -> None:
            self.whatsapp_memory_raw_dir.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=True) + "\n")

        await asyncio.to_thread(_write)


def build_peer_memory_bridge(
    config: Any,
    *,
    cortex_profile: str,
    whatsapp_mental_models_dir: Path | None = None,
    whatsapp_memory_raw_dir: Path | None = None,
) -> PeerMemoryBridge | None:
    """Construct a bridge when ``memory.peer_banks_enabled`` is true.

    Returns ``None`` if the optional ``atulya`` package cannot be imported
    or construction fails (logged).
    """

    if not getattr(config.memory, "peer_banks_enabled", False):
        return None
    try:
        from atulya import AtulyaClient, AtulyaEmbedded
    except ImportError:
        logger.warning("peer banks: atulya package not importable; skipping")
        return None

    backend = (getattr(config.memory, "peer_banks_backend", "embedded") or "embedded").strip().lower()
    bank_fallback = getattr(config.memory, "bank_id", "atulya-cortex")
    try:
        if backend == "api":
            api_key_env = (getattr(config.memory, "api_key_env", "") or "").strip()
            api_key = os.environ.get(api_key_env, "") if api_key_env else ""
            emb = AtulyaClient(base_url=config.memory.api_url, api_key=api_key or None)
            logger.info("peer banks: using api backend at %s", config.memory.api_url)
        else:
            ep = (getattr(config.memory, "embed_profile", "") or "").strip()
            embed_profile = ep or cortex_profile
            emb = AtulyaEmbedded(profile=embed_profile)
            logger.info("peer banks: using embedded backend profile=%s", embed_profile)
        hip = Hippocampus(emb, default_bank=bank_fallback)
        rec = Recall(emb, default_bank=bank_fallback)
        return PeerMemoryBridge(
            embedded=emb,
            hippocampus=hip,
            recall=rec,
            recall_top_k=int(config.memory.recall_top_k),
            whatsapp_mental_models_dir=whatsapp_mental_models_dir,
            whatsapp_memory_raw_dir=whatsapp_memory_raw_dir,
        )
    except Exception as exc:
        logger.warning("peer banks: could not start embedded client: %s", exc)
        return None


__all__ = ["PeerMemoryBridge", "build_peer_memory_bridge"]


def _pick(obj: Any, key: str) -> str:
    if isinstance(obj, dict):
        value = obj.get(key, "")
    else:
        value = getattr(obj, key, "")
    if value is None:
        return ""
    return str(value).strip()


def _squash_whitespace(text: str) -> str:
    return " ".join(text.split())


def _usage_score(item: Any, *, rank_index: int) -> float:
    keys = (
        "usage_count",
        "uses",
        "access_count",
        "hit_count",
        "times_used",
        "importance",
        "score",
    )
    for key in keys:
        raw = _pick(item, key)
        if not raw:
            continue
        try:
            return float(raw)
        except Exception:
            continue
    # Fallback: preserve upstream ordering from API if no explicit usage field.
    return max(0.0, 1_000_000.0 - float(rank_index))


def _base_client(embedded: Any) -> Any:
    # AtulyaEmbedded exposes `.client`; plain Atulya/AtulyaClient is itself the base client.
    if hasattr(embedded, "client"):
        try:
            return embedded.client
        except Exception:
            return embedded
    return embedded


def _safe_bank_filename(bank_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in bank_id)[:160] or "bank"
