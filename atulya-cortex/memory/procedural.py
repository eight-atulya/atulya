"""procedural.py — thin router that pins kind="procedural" on Hippocampus / Recall.

Procedural memory is *how to do things* — skills, workflows, sequences.
Atulya does not have a native substrate type for this; we rely on the
cortex tag `cortex:kind:procedural` for filtering. Lessons distilled by
`dream/skill_distill.py` are written as procedural memories.
"""

from __future__ import annotations

from typing import Any

from cortex.bus import Budget, Recollection, Stimulus
from memory.hippocampus import Hippocampus
from memory.recall import Recall


class ProceduralMemory:
    """Adapter that always speaks "procedural" to the underlying organs."""

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
        return await self._hippocampus.encode(stimulus, kind="procedural", bank=bank, extra_tags=extra_tags)

    async def remember_skill(
        self,
        skill_name: str,
        body_text: str,
        *,
        bank: str | None = None,
    ) -> dict[str, Any]:
        return await self._hippocampus.encode_text(
            body_text,
            kind="procedural",
            bank=bank,
            extra_tags=[f"cortex:skill:{skill_name}"],
        )

    async def recall_about(
        self,
        query: str,
        *,
        budget: Budget = "mid",
        bank: str | None = None,
        top_k: int | None = None,
    ) -> list[Recollection]:
        return await self._recall.recall(query, budget=budget, kinds=["procedural"], bank=bank, top_k=top_k)


__all__ = ["ProceduralMemory"]
