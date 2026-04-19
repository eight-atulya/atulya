"""quantum — speculative compute.

Four organs:
- `coherence.py`     — KV / prefix cache reuse
- `entanglement.py`  — background recall prefetch
- `superposition.py` — speculative execution of idempotent tools
- `decoherence.py`   — clean rollback when speculation is wrong
"""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol, runtime_checkable


@runtime_checkable
class Speculative(Protocol):
    """Anything that can run a piece of work speculatively and roll it back."""

    async def speculate(self, work: Callable[[], Awaitable]) -> "SpeculationHandle": ...

    async def commit(self, handle: "SpeculationHandle") -> None: ...

    async def rollback(self, handle: "SpeculationHandle") -> None: ...


class SpeculationHandle:
    """Opaque receipt for a speculation. Concrete fields land with `superposition.py`."""

    def __init__(self, key: str) -> None:
        self.key = key


from quantum.coherence import Coherence, CoherenceStats, prefix_id_for  # noqa: E402
from quantum.decoherence import Decoherence  # noqa: E402
from quantum.entanglement import Entanglement  # noqa: E402
from quantum.superposition import (  # noqa: E402
    SAFE_IDEMPOTENT_TOOLS,
    Speculation,
    SpeculationDenied,
    Superposition,
)

__all__ = [
    "Coherence",
    "CoherenceStats",
    "Decoherence",
    "Entanglement",
    "SAFE_IDEMPOTENT_TOOLS",
    "Speculation",
    "SpeculationDenied",
    "SpeculationHandle",
    "Speculative",
    "Superposition",
    "prefix_id_for",
]
