"""episodic.py — thin router that pins kind="episodic" on Hippocampus / Recall.

Episodic memory is the brain's record of *what happened*. It maps to atulya
substrate's `experience` type and the cortex tag `cortex:kind:episodic`.
"""

from __future__ import annotations

from typing import Any

from cortex.bus import Budget, Recollection, Stimulus
from memory.hippocampus import Hippocampus
from memory.recall import Recall


class EpisodicMemory:
    """Adapter that always speaks "episodic" to the underlying organs."""

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
        return await self._hippocampus.encode(stimulus, kind="episodic", bank=bank, extra_tags=extra_tags)

    async def recall_about(
        self,
        query: str,
        *,
        budget: Budget = "mid",
        bank: str | None = None,
        top_k: int | None = None,
    ) -> list[Recollection]:
        return await self._recall.recall(query, budget=budget, kinds=["episodic"], bank=bank, top_k=top_k)


__all__ = ["EpisodicMemory"]
