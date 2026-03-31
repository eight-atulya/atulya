"""Focused tests for timeline metadata and timeline API behavior."""

import json
import uuid
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio

from atulya_api.api import create_app
from atulya_api.config import _get_raw_config
from atulya_api.engine.memory_engine import MemoryEngine, fq_table
from atulya_api.engine.temporal import classify_fact_temporal_metadata


@pytest.fixture(autouse=True)
def enable_timeline_v2():
    """Enable timeline_v2 during these tests and restore afterwards."""
    config = _get_raw_config()
    original = config.timeline_v2
    config.timeline_v2 = True
    try:
        yield
    finally:
        config.timeline_v2 = original


@pytest_asyncio.fixture
async def api_client(memory: MemoryEngine):
    """Create a FastAPI test client backed by the shared memory fixture."""
    app = create_app(memory, initialize_memory=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_timeline_engine_and_graph_data_include_temporal_metadata(
    memory: MemoryEngine, request_context
):
    """Timeline should surface facts, observations, and mental models with normalized temporal metadata."""
    bank_id = f"test-timeline-{uuid.uuid4().hex[:8]}"
    world_id = uuid.uuid4()
    event_id = uuid.uuid4()
    observation_id = uuid.uuid4()
    created_world = datetime(2024, 1, 9, 9, 0, tzinfo=timezone.utc)
    created_event = datetime(2024, 1, 10, 14, 0, tzinfo=timezone.utc)
    created_observation = datetime(2024, 1, 11, 10, 0, tzinfo=timezone.utc)
    model_refreshed_at = datetime(2024, 1, 12, 8, 30, tzinfo=timezone.utc)

    await memory.get_bank_profile(bank_id=bank_id, request_context=request_context)

    try:
        async with memory._pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {fq_table("memory_units")} (
                    id, bank_id, text, context, event_date, mentioned_at, created_at,
                    timeline_anchor_at, timeline_anchor_kind, temporal_direction,
                    temporal_confidence, fact_type, tags
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'world', $12)
                """,
                world_id,
                bank_id,
                "Alice likes green tea.",
                "preference",
                created_world,
                created_world,
                created_world,
                created_world,
                "recorded_only",
                "present",
                0.35,
                ["tea"],
            )
            await conn.execute(
                f"""
                INSERT INTO {fq_table("memory_units")} (
                    id, bank_id, text, context, event_date, occurred_start, mentioned_at, created_at,
                    timeline_anchor_at, timeline_anchor_kind, temporal_direction,
                    temporal_confidence, temporal_reference_text, fact_type, tags
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, 'experience', $14)
                """,
                event_id,
                bank_id,
                "Alice joined Acme on 2024-01-10.",
                "career",
                created_event,
                created_event,
                created_event,
                created_event,
                created_event,
                "event_exact",
                "past",
                1.0,
                "2024-01-10",
                ["career"],
            )
            await conn.execute(
                f"""
                INSERT INTO {fq_table("memory_units")} (
                    id, bank_id, text, context, event_date, mentioned_at, created_at,
                    timeline_anchor_at, timeline_anchor_kind, temporal_direction,
                    temporal_confidence, fact_type, proof_count, source_memory_ids, tags
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'observation', $12, $13::uuid[], $14)
                """,
                observation_id,
                bank_id,
                "Alice works at Acme.",
                "current state",
                created_observation,
                created_observation,
                created_observation,
                created_observation,
                "ongoing_state",
                "present",
                0.62,
                2,
                [world_id, event_id],
                ["career"],
            )
            await conn.execute(
                f"""
                INSERT INTO {fq_table("memory_links")} (from_unit_id, to_unit_id, link_type, weight)
                VALUES ($1, $2, 'semantic', 0.8)
                """,
                event_id,
                observation_id,
            )
            await conn.execute(
                f"""
                INSERT INTO {fq_table("mental_models")} (
                    id, bank_id, name, source_query, content, tags, last_refreshed_at, created_at, reflect_response
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                """,
                "mm-timeline",
                bank_id,
                "Employment Snapshot",
                "What do we know about Alice's work situation?",
                "Alice currently works at Acme and prefers green tea during work.",
                ["career"],
                model_refreshed_at,
                model_refreshed_at,
                json.dumps(
                    {
                        "based_on": {
                            "memories": [
                                {"id": str(observation_id)},
                                {"id": str(event_id)},
                            ]
                        }
                    }
                ),
            )

        timeline = await memory.get_timeline(
            bank_id=bank_id,
            fact_type=None,
            q=None,
            tags=None,
            tags_match="all_strict",
            limit=20,
            request_context=request_context,
        )

        assert timeline["total_items"] == 4
        items_by_id = {item["id"]: item for item in timeline["items"]}
        assert items_by_id[str(world_id)]["anchor_kind"] == "recorded_only"
        assert items_by_id[str(world_id)]["temporal"]["anchor_at"] == created_world.isoformat()
        assert items_by_id[str(event_id)]["anchor_kind"] == "event_exact"
        assert items_by_id[str(observation_id)]["anchor_kind"] == "ongoing_state"
        assert items_by_id["mm-timeline"]["kind"] == "mental_model"
        assert items_by_id["mm-timeline"]["anchor_kind"] == "derived_snapshot"
        assert items_by_id["mm-timeline"]["source_memory_ids"] == [str(observation_id), str(event_id)]

        edge_kinds = {edge["edge_kind"] for edge in timeline["edges"]}
        assert "chronological" in edge_kinds
        assert "semantic" in edge_kinds
        assert "source" in edge_kinds
        assert "derived" in edge_kinds

        graph_data = await memory.get_graph_data(
            bank_id=bank_id,
            fact_type=None,
            limit=20,
            q=None,
            tags=None,
            request_context=request_context,
        )
        graph_rows = {row["id"]: row for row in graph_data["table_rows"]}
        assert graph_rows[str(world_id)]["timeline_anchor_kind"] == "recorded_only"
        assert graph_rows[str(world_id)]["temporal"]["anchor_kind"] == "recorded_only"
        assert graph_rows[str(observation_id)]["temporal"]["anchor_kind"] == "ongoing_state"
    finally:
        await memory.delete_bank(bank_id, request_context=request_context)


@pytest.mark.asyncio
async def test_timeline_and_version_http_endpoints(api_client, memory: MemoryEngine, request_context):
    """HTTP endpoints should expose timeline_v2 and return timeline items with temporal blocks."""
    bank_id = f"http-timeline-{uuid.uuid4().hex[:8]}"
    now = datetime(2024, 2, 1, 12, 0, tzinfo=timezone.utc)

    await memory.get_bank_profile(bank_id=bank_id, request_context=request_context)
    try:
        async with memory._pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {fq_table("memory_units")} (
                    id, bank_id, text, event_date, mentioned_at, created_at,
                    timeline_anchor_at, timeline_anchor_kind, temporal_direction,
                    temporal_confidence, fact_type, tags
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'world', $11)
                """,
                uuid.uuid4(),
                bank_id,
                "Roadmap planning happens every Friday.",
                now,
                now,
                now,
                now,
                "recorded_only",
                "present",
                0.35,
                ["planning"],
            )

        version_response = await api_client.get("/version")
        assert version_response.status_code == 200
        assert version_response.json()["features"]["timeline_v2"] is True

        timeline_response = await api_client.get(f"/v1/default/banks/{bank_id}/timeline")
        assert timeline_response.status_code == 200
        payload = timeline_response.json()
        assert payload["total_items"] == 1
        assert payload["items"][0]["temporal"]["anchor_kind"] == "recorded_only"
        assert payload["items"][0]["temporal"]["recorded_at"] == now.isoformat()
    finally:
        await memory.delete_bank(bank_id, request_context=request_context)


def test_classify_fact_temporal_metadata_marks_future_plan_without_occurrence():
    """Future-oriented facts should still get a semantic future classification even without occurred_start."""
    recorded_at = datetime(2024, 3, 1, 9, 0, tzinfo=timezone.utc)

    metadata = classify_fact_temporal_metadata(
        fact_text="Alice will start a new role next month.",
        occurred_start=None,
        mentioned_at=recorded_at,
        created_at=recorded_at,
        explicit_temporal=False,
        inferred_temporal=False,
    )

    assert metadata.anchor_at == recorded_at
    assert metadata.anchor_kind == "future_plan"
    assert metadata.direction == "future"
