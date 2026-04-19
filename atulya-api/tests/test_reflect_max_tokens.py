"""
Regression tests for Group 6 of the hindsight bugfix backport: ``max_tokens``
must be honoured end-to-end through reflect.

Three independent invariants are pinned down here:

1. The Gemini provider forwards ``max_completion_tokens`` to its
   ``GenerateContentConfig.max_output_tokens`` field — previously it was
   silently dropped, so requests claiming a cap got whatever Gemini's default
   was.

2. ``run_reflect_agent`` short-circuits oversized answers (no tool calls,
   answer > ``max_tokens``) with a single capped rewrite call. Without this,
   providers that ignore the cap can return arbitrarily long final answers
   even when the caller asks for a small response.

3. Within-cap short-circuits don't trigger any extra LLM call (regression
   guard against the cheap path becoming a 2x cost path).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from atulya_api.engine.reflect.agent import _estimate_tokens, run_reflect_agent
from atulya_api.engine.response_models import LLMToolCall, LLMToolCallResult, TokenUsage


# ─── 1. Gemini provider forwards max_completion_tokens ───────────────────────


class TestGeminiMaxOutputTokensForwarded:
    """Verify the Gemini ``call`` and ``call_with_tools`` paths set
    ``max_output_tokens`` on the generation config when the caller passes
    ``max_completion_tokens``.

    We capture ``GenerateContentConfig`` construction without spinning up a
    real client by patching ``genai_types.GenerateContentConfig``.
    """

    def _make_llm(self) -> Any:
        from atulya_api.engine.providers import gemini_llm

        llm = gemini_llm.GeminiLLM.__new__(gemini_llm.GeminiLLM)
        llm.provider = "gemini"
        llm.model = "gemini-2.5-flash"
        llm.api_key = "test"
        llm._client = MagicMock()
        llm._is_vertexai = False
        llm._safety_settings = None
        return llm

    @pytest.mark.asyncio
    async def test_call_sets_max_output_tokens(self) -> None:
        from atulya_api.engine.providers import gemini_llm

        captured: dict[str, Any] = {}

        class _FakeConfig:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

        async def _fake_generate(*args: Any, **kwargs: Any) -> Any:
            response = MagicMock()
            response.text = "ok"
            response.usage_metadata = MagicMock(prompt_token_count=1, candidates_token_count=1)
            return response

        llm = self._make_llm()
        llm._client.aio.models.generate_content = AsyncMock(side_effect=_fake_generate)

        with patch.object(gemini_llm.genai_types, "GenerateContentConfig", _FakeConfig):
            await llm.call(
                messages=[{"role": "user", "content": "hello"}],
                max_completion_tokens=128,
            )

        assert captured.get("max_output_tokens") == 128

    @pytest.mark.asyncio
    async def test_call_with_tools_sets_max_output_tokens(self) -> None:
        from atulya_api.engine.providers import gemini_llm

        captured: dict[str, Any] = {}

        class _FakeConfig:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

        async def _fake_generate(*args: Any, **kwargs: Any) -> Any:
            response = MagicMock()
            response.text = "ok"
            response.candidates = []
            response.usage_metadata = MagicMock(prompt_token_count=1, candidates_token_count=1)
            return response

        llm = self._make_llm()
        llm._client.aio.models.generate_content = AsyncMock(side_effect=_fake_generate)

        with patch.object(gemini_llm.genai_types, "GenerateContentConfig", _FakeConfig):
            try:
                await llm.call_with_tools(
                    messages=[{"role": "user", "content": "hello"}],
                    tools=[{"function": {"name": "noop", "description": "", "parameters": {}}}],
                    max_completion_tokens=256,
                )
            except Exception:
                # Downstream parsing of our minimal fake response may fail; we
                # only need to assert the cap reached GenerateContentConfig
                # before any error path ran.
                pass

        assert captured.get("max_output_tokens") == 256

    @pytest.mark.asyncio
    async def test_call_omits_max_output_tokens_when_unset(self) -> None:
        from atulya_api.engine.providers import gemini_llm

        captured: dict[str, Any] = {}

        class _FakeConfig:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

        async def _fake_generate(*args: Any, **kwargs: Any) -> Any:
            response = MagicMock()
            response.text = "ok"
            response.usage_metadata = MagicMock(prompt_token_count=1, candidates_token_count=1)
            return response

        llm = self._make_llm()
        llm._client.aio.models.generate_content = AsyncMock(side_effect=_fake_generate)

        with patch.object(gemini_llm.genai_types, "GenerateContentConfig", _FakeConfig):
            await llm.call(
                messages=[{"role": "user", "content": "hello"}],
            )

        assert "max_output_tokens" not in captured


# ─── 2 & 3. Short-circuit answer cap enforcement ─────────────────────────────


def _mock_functions() -> dict[str, Any]:
    return {
        "search_mental_models_fn": AsyncMock(return_value={"mental_models": []}),
        "search_observations_fn": AsyncMock(return_value={"observations": []}),
        "recall_fn": AsyncMock(return_value={"memories": []}),
        "expand_fn": AsyncMock(return_value={"memories": []}),
    }


class TestReflectShortCircuitMaxTokens:
    @pytest.mark.asyncio
    async def test_oversized_short_circuit_triggers_capped_rewrite(self) -> None:
        """When the LLM returns a long answer with no tool calls, the agent
        must issue exactly one capped rewrite call and return its output."""
        long_answer = "word " * 5000  # well above any small cap
        rewritten = "Short rewritten answer."

        llm = MagicMock()
        llm.call_with_tools = AsyncMock(
            return_value=LLMToolCallResult(
                content=long_answer,
                tool_calls=[],
                finish_reason="stop",
            )
        )
        llm.call = AsyncMock(
            return_value=(rewritten, TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15))
        )

        result = await run_reflect_agent(
            llm_config=llm,
            bank_id="test-bank",
            query="q",
            bank_profile={"name": "T", "mission": "M"},
            max_tokens=64,
            **_mock_functions(),
        )

        assert result.text == rewritten
        # Exactly one rewrite call (the cap-enforcement path).
        assert llm.call.await_count == 1
        # The rewrite call must request the same cap the caller asked for.
        kwargs = llm.call.await_args.kwargs
        assert kwargs.get("max_completion_tokens") == 64
        assert kwargs.get("scope") == "reflect"

    @pytest.mark.asyncio
    async def test_within_cap_short_circuit_skips_rewrite(self) -> None:
        """When the answer is already within the cap, no extra LLM call."""
        short_answer = "Concise answer."

        llm = MagicMock()
        llm.call_with_tools = AsyncMock(
            return_value=LLMToolCallResult(
                content=short_answer,
                tool_calls=[],
                finish_reason="stop",
            )
        )
        llm.call = AsyncMock()  # would blow up if called with no return value set

        result = await run_reflect_agent(
            llm_config=llm,
            bank_id="test-bank",
            query="q",
            bank_profile={"name": "T", "mission": "M"},
            max_tokens=4096,
            **_mock_functions(),
        )

        assert result.text == short_answer
        llm.call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_max_tokens_skips_rewrite(self) -> None:
        """When max_tokens is None the cap path must not trigger at all."""
        long_answer = "word " * 5000

        llm = MagicMock()
        llm.call_with_tools = AsyncMock(
            return_value=LLMToolCallResult(
                content=long_answer,
                tool_calls=[],
                finish_reason="stop",
            )
        )
        llm.call = AsyncMock()

        result = await run_reflect_agent(
            llm_config=llm,
            bank_id="test-bank",
            query="q",
            bank_profile={"name": "T", "mission": "M"},
            max_tokens=None,
            **_mock_functions(),
        )

        assert result.text == long_answer.strip()
        llm.call.assert_not_awaited()


class TestEstimateTokens:
    def test_empty_string_is_zero(self) -> None:
        assert _estimate_tokens("") == 0

    def test_monotonic_with_length(self) -> None:
        short = _estimate_tokens("hello")
        long = _estimate_tokens("hello " * 500)
        assert long > short
