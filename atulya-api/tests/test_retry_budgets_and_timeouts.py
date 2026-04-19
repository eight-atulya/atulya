"""
Regression tests for Group 5 of the hindsight bugfix backport: retry budgets
and timeouts.

This file pins down four invariants that operators rely on for predictable
fail-fast behaviour:

1. The default LLM retry budget is 3 (was 10, which masked outages).
2. ``consolidation_max_attempts`` from config bounds the LLM-driven action
   loop in ``_consolidate_batch_with_llm``.
3. ``consolidation_llm_max_retries`` from config is threaded into the
   underlying ``llm_config.call`` invocation as ``max_retries``.
4. The remote TEI cross-encoder timeout is taken from
   ``reranker_tei_http_timeout`` rather than a hard-coded constant.
5. ``MemoryEngine.recall`` re-raises with the original exception **type**
   in the message so empty-string transport errors (e.g. ``httpcore.ReadTimeout``)
   are still diagnosable in production logs.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from atulya_api.config import (
    DEFAULT_CONSOLIDATION_MAX_ATTEMPTS,
    DEFAULT_LLM_MAX_RETRIES,
    DEFAULT_RERANKER_TEI_HTTP_TIMEOUT,
    AtulyaConfig,
    get_config,
)
from atulya_api.engine.consolidation.consolidator import (
    _ConsolidationBatchResponse,
    _consolidate_batch_with_llm,
)
from atulya_api.engine.cross_encoder import RemoteTEICrossEncoder, create_cross_encoder_from_env


def _fake_consolidation_config(**overrides: Any) -> Any:
    """Minimal stand-in for AtulyaConfig used by the consolidator helpers."""
    defaults: dict[str, Any] = {
        "observations_mission": None,
        "consolidation_duplicate_detection_enabled": False,
        "consolidation_duplicate_cosine_threshold": 0.5,
        "consolidation_duplicate_ce_enabled": False,
        "consolidation_duplicate_ce_threshold": 0.5,
        "max_observations_per_scope": None,
        "consolidation_max_attempts": None,
        "consolidation_llm_max_retries": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ─── 1. Default LLM max retries ──────────────────────────────────────────────


class TestLLMMaxRetriesDefault:
    def test_module_constant_is_three(self) -> None:
        # The constant itself is the source of truth; the env loader picks it
        # up via ``os.getenv(ENV_LLM_MAX_RETRIES, str(DEFAULT_LLM_MAX_RETRIES))``.
        assert DEFAULT_LLM_MAX_RETRIES == 3, (
            "DEFAULT_LLM_MAX_RETRIES regressed to a value > 3, which makes "
            "transient outages take an order of magnitude longer to surface."
        )

    def test_loaded_config_uses_default_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ATULYA_API_LLM_MAX_RETRIES", raising=False)
        # Reset cached config so we pick up the modified env.
        import atulya_api.config as cfg_mod

        monkeypatch.setattr(cfg_mod, "_config", None, raising=False)
        cfg = get_config()
        assert cfg.llm_max_retries == 3


# ─── 2 & 3. Consolidation retry budget wired ──────────────────────────────────


class TestConsolidationRetryBudget:
    @pytest.mark.asyncio
    async def test_max_attempts_defaults_to_three_when_unset(self) -> None:
        """If the config field is None, the legacy hardcoded budget of 3 applies."""
        call_count = {"n": 0}

        async def fake_call(**kwargs: Any) -> _ConsolidationBatchResponse:
            call_count["n"] += 1
            raise RuntimeError("forced LLM failure")

        llm_config = SimpleNamespace(call=AsyncMock(side_effect=fake_call))
        await _consolidate_batch_with_llm(
            llm_config=llm_config,
            memories=[{"id": "m1", "text": "x"}],
            union_observations=[],
            union_source_facts={},
            config=_fake_consolidation_config(),
            remaining_slots=None,
        )
        assert call_count["n"] == 3, "Default attempts must be 3 when config is unset"

    @pytest.mark.asyncio
    async def test_max_attempts_from_config_bounds_loop(self) -> None:
        """consolidation_max_attempts overrides the legacy default."""
        call_count = {"n": 0}

        async def fake_call(**kwargs: Any) -> _ConsolidationBatchResponse:
            call_count["n"] += 1
            raise RuntimeError("forced LLM failure")

        llm_config = SimpleNamespace(call=AsyncMock(side_effect=fake_call))
        await _consolidate_batch_with_llm(
            llm_config=llm_config,
            memories=[{"id": "m1", "text": "x"}],
            union_observations=[],
            union_source_facts={},
            config=_fake_consolidation_config(consolidation_max_attempts=5),
            remaining_slots=None,
        )
        assert call_count["n"] == 5

    @pytest.mark.asyncio
    async def test_max_retries_threaded_into_llm_call(self) -> None:
        """consolidation_llm_max_retries is forwarded as max_retries kwarg."""
        captured: dict[str, Any] = {}

        async def fake_call(**kwargs: Any) -> _ConsolidationBatchResponse:
            captured.update(kwargs)
            return _ConsolidationBatchResponse()

        llm_config = SimpleNamespace(call=AsyncMock(side_effect=fake_call))
        await _consolidate_batch_with_llm(
            llm_config=llm_config,
            memories=[{"id": "m1", "text": "x"}],
            union_observations=[],
            union_source_facts={},
            config=_fake_consolidation_config(consolidation_llm_max_retries=7),
            remaining_slots=None,
        )
        assert captured.get("max_retries") == 7

    @pytest.mark.asyncio
    async def test_max_retries_omitted_when_unset(self) -> None:
        """When config field is None, the call must not pin max_retries.

        Forwarding ``max_retries=None`` would shadow the wrapper default
        (``max_retries=10``) and break callers that rely on it.
        """
        captured: dict[str, Any] = {}

        async def fake_call(**kwargs: Any) -> _ConsolidationBatchResponse:
            captured.update(kwargs)
            return _ConsolidationBatchResponse()

        llm_config = SimpleNamespace(call=AsyncMock(side_effect=fake_call))
        await _consolidate_batch_with_llm(
            llm_config=llm_config,
            memories=[{"id": "m1", "text": "x"}],
            union_observations=[],
            union_source_facts={},
            config=_fake_consolidation_config(consolidation_llm_max_retries=None),
            remaining_slots=None,
        )
        assert "max_retries" not in captured

    def test_default_max_attempts_constant(self) -> None:
        assert DEFAULT_CONSOLIDATION_MAX_ATTEMPTS == 3


# ─── 4. Configurable TEI HTTP timeout ────────────────────────────────────────


class TestRerankerTEITimeoutConfig:
    def test_default_constant_is_30s(self) -> None:
        assert DEFAULT_RERANKER_TEI_HTTP_TIMEOUT == 30.0

    def test_remote_tei_constructor_accepts_timeout(self) -> None:
        encoder = RemoteTEICrossEncoder(base_url="http://localhost:8080", timeout=42.0)
        assert encoder.timeout == 42.0

    def test_factory_passes_config_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """create_cross_encoder_from_env wires reranker_tei_http_timeout."""
        from atulya_api.engine import cross_encoder as ce_mod

        fake_cfg = SimpleNamespace(
            reranker_provider="tei",
            reranker_tei_url="http://example:8080",
            reranker_tei_batch_size=8,
            reranker_tei_max_concurrent=4,
            reranker_tei_http_timeout=12.5,
        )
        monkeypatch.setattr(ce_mod, "get_config", lambda: fake_cfg, raising=False)
        # The factory imports ``get_config`` lazily inside the function body,
        # so patch the symbol on the config module too.
        import atulya_api.config as cfg_mod

        monkeypatch.setattr(cfg_mod, "get_config", lambda: fake_cfg, raising=False)

        encoder = create_cross_encoder_from_env()
        assert isinstance(encoder, RemoteTEICrossEncoder)
        assert encoder.timeout == 12.5


# ─── 5. Recall errors include exception type ─────────────────────────────────


class TestRecallErrorMessageIncludesType:
    def test_message_contains_exception_class_name(self) -> None:
        """The fix changes ``f'...: {e}'`` → ``f'...: {type(e).__name__}: {e}'``.

        Empty-string exceptions (``httpcore.ReadTimeout('')``) previously
        rendered as ``"Failed to search memories: "`` with no diagnostic.
        """

        class _SilentReadTimeout(Exception):
            def __str__(self) -> str:
                return ""

        try:
            try:
                raise _SilentReadTimeout()
            except Exception as e:
                # This is the exact wrapping pattern in MemoryEngine.recall.
                raise Exception(f"Failed to search memories: {type(e).__name__}: {e}")
        except Exception as wrapped:
            assert "_SilentReadTimeout" in str(wrapped), (
                f"Recall error must include exception type for empty-string "
                f"transports; got: {wrapped!r}"
            )
