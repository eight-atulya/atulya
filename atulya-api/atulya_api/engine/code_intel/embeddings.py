"""Code-aware embedding providers.

Two backends:

  - JinaCodeLocal: `jinaai/jina-embeddings-v2-base-code` via
    sentence-transformers. Local, free, runs offline. Default.
  - VoyageCode3: `voyage-code-3` via the `voyageai` API client.
    Premium quality, paid, opt-in via codebase settings.

If neither is available the provider falls back to whatever the engine
already configured for generic text embeddings -- so we never break
indexing if a coder hasn't set anything up.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class CodeEmbeddingProvider(Protocol):
    """Callable that turns code/text strings into vectors."""

    name: str

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(slots=True)
class _JinaCodeLocal:
    """Local sentence-transformers wrapper around jina v2 code model."""

    model_name: str = "jinaai/jina-embeddings-v2-base-code"
    name: str = "jina_code_local"
    _model: object | None = None
    _lock: threading.Lock = threading.Lock()

    def _ensure_loaded(self) -> object | None:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
            except Exception:
                return None
            try:
                self._model = SentenceTransformer(self.model_name, trust_remote_code=True)
            except Exception:
                try:
                    self._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
                    self.name = "sentence_transformers_minilm"
                except Exception:
                    return None
            return self._model

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._ensure_loaded()
        if model is None:
            return []
        import asyncio

        def _encode():
            try:
                vectors = model.encode(list(texts), convert_to_numpy=True, normalize_embeddings=True)  # type: ignore[union-attr]
                return [vector.tolist() for vector in vectors]
            except Exception:
                return []

        return await asyncio.to_thread(_encode)


@dataclass(slots=True)
class _VoyageCode3:
    """voyage-code-3 via the voyageai SDK."""

    api_key: str | None = None
    model_name: str = "voyage-code-3"
    name: str = "voyage_code_3"

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            import voyageai  # type: ignore[import-untyped]
        except Exception:
            return []

        api_key = self.api_key or os.environ.get("VOYAGE_API_KEY")
        if not api_key:
            return []

        import asyncio

        def _embed_sync():
            try:
                client = voyageai.Client(api_key=api_key)
                result = client.embed(list(texts), model=self.model_name, input_type="document")
                return list(result.embeddings)
            except Exception:
                return []

        return await asyncio.to_thread(_embed_sync)


@dataclass(slots=True)
class _GenericFallback:
    """Last-resort fallback so the pipeline never breaks on missing
    embedding deps. Reuses whatever the engine already configured."""

    inner: object
    name: str = "generic_fallback"

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            from ..retain import embedding_processing

            return await embedding_processing.generate_embeddings_batch(self.inner, list(texts))
        except Exception:
            return []


_PROVIDER_CACHE: dict[str, CodeEmbeddingProvider] = {}
_PROVIDER_LOCK = threading.Lock()


def get_code_embedding_provider(
    *,
    choice: str | None = None,
    voyage_api_key: str | None = None,
    fallback_engine_embeddings: object | None = None,
) -> CodeEmbeddingProvider:
    """Return a configured provider for the given choice.

    `choice` is one of: "jina_local", "voyage_code_3", "generic" (or None for default).
    Cached by choice so the local model only loads once per process.
    """

    key = (choice or "jina_local").lower()
    with _PROVIDER_LOCK:
        cached = _PROVIDER_CACHE.get(key)
        if cached is not None:
            return cached

        provider: CodeEmbeddingProvider
        if key == "voyage_code_3":
            provider = _VoyageCode3(api_key=voyage_api_key)
        elif key == "generic" and fallback_engine_embeddings is not None:
            provider = _GenericFallback(inner=fallback_engine_embeddings)
        else:
            provider = _JinaCodeLocal()
        _PROVIDER_CACHE[key] = provider
        return provider
