"""semantic.py — thin router that pins kind="semantic" on Hippocampus / Recall.

Semantic memory is the brain's record of *general facts about the world*.
Maps to atulya substrate's `world` type and the cortex tag
`cortex:kind:semantic`.
"""

from __future__ import annotations

from typing import Any

from cortex.bus import Budget, Recollection, Stimulus
from memory.hippocampus import Hippocampus
from memory.recall import Recall


class SemanticMemory:
    """Adapter that always speaks "semantic" to the underlying organs."""

    def __init__(self, hippocampus: Hippocampus, recall: Recall) -> None:
        self._hippocampus = hippocampus
        self._recall = recall

    async def remember(
        self,
        stimulus: Stimulus,
        *,
        bank: str | None = None,
        extra_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        return await self._hippocampus.encode(stimulus, kind="semantic", bank=bank, extra_tags=extra_tags)

    async def remember_text(
        self,
        text: str,
        *,
        bank: str | None = None,
        extra_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        return await self._hippocampus.encode_text(text, kind="semantic", bank=bank, extra_tags=extra_tags)

    async def recall_about(
        self,
        query: str,
        *,
        budget: Budget = "mid",
        bank: str | None = None,
        top_k: int | None = None,
    ) -> list[Recollection]:
        return await self._recall.recall(query, budget=budget, kinds=["semantic"], bank=bank, top_k=top_k)


__all__ = ["SemanticMemory"]
