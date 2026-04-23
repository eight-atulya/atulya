from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from plasticity.attention_network import (
    AttentionEntity,
    AttentionWeights,
    hash_binary_with_brain_metadata,
    ping_local_model,
    request_structured_response,
    route_entities,
    score_entity,
)


def test_score_entity_uses_weighted_formula() -> None:
    entity = AttentionEntity(
        entity_id="m1",
        category="memory",
        semantic_relevance=1.0,
        recency=0.5,
        task_alignment=0.5,
        user_intent=0.2,
        system_state=0.0,
    )
    w = AttentionWeights(semantic_relevance=0.4, recency=0.2, task_alignment=0.2, user_intent=0.1, system_state=0.1)
    assert score_entity(entity, w) == pytest.approx(0.62)


def test_route_entities_is_deterministic_and_category_capped() -> None:
    entities = [
        AttentionEntity(entity_id="memory-2", category="memory", semantic_relevance=0.3, recency=0.2, task_alignment=0.2),
        AttentionEntity(entity_id="memory-1", category="memory", semantic_relevance=0.9, recency=0.9, task_alignment=0.9),
        AttentionEntity(entity_id="memory-3", category="memory", semantic_relevance=0.8, recency=0.8, task_alignment=0.8),
        AttentionEntity(entity_id="tool-1", category="tool", semantic_relevance=0.95, recency=0.9, task_alignment=0.9),
    ]
    decision = route_entities(entities, per_category_limit=2, total_limit=3)

    # Highest-scoring tool + top two memories should survive.
    assert [s.entity.entity_id for s in decision.selected] == ["tool-1", "memory-1", "memory-3"]
    assert len(decision.banks["memory"]) == 2
    assert len(decision.banks["tool"]) == 1
    assert decision.trajectory["agent"] == 0.0


def test_hash_binary_with_brain_metadata(tmp_path: Path) -> None:
    binary = tmp_path / "ip.bin"
    binary.write_bytes(b"\x7f\x00\x00\x01")
    brain = tmp_path / "BRAIN.md"
    brain.write_text("# cortex\nmetadata\n", encoding="utf-8")

    digest = hash_binary_with_brain_metadata(binary, brain)
    assert set(digest) == {"binary_sha256", "brain_sha256", "combined_sha256", "metadata"}
    assert digest["metadata"]["binary_size"] == 4
    assert digest["metadata"]["brain_chars"] > 0


@pytest.mark.asyncio
async def test_ping_local_model_reads_models(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(200, json={"data": [{"id": "google/gemma-3-4b"}]})

    transport = httpx.MockTransport(handler)

    class _FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("plasticity.attention_network.httpx.AsyncClient", _FakeAsyncClient)
    out = await ping_local_model()
    assert out["ok"] is True
    assert "google/gemma-3-4b" in out["models"]


@pytest.mark.asyncio
async def test_request_structured_response_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "summary": "ok",
                                "confidence": 0.9,
                                "routing_recommendation": ["memory", "tool"],
                                "safety_notes": "none",
                            }
                        )
                    }
                }
            ]
        }
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)

    class _FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("plasticity.attention_network.httpx.AsyncClient", _FakeAsyncClient)
    out = await request_structured_response("hello", model="google/gemma-3-4b")
    assert out["response"]["summary"] == "ok"

