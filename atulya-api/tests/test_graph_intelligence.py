from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio

from atulya_api.api import create_app
from atulya_api.engine.db_utils import acquire_with_retry
from atulya_api.engine.graph_intelligence import (
    GraphBuildOptions,
    GraphEvidenceUnit,
    build_graph_intelligence,
    investigate_graph,
)
from atulya_api.engine.graph_scaling import build_evidence_graph_summary
from atulya_api.engine.memory_engine import fq_table


def _unit(
    unit_id: str,
    text: str,
    *,
    entity: str | None = None,
    entities: list[str] | None = None,
    tags: list[str] | None = None,
    days_ago: int = 0,
) -> GraphEvidenceUnit:
    timestamp = datetime.now(UTC) - timedelta(days=days_ago)
    return GraphEvidenceUnit(
        id=unit_id,
        text=text,
        fact_type="world",
        occurred_start=timestamp,
        mentioned_at=timestamp,
        created_at=timestamp,
        tags=tags or [],
        entities=entities or ([entity] if entity else []),
        proof_count=1,
        access_count=1,
    )


def test_state_aggregation_uses_latest_state_and_counts_evidence():
    graph = build_graph_intelligence(
        [
            _unit("u1", "Alice worked at Google.", entity="Alice", days_ago=30),
            _unit("u2", "Alice now works at OpenAI.", entity="Alice", days_ago=2),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    alice = next(node for node in graph.nodes if node.title == "Alice")
    assert alice.current_state == "Alice now works at OpenAI."
    assert alice.evidence_count == 2
    assert alice.subtitle
    assert alice.status_reason
    assert alice.primary_timestamp


def test_change_detection_emits_temporal_state_change():
    graph = build_graph_intelligence(
        [
            _unit("u1", "Alice worked at Google.", entity="Alice", days_ago=30),
            _unit("u2", "Alice now works at OpenAI.", entity="Alice", days_ago=1),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    change_events = [event for event in graph.change_events if event.change_type == "change"]
    assert change_events
    assert any("Alice appears to have changed" in event.summary for event in change_events)


def test_contradiction_detection_requires_conflicting_supported_states():
    graph = build_graph_intelligence(
        [
            _unit("u1", "Bob is remote for work.", entity="Bob", days_ago=5),
            _unit("u2", "Bob is not remote for work.", entity="Bob", days_ago=1),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    bob = next(node for node in graph.nodes if node.title == "Bob")
    assert bob.status == "contradictory"
    assert any(event.change_type == "contradiction" for event in graph.change_events if event.node_id == bob.id)


def test_stale_detection_marks_old_state_when_neighbor_moves():
    graph = build_graph_intelligence(
        [
            _unit("u1", "Alice and Bob worked on Atlas.", entities=["Alice", "Bob"], days_ago=100),
            _unit("u2", "Alice supports Atlas rollout.", entity="Alice", days_ago=80),
            _unit("u3", "Bob led Atlas ops.", entity="Bob", days_ago=10),
            _unit("u4", "Bob no longer leads Atlas ops.", entity="Bob", days_ago=1),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    alice = next(node for node in graph.nodes if node.title == "Alice")
    assert alice.status == "stale"
    assert any(event.change_type == "stale" for event in graph.change_events if event.node_id == alice.id)


def test_ranking_is_stable_when_scores_match():
    graph = build_graph_intelligence(
        [
            _unit("u1", "Alpha is in the system.", entity="Alpha", days_ago=5),
            _unit("u2", "Beta is in the system.", entity="Beta", days_ago=5),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    assert [node.title for node in graph.nodes] == ["Alpha", "Beta"]


def test_investigation_returns_focal_nodes_and_recommended_checks():
    graph = build_graph_intelligence(
        [
            _unit("u1", "Alice worked at Google.", entity="Alice", days_ago=20),
            _unit("u2", "Alice now works at OpenAI.", entity="Alice", days_ago=1),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )
    investigation = investigate_graph("What changed about Alice?", graph, graph_units := [
        _unit("u1", "Alice worked at Google.", entity="Alice", days_ago=20),
        _unit("u2", "Alice now works at OpenAI.", entity="Alice", days_ago=1),
    ])

    assert investigation.focal_node_ids
    assert investigation.change_events
    assert investigation.recommended_checks
    assert "Alice" in investigation.answer


def test_evidence_summary_prioritizes_high_usage_memories():
    summary = build_evidence_graph_summary(
        {
            "nodes": [
                {"data": {"id": "m-low", "label": "Low memory", "accessCount": 1}},
                {"data": {"id": "m-hot", "label": "Hot memory", "accessCount": 12}},
                {"data": {"id": "m-mid", "label": "Connected memory", "accessCount": 3}},
            ],
            "edges": [
                {"data": {"source": "m-hot", "target": "m-mid", "weight": 2.0, "linkType": "semantic"}},
                {"data": {"source": "m-hot", "target": "m-low", "weight": 1.0, "linkType": "semantic"}},
            ],
            "table_rows": [
                {"id": "m-low", "text": "Low priority memory", "fact_type": "world", "entities": "bank"},
                {"id": "m-hot", "text": "Frequently used memory", "fact_type": "world", "entities": "bank"},
                {"id": "m-mid", "text": "Connected memory", "fact_type": "world", "entities": "user"},
            ],
            "total_units": 320,
        }
    )

    assert summary.mode_hint == "overview"
    assert summary.top_nodes
    assert summary.top_nodes[0].id == "m-hot"
    assert summary.initial_focus_ids[0] == "m-hot"


@pytest_asyncio.fixture
async def api_client(memory):
    app = create_app(memory, initialize_memory=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_graph_intelligence_and_investigation_endpoints(api_client, memory, request_context):
    bank_id = f"graph_intelligence_test_{datetime.now(UTC).timestamp()}"
    await memory._authenticate_tenant(request_context)
    pool = await memory._get_pool()
    async with acquire_with_retry(pool) as conn:
        entity_id = await conn.fetchval(
            f"""
            INSERT INTO {fq_table("entities")} (bank_id, canonical_name, first_seen, last_seen, mention_count)
            VALUES ($1, $2, $3, $4, 2)
            RETURNING id
            """,
            bank_id,
            "Alice",
            datetime.now(UTC) - timedelta(days=20),
            datetime.now(UTC) - timedelta(days=1),
        )
        old_id = await conn.fetchval(
            f"""
            INSERT INTO {fq_table("memory_units")} (
                bank_id, text, event_date, occurred_start, mentioned_at, fact_type, tags, proof_count
            )
            VALUES ($1, $2, $3, $3, $3, 'world', $4::varchar[], 1)
            RETURNING id
            """,
            bank_id,
            "Alice worked at Google.",
            datetime.now(UTC) - timedelta(days=20),
            ["company"],
        )
        new_id = await conn.fetchval(
            f"""
            INSERT INTO {fq_table("memory_units")} (
                bank_id, text, event_date, occurred_start, mentioned_at, fact_type, tags, proof_count
            )
            VALUES ($1, $2, $3, $3, $3, 'world', $4::varchar[], 1)
            RETURNING id
            """,
            bank_id,
            "Alice now works at OpenAI.",
            datetime.now(UTC) - timedelta(days=1),
            ["company"],
        )
        await conn.executemany(
            f"INSERT INTO {fq_table('unit_entities')} (unit_id, entity_id) VALUES ($1, $2)",
            [(old_id, entity_id), (new_id, entity_id)],
        )

    intelligence_response = await api_client.get(
        f"/v1/default/banks/{bank_id}/graph/intelligence",
        params={"confidence_min": 0.0, "node_kind": "entity"},
    )
    assert intelligence_response.status_code == 200
    intelligence = intelligence_response.json()
    assert intelligence["nodes"]
    assert intelligence["change_events"]
    assert intelligence["nodes"][0]["kind"] == "entity"

    investigate_response = await api_client.post(
        f"/v1/default/banks/{bank_id}/graph/investigate",
        json={"query": "What changed about Alice?", "confidence_min": 0.0, "node_kind": "entity"},
    )
    assert investigate_response.status_code == 200
    investigation = investigate_response.json()
    assert investigation["answer"]
    assert investigation["focal_node_ids"]
    assert investigation["change_events"]

    summary_response = await api_client.get(
        f"/v1/default/banks/{bank_id}/graph/summary",
        params={"surface": "state", "confidence_min": 0.0, "node_kind": "entity"},
    )
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["surface"] == "state"
    assert summary["initial_focus_ids"]
    assert summary["total_nodes"] >= 1

    neighborhood_response = await api_client.get(
        f"/v1/default/banks/{bank_id}/graph/neighborhood",
        params=[
            ("surface", "state"),
            ("confidence_min", "0.0"),
            ("node_kind", "entity"),
            ("focus_ids", intelligence["nodes"][0]["id"]),
        ],
    )
    assert neighborhood_response.status_code == 200
    neighborhood = neighborhood_response.json()
    assert neighborhood["surface"] == "state"
    assert neighborhood["focus_ids"]
    assert neighborhood["nodes"]

    evidence_summary_response = await api_client.get(
        f"/v1/default/banks/{bank_id}/graph/summary",
        params={"surface": "evidence"},
    )
    assert evidence_summary_response.status_code == 200
    evidence_summary = evidence_summary_response.json()
    assert evidence_summary["surface"] == "evidence"
    assert evidence_summary["top_nodes"]

    evidence_neighborhood_response = await api_client.get(
        f"/v1/default/banks/{bank_id}/graph/neighborhood",
        params=[("surface", "evidence"), ("focus_ids", str(new_id))],
    )
    assert evidence_neighborhood_response.status_code == 200
    evidence_neighborhood = evidence_neighborhood_response.json()
    assert evidence_neighborhood["surface"] == "evidence"
    assert evidence_neighborhood["nodes"]
