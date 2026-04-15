from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from atulya_api.api import create_app


@pytest.mark.asyncio
async def test_anomaly_intelligence_endpoint_returns_memory_payload():
    memory = MagicMock()
    memory.get_anomaly_intelligence = AsyncMock(
        return_value={
            "summary": {
                "total_events": 1,
                "open_events": 1,
                "resolved_events": 0,
                "avg_severity": 0.8,
                "by_type": {"contradiction": 1},
            },
            "events": [
                {
                    "id": "evt-1",
                    "bank_id": "bank-1",
                    "anomaly_type": "contradiction",
                    "severity": 0.8,
                    "status": "open",
                    "unit_ids": [],
                    "entity_ids": [],
                    "description": "test",
                    "metadata": {},
                    "detected_at": None,
                    "resolved_at": None,
                    "resolved_by": None,
                    "corrections": [],
                }
            ],
            "total_events_in_response": 1,
        }
    )
    app = create_app(memory, initialize_memory=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/default/banks/bank-1/anomaly/intelligence",
            json={"limit": 10, "min_severity": 0.0},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["total_events"] == 1
    assert payload["events"][0]["anomaly_type"] == "contradiction"
    memory.get_anomaly_intelligence.assert_awaited_once()
    kwargs = memory.get_anomaly_intelligence.await_args.kwargs
    assert kwargs["bank_id"] == "bank-1"
    assert kwargs["limit"] == 10
    assert kwargs["min_severity"] == 0.0


@pytest.mark.asyncio
async def test_anomaly_intelligence_endpoint_rejects_invalid_severity():
    memory = MagicMock()
    memory.get_anomaly_intelligence = AsyncMock(return_value={})
    app = create_app(memory, initialize_memory=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/default/banks/bank-1/anomaly/intelligence",
            json={"limit": 10, "min_severity": 1.5},
        )
    assert response.status_code == 422
    memory.get_anomaly_intelligence.assert_not_awaited()


@pytest.mark.asyncio
async def test_anomaly_intelligence_endpoint_forwards_status_and_types():
    memory = MagicMock()
    memory.get_anomaly_intelligence = AsyncMock(
        return_value={
            "summary": {"total_events": 0, "open_events": 0, "resolved_events": 0, "avg_severity": 0.0, "by_type": {}},
            "events": [],
            "total_events_in_response": 0,
        }
    )
    app = create_app(memory, initialize_memory=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/default/banks/bank-2/anomaly/intelligence",
            json={
                "limit": 5,
                "status": "open",
                "anomaly_types": ["contradiction", "flaw_circular"],
                "min_severity": 0.4,
            },
        )
    assert response.status_code == 200
    kwargs = memory.get_anomaly_intelligence.await_args.kwargs
    assert kwargs["bank_id"] == "bank-2"
    assert kwargs["status"] == "open"
    assert kwargs["anomaly_types"] == ["contradiction", "flaw_circular"]
    assert kwargs["min_severity"] == 0.4

