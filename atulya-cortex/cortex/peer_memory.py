"""peer_memory.py — atulya-embed bank per (cortex profile, peer).

Wires `memory.Hippocampus` + `memory.Recall` with one bank id per remote
contact. Creation is lazy: first interaction calls `acreate_bank` once,
then retains and recalls against that bank.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from cortex.bus import MemoryKind, Recollection, Stimulus
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
    _ensured: set[str] = field(default_factory=set)

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
            return await self.recall.recall(
                query,
                kinds=[mk],
                bank=bank_id,
                top_k=self.recall_top_k,
            )
        except Exception as exc:
            logger.warning("peer recall failed bank=%s: %s", bank_id, exc)
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
        except Exception as exc:
            logger.warning("peer retain failed bank=%s: %s", bank_id, exc)


def build_peer_memory_bridge(config: Any, *, cortex_profile: str) -> PeerMemoryBridge | None:
    """Construct a bridge when ``memory.peer_banks_enabled`` is true.

    Returns ``None`` if the optional ``atulya`` package cannot be imported
    or construction fails (logged).
    """

    if not getattr(config.memory, "peer_banks_enabled", False):
        return None
    try:
        from atulya import AtulyaEmbedded
    except ImportError:
        logger.warning("peer banks: atulya package not importable; skipping")
        return None

    ep = (getattr(config.memory, "embed_profile", "") or "").strip()
    embed_profile = ep or cortex_profile
    bank_fallback = getattr(config.memory, "bank_id", "atulya-cortex")
    try:
        emb = AtulyaEmbedded(profile=embed_profile)
        hip = Hippocampus(emb, default_bank=bank_fallback)
        rec = Recall(emb, default_bank=bank_fallback)
        return PeerMemoryBridge(
            embedded=emb,
            hippocampus=hip,
            recall=rec,
            recall_top_k=int(config.memory.recall_top_k),
        )
    except Exception as exc:
        logger.warning("peer banks: could not start embedded client: %s", exc)
        return None


__all__ = ["PeerMemoryBridge", "build_peer_memory_bridge"]
