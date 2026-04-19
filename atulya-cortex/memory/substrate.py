"""substrate.py — the composite MemoryStore implementation backed by atulya-embed.

`AtulyaSubstrate` satisfies the `MemoryStore` Protocol declared in
`memory/__init__.py`. It bundles a `Hippocampus` (encode), a `Recall`
(retrieve), and an `EmotionalMemory` (disposition) onto one object the
Cortex can hold. The typed routers (`EpisodicMemory`, `SemanticMemory`,
`ProceduralMemory`) are exposed as properties so callers can write
`brain.memory.episodic.remember(...)`.

This module is the canonical wiring between cortex and atulya-embed. New
features that need durable memory should call into this object, not into
atulya-embed directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from cortex.bus import Disposition, MemoryKind, Recollection, Stimulus
from memory.emotional import EmotionalMemory
from memory.episodic import EpisodicMemory
from memory.hippocampus import DEFAULT_BANK, Hippocampus
from memory.procedural import ProceduralMemory
from memory.recall import Recall
from memory.semantic import SemanticMemory

if TYPE_CHECKING:  # pragma: no cover - typing only
    from atulya import AtulyaEmbedded


class AtulyaSubstrate:
    """Composite memory facade — implements the `MemoryStore` Protocol."""

    def __init__(self, embedded: "AtulyaEmbedded", *, default_bank: str = DEFAULT_BANK) -> None:
        self._embedded = embedded
        self._default_bank = default_bank
        self._hippocampus = Hippocampus(embedded, default_bank=default_bank)
        self._recall = Recall(embedded, default_bank=default_bank)
        self._emotional = EmotionalMemory(embedded)
        self._episodic = EpisodicMemory(self._hippocampus, self._recall)
        self._semantic = SemanticMemory(self._hippocampus, self._recall)
        self._procedural = ProceduralMemory(self._hippocampus, self._recall)

    # ---- core MemoryStore Protocol -----------------------------------------

    async def encode(
        self,
        stimulus: Stimulus,
        *,
        kind: MemoryKind,
        bank: str | None = None,
    ) -> dict:
        return await self._hippocampus.encode(stimulus, kind=kind, bank=bank)

    async def recall(
        self,
        query: str,
        *,
        budget: str = "mid",
        kinds: Sequence[MemoryKind] | None = None,
        bank: str | None = None,
    ) -> list[Recollection]:
        return await self._recall.recall(query, budget=budget, kinds=kinds, bank=bank)

    async def disposition_for(self, bank: str) -> Disposition:
        return await self._emotional.disposition_for(bank)

    # ---- typed router properties -------------------------------------------

    @property
    def hippocampus(self) -> Hippocampus:
        return self._hippocampus

    @property
    def episodic(self) -> EpisodicMemory:
        return self._episodic

    @property
    def semantic(self) -> SemanticMemory:
        return self._semantic

    @property
    def procedural(self) -> ProceduralMemory:
        return self._procedural

    @property
    def emotional(self) -> EmotionalMemory:
        return self._emotional

    @property
    def default_bank(self) -> str:
        return self._default_bank


__all__ = ["AtulyaSubstrate"]
