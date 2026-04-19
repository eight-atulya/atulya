"""memory — the substrate, via atulya-embed.

Public surface:
- `MemoryStore`        — Protocol every memory facade satisfies.
- `AtulyaSubstrate`    — production wiring against atulya-embed.
- `InMemorySubstrate`  — fast in-process implementation for tests / CI.
- `Hippocampus`        — encoder organ.
- `Recall`             — retrieval organ.
- `WorkingMemory`      — in-process LRU + conversation buffer.
- `EpisodicMemory` / `SemanticMemory` / `ProceduralMemory` — typed routers.
- `EmotionalMemory`    — disposition reader.
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from cortex.bus import Disposition, MemoryKind, Recollection, Stimulus

RetainReceipt = dict


@runtime_checkable
class MemoryStore(Protocol):
    """Contract for the durable memory substrate."""

    async def encode(
        self,
        stimulus: Stimulus,
        *,
        kind: MemoryKind,
        bank: str | None = None,
    ) -> RetainReceipt: ...

    async def recall(
        self,
        query: str,
        *,
        budget: str = "mid",
        kinds: Sequence[MemoryKind] | None = None,
        bank: str | None = None,
    ) -> list[Recollection]: ...

    async def disposition_for(self, bank: str) -> Disposition: ...


# Concrete implementations are imported lazily inside callers' modules to keep
# the package import cheap. Re-exports below are the documented public surface.
from memory.emotional import EmotionalMemory  # noqa: E402
from memory.episodic import EpisodicMemory  # noqa: E402
from memory.hippocampus import (  # noqa: E402
    CORTEX_CHANNEL_TAG_PREFIX,
    CORTEX_KIND_TAG_PREFIX,
    CORTEX_SENDER_TAG_PREFIX,
    DEFAULT_BANK,
    Hippocampus,
    channel_tag,
    kind_tag,
    sender_tag,
)
from memory.in_memory import InMemorySubstrate  # noqa: E402
from memory.procedural import ProceduralMemory  # noqa: E402
from memory.recall import Recall  # noqa: E402
from memory.semantic import SemanticMemory  # noqa: E402
from memory.substrate import AtulyaSubstrate  # noqa: E402
from memory.working_memory import (  # noqa: E402
    DEFAULT_LRU_CAPACITY,
    DEFAULT_TURN_BUFFER,
    WorkingMemory,
)

__all__ = [
    "AtulyaSubstrate",
    "CORTEX_CHANNEL_TAG_PREFIX",
    "CORTEX_KIND_TAG_PREFIX",
    "CORTEX_SENDER_TAG_PREFIX",
    "DEFAULT_BANK",
    "DEFAULT_LRU_CAPACITY",
    "DEFAULT_TURN_BUFFER",
    "EmotionalMemory",
    "EpisodicMemory",
    "Hippocampus",
    "InMemorySubstrate",
    "MemoryStore",
    "ProceduralMemory",
    "Recall",
    "RetainReceipt",
    "SemanticMemory",
    "WorkingMemory",
    "channel_tag",
    "kind_tag",
    "sender_tag",
]
