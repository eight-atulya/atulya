"""engine.py — adapters that let DSPy / TextGrad drive cortex.Language.

Both DSPy and TextGrad expect their own LM objects. Rather than forcing the
rest of the cortex to know about those APIs, we expose one adapter
(`LanguageEngine`) that wraps a `cortex.language.Language` and runs
arbitrary chat-completions calls synchronously.

- `LanguageEngine.complete(messages, ...)` returns a plain string.
- `build_dspy_lm(language, ...)` returns a `dspy.LM`-compatible object if
  `dspy-ai` is installed. When DSPy is missing we raise a clean
  `ImportError` with a remediation hint — callers decide whether to fall
  back to the local Compiler path.
- `build_textgrad_engine(language, ...)` is the symmetric adapter for
  TextGrad's `BlackboxLLM` / `engine.Engine` shape.

All three adapters share one worker: `LanguageEngine._call_sync` which
runs the Language coroutine on a fresh event loop when invoked from a
synchronous context, or on the current loop when already inside one
(via `asyncio.run_coroutine_threadsafe` on a dedicated thread).

Design rationale:
- Both DSPy and TextGrad are fundamentally synchronous. We give them a
  blocking call site without touching the cortex async loop.
- No environment-variable side effects: callers pass in a Language; we
  never read `OPENAI_API_KEY` here.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any, Iterable

# Imported lazily in build_* helpers so this module never hard-depends on
# dspy-ai or textgrad.


@dataclass
class _LoopThread:
    """One background thread hosting an asyncio loop, shared by all sync calls."""

    loop: asyncio.AbstractEventLoop
    thread: threading.Thread

    def submit(self, coro: Any) -> Any:
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return fut.result()

    def stop(self) -> None:
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2.0)


def _spawn_loop_thread() -> _LoopThread:
    loop = asyncio.new_event_loop()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=_run, name="plasticity-engine-loop", daemon=True)
    thread.start()
    return _LoopThread(loop=loop, thread=thread)


class LanguageEngine:
    """Synchronous façade over cortex.language.Language.

    Every call is converted from async to sync. Useful for DSPy/TextGrad,
    both of which are synchronous libraries.
    """

    def __init__(
        self,
        language: Any,
        *,
        provider: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> None:
        self._language = language
        self._provider = provider
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._loop: _LoopThread | None = None
        self._lock = threading.Lock()

    @property
    def provider(self) -> str | None:
        return self._provider

    @property
    def model(self) -> str | None:
        return self._model

    def _loop_or_start(self) -> _LoopThread:
        with self._lock:
            if self._loop is None:
                self._loop = _spawn_loop_thread()
            return self._loop

    def close(self) -> None:
        with self._lock:
            if self._loop is not None:
                self._loop.stop()
                self._loop = None

    def __enter__(self) -> "LanguageEngine":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> str:
        loop = self._loop_or_start()
        coro = self._language.think(
            messages,
            provider=provider or self._provider,
            model=model or self._model,
            temperature=self._temperature if temperature is None else temperature,
            max_tokens=self._max_tokens if max_tokens is None else max_tokens,
        )
        utterance = loop.submit(coro)
        return utterance.text or ""

    def __call__(
        self,
        prompt: str | list[dict[str, Any]],
        *,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **_: Any,
    ) -> str:
        """Duck-typed entry for libraries that pass a raw string prompt."""

        if isinstance(prompt, str):
            messages: list[dict[str, Any]] = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
        else:
            messages = list(prompt)
        return self.complete(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )


# ---------------------------------------------------------------------------
# Optional DSPy adapter
# ---------------------------------------------------------------------------


def build_dspy_lm(
    language: Any,
    *,
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 512,
) -> Any:
    """Return a `dspy.LM`-compatible object wrapping `language`.

    Raises `ImportError` if `dspy-ai` is not installed; callers should catch
    and fall back to the local bootstrap path.
    """

    try:
        import dspy  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised only with dspy present
        raise ImportError(
            "dspy-ai is not installed; run `uv pip install 'atulya-cortex[optimize]'` "
            "to enable the DSPy backend, or call Compiler.compile(..., backend='local')."
        ) from exc

    engine = LanguageEngine(
        language,
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    class _CortexDSPyLM(dspy.LM):  # type: ignore[misc,no-any-unimported]
        """dspy.LM subclass that routes every call through the cortex Language."""

        def __init__(self) -> None:
            super().__init__(model=model or "cortex-language")
            self._engine = engine

        def basic_request(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            text = self._engine(prompt, **kwargs)
            return {"choices": [{"text": text, "message": {"content": text}}]}

        def __call__(self, prompt: str, **kwargs: Any) -> list[str]:
            return [self._engine(prompt, **kwargs)]

    return _CortexDSPyLM()


# ---------------------------------------------------------------------------
# Optional TextGrad adapter
# ---------------------------------------------------------------------------


def build_textgrad_engine(
    language: Any,
    *,
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 512,
) -> Any:
    """Return a textgrad.engine.EngineLM-compatible object wrapping `language`.

    Raises `ImportError` if `textgrad` is not installed.
    """

    try:
        import textgrad  # type: ignore[import-not-found]  # noqa: F401
        from textgrad.engine import EngineLM  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised only with textgrad present
        raise ImportError(
            "textgrad is not installed; run `uv pip install 'atulya-cortex[textgrad]'` "
            "to enable the TextGrad backend, or call TextGradient.step(..., backend='local')."
        ) from exc

    engine = LanguageEngine(
        language,
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    class _CortexTextGradEngine(EngineLM):  # type: ignore[misc,no-any-unimported]
        def generate(self, content: str | Iterable[Any], system_prompt: str | None = None, **kwargs: Any) -> str:
            prompt = content if isinstance(content, str) else "\n".join(str(c) for c in content)
            return engine(prompt, system=system_prompt, **kwargs)

    return _CortexTextGradEngine()


__all__ = [
    "LanguageEngine",
    "build_dspy_lm",
    "build_textgrad_engine",
]
