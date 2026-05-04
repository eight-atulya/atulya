import asyncio
from types import SimpleNamespace

import pytest

from atulya_api.engine.response_models import TokenUsage
from atulya_api.engine.retain import fact_extraction


@pytest.mark.asyncio
async def test_extract_facts_from_text_respects_retain_llm_max_concurrent(monkeypatch):
    active_calls = 0
    peak_calls = 0

    async def fake_extract_facts_from_chunk(**kwargs):
        nonlocal active_calls, peak_calls
        active_calls += 1
        peak_calls = max(peak_calls, active_calls)
        await asyncio.sleep(0.01)
        active_calls -= 1
        return [], TokenUsage()

    monkeypatch.setattr(fact_extraction, "_extract_facts_from_chunk", fake_extract_facts_from_chunk)
    monkeypatch.setattr(fact_extraction, "_retain_extraction_semaphores", {})

    config = SimpleNamespace(
        retain_chunk_size=10,
        retain_llm_max_concurrent=1,
        llm_max_concurrent=32,
    )

    await fact_extraction.extract_facts_from_text(
        text="a " * 30,
        event_date=None,
        llm_config=SimpleNamespace(),
        agent_name="test-agent",
        config=config,
        context="",
    )

    assert peak_calls == 1


@pytest.mark.asyncio
async def test_extract_facts_from_text_falls_back_to_global_llm_max_concurrent(monkeypatch):
    active_calls = 0
    peak_calls = 0

    async def fake_extract_facts_from_chunk(**kwargs):
        nonlocal active_calls, peak_calls
        active_calls += 1
        peak_calls = max(peak_calls, active_calls)
        await asyncio.sleep(0.01)
        active_calls -= 1
        return [], TokenUsage()

    monkeypatch.setattr(fact_extraction, "_extract_facts_from_chunk", fake_extract_facts_from_chunk)
    monkeypatch.setattr(fact_extraction, "_retain_extraction_semaphores", {})

    config = SimpleNamespace(
        retain_chunk_size=10,
        retain_llm_max_concurrent=None,
        llm_max_concurrent=2,
    )

    await fact_extraction.extract_facts_from_text(
        text="a " * 30,
        event_date=None,
        llm_config=SimpleNamespace(),
        agent_name="test-agent",
        config=config,
        context="",
    )

    assert peak_calls <= 2
