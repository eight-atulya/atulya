"""coherence.py — KV / prefix cache reuse.

Coherence is what keeps the same prompt cheap on the second call. Two layers:

1. **Local LLM cache** (`silo/llm_cache.py`): when the *full* request matches
   a previous one, return the cached `Utterance` and skip the network round
   trip entirely. This is the dominant TTFT win for local LLMs.

2. **Prefix tracking**: hash the system prompt and report a stable
   `prefix_id` per (provider, model). Providers that support prompt caching
   (Anthropic `prompt_cache_control`, DeepSeek prefix cache, vLLM
   `prefix_cache`) can use this id to attach the right header / extra_body.
   For LM Studio and Ollama, the model server's KV cache reuses prefixes
   automatically when the system prompt is byte-identical, so we just emit
   the same bytes.

`Coherence.think(...)` is a drop-in wrapper around `Language.think(...)`
that adds caching transparently.

Naming voice: `Coherence.think` mirrors `Language.think`. The verb stays
the same; the implementation changes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from cortex.language import Language, Utterance


@dataclass
class CoherenceStats:
    """Hit/miss counters useful for benchmarks."""

    hits: int = 0
    misses: int = 0
    bytes_saved: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


def prefix_id_for(messages: list[dict[str, Any]]) -> str:
    """Stable id for the *system prompt prefix* of a chat request.

    Two requests sharing the same id can share a model-side KV cache.
    """

    sys_messages = [m for m in messages if m.get("role") == "system"]
    blob = json.dumps(sys_messages, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.blake2b(blob, digest_size=16).hexdigest()


class Coherence:
    """Caching wrapper around `Language`."""

    def __init__(self, language: Language, llm_cache: Any) -> None:
        self._language = language
        self._cache = llm_cache
        self.stats = CoherenceStats()

    @property
    def providers(self) -> list[str]:
        return self._language.providers

    async def think(
        self,
        messages: list[dict[str, Any]],
        *,
        provider: str | None = None,
        model: str | None = None,
        disposition: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> Utterance:
        chosen_provider = provider or self._language._resolve_disposition(disposition) or self._language.providers[0]
        provider_obj = self._language.get_provider(chosen_provider)
        chosen_model = model or provider_obj.default_model

        cached = self._cache.recall(
            provider=chosen_provider,
            model=chosen_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra=extra_body,
        )
        if cached is not None:
            self.stats.hits += 1
            self.stats.bytes_saved += len(cached.text.encode("utf-8"))
            return cached

        utt = await self._language.think(
            messages,
            provider=chosen_provider,
            model=chosen_model,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )
        self.stats.misses += 1
        self._cache.remember(
            utt,
            provider=chosen_provider,
            model=chosen_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra=extra_body,
        )
        return utt


__all__ = ["Coherence", "CoherenceStats", "prefix_id_for"]
