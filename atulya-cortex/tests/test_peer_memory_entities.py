from __future__ import annotations

import pytest

from cortex.peer_memory import PeerMemoryBridge


class _FakeMentalModelsAPI:
    def list(self, bank_id: str):
        return type("R", (), {"items": []})()


class _FakeMemoriesAPI:
    def __init__(self, items):
        self._items = items

    def list(self, bank_id: str, memory_type=None, search_query=None, limit=100, offset=0):
        return __import__("builtins").type("R", (), {"items": list(self._items)})()


class _FakeEmbedded:
    def __init__(self, items):
        self.mental_models = _FakeMentalModelsAPI()
        self.memories = _FakeMemoriesAPI(items)

    async def acreate_bank(self, bank_id: str, retain_mission: str = ""):
        return None


class _NoopHip:
    async def encode(self, *args, **kwargs):
        return None


class _NoopRecall:
    async def recall(self, *args, **kwargs):
        return []


@pytest.mark.asyncio
async def test_top_used_entities_capped_at_88_and_sorted_by_usage() -> None:
    items = []
    for i in range(120):
        items.append(
            {
                "id": f"mem-{i}",
                "type": "semantic",
                "content": f"entity {i}",
                "usage_count": i,
            }
        )
    bridge = PeerMemoryBridge(
        embedded=_FakeEmbedded(items),
        hippocampus=_NoopHip(),
        recall=_NoopRecall(),
        recall_top_k=4,
    )
    top = await bridge._top_used_bank_entities("bank-a", limit=88)
    assert len(top) == 88
    assert top[0].entity_id == "mem-119"
    assert top[-1].entity_id == "mem-32"

