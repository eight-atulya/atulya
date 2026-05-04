import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from atulya_api.engine.consolidation import consolidator


def _make_memories(count: int) -> list[dict[str, str]]:
    return [{"id": f"memory-{index}", "text": f"memory text {index}", "tags": []} for index in range(count)]


class _RecordingConn:
    def __init__(self) -> None:
        self.marked_batches: list[list[str]] = []

    async def executemany(self, _query: str, params) -> None:
        self.marked_batches.append([str(memory_id) for (memory_id,) in params])


@pytest.mark.asyncio
async def test_process_memory_batch_respects_consolidation_llm_max_concurrent(monkeypatch):
    active_calls = 0
    peak_calls = 0

    async def fake_find_related_observations(**kwargs):
        nonlocal active_calls, peak_calls
        active_calls += 1
        peak_calls = max(peak_calls, active_calls)
        await asyncio.sleep(0.01)
        active_calls -= 1
        return SimpleNamespace(results=[], source_facts={})

    monkeypatch.setattr(consolidator, "_find_related_observations", fake_find_related_observations)
    monkeypatch.setattr(
        consolidator,
        "_collect_duplicate_telemetry",
        AsyncMock(return_value=consolidator._DuplicateTelemetry()),
    )
    monkeypatch.setattr(
        consolidator,
        "_consolidate_batch_with_llm",
        AsyncMock(return_value=consolidator._BatchLLMResult()),
    )
    monkeypatch.setattr(consolidator, "_consolidation_recall_semaphores", {})

    result = await consolidator._process_memory_batch(
        conn=object(),
        memory_engine=SimpleNamespace(),
        llm_config=SimpleNamespace(),
        bank_id="bank",
        memories=_make_memories(3),
        request_context=SimpleNamespace(),
        config=SimpleNamespace(
            consolidation_llm_max_concurrent=1,
            llm_max_concurrent=32,
            max_observations_per_scope=None,
        ),
    )

    assert peak_calls == 1
    assert len(result.results) == 3


@pytest.mark.asyncio
async def test_process_memory_batch_falls_back_to_global_llm_max_concurrent(monkeypatch):
    active_calls = 0
    peak_calls = 0

    async def fake_find_related_observations(**kwargs):
        nonlocal active_calls, peak_calls
        active_calls += 1
        peak_calls = max(peak_calls, active_calls)
        await asyncio.sleep(0.01)
        active_calls -= 1
        return SimpleNamespace(results=[], source_facts={})

    monkeypatch.setattr(consolidator, "_find_related_observations", fake_find_related_observations)
    monkeypatch.setattr(
        consolidator,
        "_collect_duplicate_telemetry",
        AsyncMock(return_value=consolidator._DuplicateTelemetry()),
    )
    monkeypatch.setattr(
        consolidator,
        "_consolidate_batch_with_llm",
        AsyncMock(return_value=consolidator._BatchLLMResult()),
    )
    monkeypatch.setattr(consolidator, "_consolidation_recall_semaphores", {})

    await consolidator._process_memory_batch(
        conn=object(),
        memory_engine=SimpleNamespace(),
        llm_config=SimpleNamespace(),
        bank_id="bank",
        memories=_make_memories(4),
        request_context=SimpleNamespace(),
        config=SimpleNamespace(
            consolidation_llm_max_concurrent=None,
            llm_max_concurrent=2,
            max_observations_per_scope=None,
        ),
    )

    assert peak_calls <= 2


@pytest.mark.asyncio
async def test_process_memory_batch_with_fallback_splits_failed_batches(monkeypatch):
    batch_sizes: list[int] = []
    conn = _RecordingConn()

    async def fake_process_memory_batch(**kwargs):
        memories = kwargs["memories"]
        batch_sizes.append(len(memories))
        if len(memories) > 1:
            raise consolidator.ConsolidationBatchError("timed out")
        return consolidator._ProcessMemoryBatchResult(results=[{"action": "skipped"}])

    monkeypatch.setattr(consolidator, "_process_memory_batch", fake_process_memory_batch)

    result = await consolidator._process_memory_batch_with_fallback(
        conn=conn,
        memory_engine=SimpleNamespace(),
        llm_config=SimpleNamespace(),
        bank_id="bank",
        memories=_make_memories(2),
        request_context=SimpleNamespace(),
        config=SimpleNamespace(),
        obs_tags_list=None,
    )

    assert batch_sizes == [2, 1, 1]
    assert conn.marked_batches == [["memory-0"], ["memory-1"]]
    assert len(result.results) == 2


@pytest.mark.asyncio
async def test_process_memory_batch_with_fallback_raises_for_single_failed_memory(monkeypatch):
    conn = _RecordingConn()

    async def fake_process_memory_batch(**kwargs):
        raise consolidator.ConsolidationBatchError("still timed out")

    monkeypatch.setattr(consolidator, "_process_memory_batch", fake_process_memory_batch)

    with pytest.raises(consolidator.ConsolidationBatchError):
        await consolidator._process_memory_batch_with_fallback(
            conn=conn,
            memory_engine=SimpleNamespace(),
            llm_config=SimpleNamespace(),
            bank_id="bank",
            memories=_make_memories(1),
            request_context=SimpleNamespace(),
            config=SimpleNamespace(),
            obs_tags_list=None,
        )

    assert conn.marked_batches == []


@pytest.mark.asyncio
async def test_consolidate_batch_with_llm_passes_max_completion_tokens():
    captured_kwargs: dict[str, object] = {}

    class _FakeLLM:
        async def call(self, **kwargs):
            captured_kwargs.update(kwargs)
            return consolidator._ConsolidationBatchResponse()

    await consolidator._consolidate_batch_with_llm(
        llm_config=_FakeLLM(),
        memories=_make_memories(1),
        union_observations=[],
        union_source_facts={},
        config=SimpleNamespace(
            observations_mission=None,
            consolidation_max_attempts=1,
            consolidation_llm_max_retries=None,
            consolidation_max_completion_tokens=777,
        ),
    )

    assert captured_kwargs["max_completion_tokens"] == 777
