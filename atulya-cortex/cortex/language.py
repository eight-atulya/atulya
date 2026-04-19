"""language.py — the multi-provider LLM driver.

`Language` wraps any OpenAI-compatible chat-completions endpoint. The same
class drives:

- **LM Studio** (default for local development; `http://localhost:1234/v1`)
- **Ollama**    (`http://localhost:11434/v1`, model name = ollama tag)
- **vLLM**      (`http://localhost:8000/v1`)
- **OpenAI**    (api.openai.com)
- **Anthropic** (via the OpenAI-compatible endpoint at `/v1/openai/v1`)
- **Groq**, **Together**, **Fireworks**, **Cerebras**, **Mistral**,
  **Perplexity**, **DeepSeek**, **OpenRouter**, **xAI**, **Google AI Studio**
  (every commercial provider that exposes the OpenAI schema)

A `Language` is constructed with one or more `Provider`s; the first is the
default, the rest are fallbacks tried in order on failure. Per-call you may
override the provider with `provider=<name>` and the model with
`model=<id>`.

`Disposition`-aware routing: pass `disposition="careful"` to prefer the
slower/larger provider, or `disposition="snappy"` for the fastest. The
disposition map is constructor-supplied so behavior stays declarative.

Naming voice: `Language.think` is the load-bearing verb. The class is named
`Language` because that is what the cortex *uses* to decide.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

import httpx

DEFAULT_LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
DEFAULT_LM_STUDIO_MODEL = "google/gemma-3-4b"


@dataclass
class Provider:
    """One OpenAI-compatible chat endpoint."""

    name: str
    base_url: str
    api_key: str = ""
    default_model: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 120.0
    max_retries: int = 1

    @classmethod
    def lm_studio(
        cls,
        *,
        base_url: str = DEFAULT_LM_STUDIO_BASE_URL,
        model: str = DEFAULT_LM_STUDIO_MODEL,
    ) -> "Provider":
        return cls(name="lm-studio", base_url=base_url, api_key="lm-studio", default_model=model)

    @classmethod
    def ollama(
        cls,
        *,
        base_url: str = "http://localhost:11434/v1",
        model: str = "gemma3:4b",
    ) -> "Provider":
        return cls(name="ollama", base_url=base_url, api_key="ollama", default_model=model)

    @classmethod
    def vllm(
        cls,
        *,
        base_url: str = "http://localhost:8000/v1",
        model: str = "google/gemma-3-4b-it",
    ) -> "Provider":
        return cls(name="vllm", base_url=base_url, api_key="not-needed", default_model=model)

    @classmethod
    def openai(cls, *, api_key: str | None = None, model: str = "gpt-4o-mini") -> "Provider":
        return cls(
            name="openai",
            base_url="https://api.openai.com/v1",
            api_key=api_key or os.environ.get("OPENAI_API_KEY", ""),
            default_model=model,
        )

    @classmethod
    def anthropic(cls, *, api_key: str | None = None, model: str = "claude-3-5-sonnet-latest") -> "Provider":
        return cls(
            name="anthropic",
            base_url="https://api.anthropic.com/v1",
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
            default_model=model,
            headers={"anthropic-version": "2023-06-01"},
        )

    @classmethod
    def groq(cls, *, api_key: str | None = None, model: str = "llama-3.1-8b-instant") -> "Provider":
        return cls(
            name="groq",
            base_url="https://api.groq.com/openai/v1",
            api_key=api_key or os.environ.get("GROQ_API_KEY", ""),
            default_model=model,
        )

    @classmethod
    def together(cls, *, api_key: str | None = None, model: str = "google/gemma-2-9b-it") -> "Provider":
        return cls(
            name="together",
            base_url="https://api.together.xyz/v1",
            api_key=api_key or os.environ.get("TOGETHER_API_KEY", ""),
            default_model=model,
        )

    @classmethod
    def deepseek(cls, *, api_key: str | None = None, model: str = "deepseek-chat") -> "Provider":
        return cls(
            name="deepseek",
            base_url="https://api.deepseek.com/v1",
            api_key=api_key or os.environ.get("DEEPSEEK_API_KEY", ""),
            default_model=model,
        )

    @classmethod
    def openrouter(cls, *, api_key: str | None = None, model: str = "google/gemma-3-4b-it") -> "Provider":
        return cls(
            name="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key or os.environ.get("OPENROUTER_API_KEY", ""),
            default_model=model,
        )


@dataclass
class Utterance:
    """One LLM turn (output of `Language.think`)."""

    text: str
    provider: str
    model: str
    elapsed_ms: float
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


class LanguageError(RuntimeError):
    """Raised when every provider in the fallback chain has failed."""


class Language:
    """Multi-provider LLM driver."""

    def __init__(
        self,
        providers: Iterable[Provider],
        *,
        disposition_map: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._providers: dict[str, Provider] = {}
        self._order: list[str] = []
        for p in providers:
            if p.name in self._providers:
                continue
            self._providers[p.name] = p
            self._order.append(p.name)
        if not self._providers:
            raise ValueError("Language requires at least one Provider")
        self._disposition_map = dict(disposition_map or {})
        self._client = client
        self._owned_client = client is None

    @classmethod
    def with_lm_studio(cls) -> "Language":
        """Sane local default: just LM Studio at port 1234 with gemma-3-4b."""

        return cls([Provider.lm_studio()])

    @property
    def providers(self) -> list[str]:
        return list(self._order)

    def get_provider(self, name: str | None) -> Provider:
        if name is None:
            return self._providers[self._order[0]]
        if name not in self._providers:
            raise KeyError(f"unknown provider {name!r}; known={self.providers}")
        return self._providers[name]

    async def aclose(self) -> None:
        if self._owned_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _client_or_raise(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    def _resolve_disposition(self, disposition: str | None) -> str | None:
        if disposition is None:
            return None
        return self._disposition_map.get(disposition)

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
        """Send a chat-completions request; return one Utterance.

        Order of provider resolution:
          1. explicit `provider=` arg
          2. `disposition_map[disposition]`
          3. fallback chain in declaration order
        """

        if provider is None:
            provider = self._resolve_disposition(disposition)

        chain: list[str]
        if provider is not None:
            chain = [provider] + [n for n in self._order if n != provider]
        else:
            chain = list(self._order)

        last_error: Exception | None = None
        for name in chain:
            p = self._providers[name]
            mdl = model or p.default_model
            if not mdl:
                last_error = LanguageError(f"provider {name!r} has no model and none was passed")
                continue
            try:
                return await self._call_provider(
                    p,
                    model=mdl,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    extra_body=extra_body,
                )
            except Exception as exc:
                last_error = exc
                continue

        raise LanguageError(f"all providers failed: {last_error}") from last_error

    async def _call_provider(
        self,
        provider: Provider,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None,
        extra_body: dict[str, Any] | None,
    ) -> Utterance:
        url = f"{provider.base_url.rstrip('/')}/chat/completions"
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if extra_body:
            body.update(extra_body)
        headers = {"Content-Type": "application/json"}
        if provider.api_key:
            headers["Authorization"] = f"Bearer {provider.api_key}"
        headers.update(provider.headers)

        client = self._client_or_raise()
        attempt = 0
        last_error: Exception | None = None
        while attempt <= provider.max_retries:
            attempt += 1
            started = time.monotonic()
            try:
                resp = await client.post(url, headers=headers, json=body, timeout=provider.timeout_s)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                continue
            elapsed_ms = (time.monotonic() - started) * 1000.0
            if resp.status_code >= 400:
                last_error = LanguageError(f"{provider.name} HTTP {resp.status_code}: {resp.text[:200]}")
                if 500 <= resp.status_code < 600 and attempt <= provider.max_retries:
                    continue
                raise last_error
            data = resp.json()
            try:
                choice = data["choices"][0]
                text = choice["message"]["content"] or ""
            except (KeyError, IndexError) as exc:
                raise LanguageError(f"{provider.name} returned unexpected payload: {data!r}") from exc
            return Utterance(
                text=text,
                provider=provider.name,
                model=model,
                elapsed_ms=elapsed_ms,
                usage=data.get("usage", {}) or {},
                raw=data,
            )

        raise last_error or LanguageError(f"{provider.name}: no attempts succeeded")


__all__ = [
    "DEFAULT_LM_STUDIO_BASE_URL",
    "DEFAULT_LM_STUDIO_MODEL",
    "Language",
    "LanguageError",
    "Provider",
    "Utterance",
]
