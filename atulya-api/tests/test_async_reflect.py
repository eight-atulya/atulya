"""Tests for async reflect operations."""

import asyncio
import uuid
from datetime import datetime

import httpx
import pytest
import pytest_asyncio

from atulya_api.api import create_app
from atulya_api.engine.memory_engine import MemoryEngine
from atulya_api.engine.response_models import MemoryFact, ReflectResult, TokenUsage
from atulya_api.engine.task_backend import SyncTaskBackend


class _FakeEmbeddings:
    def __init__(self, dimension: int = 384):
        self._dimension = dimension

    @property
    def provider_name(self) -> str:
        return "test"

    @property
    def dimension(self) -> int:
        return self._dimension

    async def initialize(self) -> None:
        return None

    def encode(self, texts: list[str]) -> list[list[float]]:
        rows: list[list[float]] = []
        for text in texts:
            seed = sum(ord(ch) for ch in (text or ""))
            rows.append([float((seed + i) % 17) / 17.0 for i in range(self._dimension)])
        return rows


class _FakeCrossEncoder:
    @property
    def provider_name(self) -> str:
        return "test"

    async def initialize(self) -> None:
        return None

    async def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [0.5 for _ in pairs]


@pytest_asyncio.fixture
async def reflect_memory(pg0_db_url, query_analyzer):
    mem = MemoryEngine(
        db_url=pg0_db_url,
        memory_llm_provider="mock",
        memory_llm_api_key="",
        memory_llm_model="mock",
        embeddings=_FakeEmbeddings(),
        cross_encoder=_FakeCrossEncoder(),
        query_analyzer=query_analyzer,
        pool_min_size=1,
        pool_max_size=5,
        run_migrations=False,
        task_backend=SyncTaskBackend(),
        skip_llm_verification=True,
    )
    await mem.initialize()
    yield mem
    try:
        if mem._pool and not mem._pool._closing:
            await mem.close()
    except Exception:
        pass


@pytest_asyncio.fixture
async def api_client(reflect_memory, monkeypatch):
    """Create an async test client for the FastAPI app."""
    async def fake_reflect_async(*args, **kwargs):
        return ReflectResult(
            text="Alice prefers API-first releases with clear rollout plans.",
            based_on={
                "world": [
                    MemoryFact(
                        id="mem-1",
                        text="Alice prefers API-first releases with clear rollout plans.",
                        fact_type="world",
                        context="team preference",
                        occurred_start=None,
                        occurred_end=None,
                    )
                ]
            },
            tool_trace=[],
            llm_trace=[],
            usage=TokenUsage(input_tokens=12, output_tokens=8, total_tokens=20),
        )

    monkeypatch.setattr(reflect_memory, "reflect_async", fake_reflect_async)
    app = create_app(reflect_memory, initialize_memory=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_submit_async_reflect_returns_completed_result(api_client):
    """Async reflect should queue work and persist the final result payload."""
    bank_id = f"async_reflect_{datetime.now().timestamp()}"

    retain_response = await api_client.post(
        f"/v1/default/banks/{bank_id}/memories",
        json={
            "items": [
                {
                    "content": "Alice prefers API-first releases with clear rollout plans.",
                    "context": "team preference",
                    "tags": ["scope:release"],
                }
            ]
        },
    )
    assert retain_response.status_code == 200

    submit_response = await api_client.post(
        f"/v1/default/banks/{bank_id}/reflect/submit",
        json={
            "query": "What release style does Alice prefer?",
            "budget": "low",
            "max_tokens": 300,
            "include": {"facts": {}},
            "tags": ["scope:release"],
            "tags_match": "all",
        },
    )
    assert submit_response.status_code == 200
    operation_id = submit_response.json()["operation_id"]

    status_payload = None
    for _ in range(10):
        status_response = await api_client.get(
            f"/v1/default/banks/{bank_id}/operations/{operation_id}"
        )
        assert status_response.status_code == 200
        status_payload = status_response.json()
        if status_payload["status"] == "completed":
            break
        await asyncio.sleep(0.05)

    assert status_payload is not None
    assert status_payload["status"] == "completed"
    assert status_payload["operation_type"] == "reflect"
    assert status_payload["stage"] is not None

    result_response = await api_client.get(
        f"/v1/default/banks/{bank_id}/operations/{operation_id}/result"
    )
    assert result_response.status_code == 200
    result_payload = result_response.json()

    assert result_payload["status"] == "completed"
    assert result_payload["operation_type"] == "reflect"
    assert result_payload["stage"] is not None
    assert result_payload["result"] is not None
    assert result_payload["result"]["text"]
    assert result_payload["result"]["based_on"] is not None
    assert len(result_payload["result"]["based_on"]["memories"]) > 0


@pytest.mark.asyncio
async def test_get_operation_result_pending_returns_null(api_client, reflect_memory):
    """Pending operations should report stage but not expose a result payload yet."""
    pool = await reflect_memory._get_pool()
    operation_id = uuid.uuid4()
    bank_id = f"async_reflect_pending_{uuid.uuid4().hex[:8]}"

    await pool.execute(
        """
        INSERT INTO async_operations
        (operation_id, bank_id, operation_type, status, result_metadata)
        VALUES ($1, $2, 'reflect', 'pending', $3::jsonb)
        """,
        operation_id,
        bank_id,
        '{"operation_stage":"queued"}',
    )

    response = await api_client.get(
        f"/v1/default/banks/{bank_id}/operations/{operation_id}/result"
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["operation_type"] == "reflect"
    assert payload["stage"] == "queued"
    assert payload["result"] is None


@pytest.mark.asyncio
async def test_cancel_operation_rejects_processing_state(reflect_memory, request_context):
    """Processing operations should no longer be cancellable."""
    pool = await reflect_memory._get_pool()
    operation_id = uuid.uuid4()
    bank_id = f"async_reflect_processing_{uuid.uuid4().hex[:8]}"

    await pool.execute(
        """
        INSERT INTO async_operations
        (operation_id, bank_id, operation_type, status, result_metadata)
        VALUES ($1, $2, 'reflect', 'processing', $3::jsonb)
        """,
        operation_id,
        bank_id,
        '{"operation_stage":"reflecting"}',
    )

    with pytest.raises(ValueError, match="can no longer be cancelled"):
        await reflect_memory.cancel_operation(
            bank_id=bank_id,
            operation_id=str(operation_id),
            request_context=request_context,
        )
