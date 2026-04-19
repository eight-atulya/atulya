"""silo — cache and durable per-bank state.

Three concrete silos:
- `silo/llm_cache.py`       — completion cache.
- `silo/embedding_cache.py` — embedding cache.
- `silo/state.py`           — durable JSON KV state.

The package declares the `Silo` Protocol and re-exports the concrete silos.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Silo(Protocol):
    """Generic cache surface. Backends include diskcache and sqlite."""

    def get(self, key: str) -> Any | None: ...

    def put(self, key: str, value: Any, *, ttl: float | None = None) -> None: ...

    def evict(self, key: str) -> None: ...


from silo.embedding_cache import EmbeddingCache  # noqa: E402
from silo.llm_cache import LLMCache  # noqa: E402
from silo.state import StateStore  # noqa: E402

__all__ = ["EmbeddingCache", "LLMCache", "Silo", "StateStore"]
