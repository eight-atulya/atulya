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
from atulya_api.engine.graph_scaling import (
    build_evidence_graph_summary,
    build_state_graph_neighborhood,
    build_state_graph_summary,
)
from atulya_api.engine.memory_engine import fq_table
from tests.graph_intelligence_eval_helper import (
    format_graph_intelligence_eval,
    run_graph_intelligence_eval,
)


def _unit(
    unit_id: str,
    text: str,
    *,
    entity: str | None = None,
    entities: list[str] | None = None,
    tags: list[str] | None = None,
    days_ago: int = 0,
    embedding: list[float] | None = None,
) -> GraphEvidenceUnit:
    timestamp = datetime.now(UTC) - timedelta(days=days_ago)
    return GraphEvidenceUnit(
        id=unit_id,
        text=text,
        fact_type="world",
        embedding=embedding,
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
            _unit(
                "u1",
                "Bob is remote for work.",
                entity="Bob",
                days_ago=5,
                embedding=[1.0, 0.0],
            ),
            _unit(
                "u2",
                "Bob is not remote for work.",
                entity="Bob",
                days_ago=1,
                embedding=[0.8, 0.6],
            ),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    bob = next(node for node in graph.nodes if node.title == "Bob")
    assert bob.status == "contradictory"
    assert any(event.change_type == "contradiction" for event in graph.change_events if event.node_id == bob.id)


def test_contradiction_detection_blocks_low_cosine_topic_drift():
    graph = build_graph_intelligence(
        [
            _unit(
                "u1",
                "GitHub release policy has no force pushes.",
                entity="GitHub",
                days_ago=5,
                embedding=[1.0, 0.0],
            ),
            _unit(
                "u2",
                "GitHub deployment policy is not mature.",
                entity="GitHub",
                days_ago=1,
                embedding=[0.4, 0.916515],
            ),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    github = next(node for node in graph.nodes if node.title == "GitHub")
    assert github.status == "changed"
    assert not any(event.change_type == "contradiction" for event in graph.change_events if event.node_id == github.id)


def test_contradiction_detection_blocks_high_cosine_paraphrase():
    graph = build_graph_intelligence(
        [
            _unit(
                "u1",
                "Bob works remote without office travel.",
                entity="Bob",
                days_ago=5,
                embedding=[1.0, 0.0],
            ),
            _unit(
                "u2",
                "Bob works remote.",
                entity="Bob",
                days_ago=1,
                embedding=[0.95, 0.05],
            ),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    bob = next(node for node in graph.nodes if node.title == "Bob")
    assert bob.status != "contradictory"
    assert not any(event.change_type == "contradiction" for event in graph.change_events if event.node_id == bob.id)


def test_contradiction_detection_accepts_in_band_similarity():
    graph = build_graph_intelligence(
        [
            _unit(
                "u1",
                "Bob supports remote work policy.",
                entity="Bob",
                days_ago=5,
                embedding=[1.0, 0.0],
            ),
            _unit(
                "u2",
                "Bob does not support remote work policy.",
                entity="Bob",
                days_ago=1,
                embedding=[0.8, 0.6],
            ),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    bob = next(node for node in graph.nodes if node.title == "Bob")
    assert bob.status == "contradictory"


def test_contradiction_detection_survives_semantic_state_merge():
    graph = build_graph_intelligence(
        [
            _unit(
                "u1",
                "Bob supports remote work policy.",
                entity="Bob",
                days_ago=5,
                embedding=[1.0, 0.0],
            ),
            _unit(
                "u2",
                "Bob does not support remote work policy.",
                entity="Bob",
                days_ago=1,
                embedding=[0.8, 0.6],
            ),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    contradiction_events = [event for event in graph.change_events if event.change_type == "contradiction"]
    assert contradiction_events
    assert contradiction_events[0].evidence_ids == ["u1", "u2"]


def test_contradiction_detection_skips_missing_embeddings():
    graph = build_graph_intelligence(
        [
            _unit("u1", "GitHub release policy has no force pushes.", entity="GitHub", days_ago=5),
            _unit("u2", "GitHub deployment policy is not mature.", entity="GitHub", days_ago=1),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    github = next(node for node in graph.nodes if node.title == "GitHub")
    assert github.status == "changed"
    assert not any(event.change_type == "contradiction" for event in graph.change_events if event.node_id == github.id)


def test_contradiction_detection_skips_one_sided_missing_embeddings():
    graph = build_graph_intelligence(
        [
            _unit(
                "u1",
                "GitHub release policy has no force pushes.",
                entity="GitHub",
                days_ago=5,
                embedding=[1.0, 0.0],
            ),
            _unit("u2", "GitHub deployment policy is not mature.", entity="GitHub", days_ago=1),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    github = next(node for node in graph.nodes if node.title == "GitHub")
    assert github.status == "changed"
    assert not any(event.change_type == "contradiction" for event in graph.change_events if event.node_id == github.id)


def test_contradictory_nodes_remain_visible_at_default_confidence_threshold():
    graph = build_graph_intelligence(
        [
            _unit(
                "u1",
                "Bob is remote for work.",
                entity="Bob",
                days_ago=5,
                embedding=[1.0, 0.0],
            ),
            _unit(
                "u2",
                "Bob is not remote for work.",
                entity="Bob",
                days_ago=1,
                embedding=[0.8, 0.6],
            ),
        ],
        GraphBuildOptions(limit=10, node_kind="entity"),
    )

    bob = next(node for node in graph.nodes if node.title == "Bob")
    assert bob.status == "contradictory"


def test_multiple_change_events_have_unique_ids():
    graph = build_graph_intelligence(
        [
            _unit("u1", "Alice worked at Google.", entity="Alice", days_ago=30),
            _unit("u2", "Alice now works at OpenAI.", entity="Alice", days_ago=10),
            _unit("u3", "Alice recently joined Anthropic.", entity="Alice", days_ago=1),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    change_events = [event for event in graph.change_events if event.change_type == "change"]
    assert len(change_events) == 2
    assert len({event.id for event in change_events}) == 2


def test_identical_facts_do_not_emit_change_event():
    graph = build_graph_intelligence(
        [
            _unit("u1", "Priya owns the Brain OS roadmap.", entity="Priya", days_ago=9),
            _unit("u2", "Priya owns the Brain OS roadmap.", entity="Priya", days_ago=1),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    priya = next(node for node in graph.nodes if node.title == "Priya")
    assert priya.status == "stable"
    assert not any(event.change_type == "change" for event in graph.change_events if event.node_id == priya.id)


def test_contradiction_penalty_changes_surfacing_not_support_confidence():
    units = [
        _unit(
            "u1",
            "Bob supports remote work policy.",
            entity="Bob",
            days_ago=5,
            embedding=[1.0, 0.0],
        ),
        _unit(
            "u2",
            "Bob does not support remote work policy.",
            entity="Bob",
            days_ago=1,
            embedding=[0.8, 0.6],
        ),
    ]

    without_penalty = build_graph_intelligence(
        units,
        GraphBuildOptions(
            limit=10,
            confidence_min=0.0,
            node_kind="entity",
            contradiction_confidence_penalty=0.0,
        ),
    )
    with_penalty = build_graph_intelligence(
        units,
        GraphBuildOptions(
            limit=10,
            confidence_min=0.0,
            node_kind="entity",
            contradiction_confidence_penalty=0.6,
        ),
    )

    bob_without_penalty = next(node for node in without_penalty.nodes if node.title == "Bob")
    bob_with_penalty = next(node for node in with_penalty.nodes if node.title == "Bob")
    assert bob_with_penalty.confidence == bob_without_penalty.confidence
    assert bob_with_penalty.change_score < bob_without_penalty.change_score


def test_clean_change_can_outrank_contradiction_after_penalty():
    graph = build_graph_intelligence(
        [
            _unit("a1", "Alice worked at Google.", entity="Alice", days_ago=30),
            _unit("a2", "Alice now works at OpenAI.", entity="Alice", days_ago=1),
            _unit(
                "b1",
                "Bob supports remote work policy.",
                entity="Bob",
                days_ago=5,
                embedding=[1.0, 0.0],
            ),
            _unit(
                "b2",
                "Bob does not support remote work policy.",
                entity="Bob",
                days_ago=1,
                embedding=[0.8, 0.6],
            ),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    assert [node.title for node in graph.nodes[:2]] == ["Alice", "Bob"]


def test_state_summary_uses_penalized_ordering_for_top_nodes():
    graph = build_graph_intelligence(
        [
            _unit("a1", "Alice worked at Google.", entity="Alice", days_ago=30),
            _unit("a2", "Alice now works at OpenAI.", entity="Alice", days_ago=1),
            _unit(
                "b1",
                "Bob supports remote work policy.",
                entity="Bob",
                days_ago=5,
                embedding=[1.0, 0.0],
            ),
            _unit(
                "b2",
                "Bob does not support remote work policy.",
                entity="Bob",
                days_ago=1,
                embedding=[0.8, 0.6],
            ),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    summary = build_state_graph_summary(graph)
    assert [node.title for node in summary.top_nodes[:2]] == ["Alice", "Bob"]


def test_state_summary_uses_conflict_label_for_contradictory_clusters():
    units: list[GraphEvidenceUnit] = []
    for index, name in enumerate(["Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Heidi", "Ivan", "Judy"]):
        units.extend(
            [
                _unit(
                    f"{name}-1",
                    f"{name} supports remote work policy.",
                    entity=name,
                    days_ago=5 + index,
                    embedding=[1.0, 0.0],
                ),
                _unit(
                    f"{name}-2",
                    f"{name} does not support remote work policy.",
                    entity=name,
                    days_ago=1,
                    embedding=[0.8, 0.6],
                ),
            ]
        )

    graph = build_graph_intelligence(units, GraphBuildOptions(limit=20, confidence_min=0.0, node_kind="entity"))

    summary = build_state_graph_summary(graph)
    contradictory_cluster = next(cluster for cluster in summary.clusters if cluster.status_tone == "contradictory")
    assert contradictory_cluster.title == "Conflict Entities"


def test_state_neighborhood_uses_conflict_labels_for_states_and_events():
    graph = build_graph_intelligence(
        [
            _unit(
                "u1",
                "Bob supports remote work policy.",
                entity="Bob",
                days_ago=5,
                embedding=[1.0, 0.0],
            ),
            _unit(
                "u2",
                "Bob does not support remote work policy.",
                entity="Bob",
                days_ago=1,
                embedding=[0.8, 0.6],
            ),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    neighborhood = build_state_graph_neighborhood(graph, focus_ids=["entity:bob"], depth=1)
    state_node = next(node for node in neighborhood.nodes if node.node_type == "state")
    event_node = next(
        node for node in neighborhood.nodes if node.node_type == "event" and node.status_tone == "contradictory"
    )
    assert state_node.status_label == "Conflict"
    assert event_node.title == "Conflict"
    assert event_node.status_label == "Conflict"


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


def test_same_document_cross_mentions_do_not_create_false_contradiction():
    shared_chunk_prefix = "bank_graph_doc_"
    graph = build_graph_intelligence(
        [
            GraphEvidenceUnit(
                id="u1",
                text="Atulya hired Anurag as the lead architect.",
                fact_type="world",
                embedding=[1.0, 0.0],
                occurred_start=datetime.now(UTC) - timedelta(days=5),
                mentioned_at=datetime.now(UTC) - timedelta(days=5),
                created_at=datetime.now(UTC) - timedelta(days=5),
                entities=["Atulya", "Anurag"],
                proof_count=1,
                access_count=1,
                chunk_id=f"{shared_chunk_prefix}0",
            ),
            GraphEvidenceUnit(
                id="u2",
                text="Anurag never wrote code for Atulya.",
                fact_type="world",
                embedding=[0.8, 0.6],
                occurred_start=datetime.now(UTC) - timedelta(days=5),
                mentioned_at=datetime.now(UTC) - timedelta(days=5),
                created_at=datetime.now(UTC) - timedelta(days=5),
                entities=["Atulya", "Anurag"],
                proof_count=1,
                access_count=1,
                chunk_id=f"{shared_chunk_prefix}1",
            ),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    contradiction_events = [event for event in graph.change_events if event.change_type == "contradiction"]
    assert not contradiction_events


def test_real_embeddings_preserve_ownership_for_cross_mentions(embeddings):
    texts = [
        "Anurag is the lead architect for Atulya.",
        "Anurag never wrote code for Atulya.",
    ]
    vectors = embeddings.encode(texts)
    graph = build_graph_intelligence(
        [
            _unit(
                "u1",
                texts[0],
                entities=["Anurag", "Atulya"],
                days_ago=10,
                embedding=vectors[0],
            ),
            _unit(
                "u2",
                texts[1],
                entities=["Anurag", "Atulya"],
                days_ago=1,
                embedding=vectors[1],
            ),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    anurag = next(node for node in graph.nodes if node.title == "Anurag")
    atulya = next(node for node in graph.nodes if node.title == "Atulya")
    assert anurag.status == "contradictory"
    assert atulya.status != "contradictory"


def test_real_embeddings_detect_state_change(embeddings):
    texts = [
        "Nadia worked at OpenAI in 2024.",
        "Nadia now works at Anthropic in 2026.",
    ]
    vectors = embeddings.encode(texts)
    graph = build_graph_intelligence(
        [
            _unit("u1", texts[0], entity="Nadia", days_ago=30, embedding=vectors[0]),
            _unit("u2", texts[1], entity="Nadia", days_ago=1, embedding=vectors[1]),
        ],
        GraphBuildOptions(limit=10, confidence_min=0.0, node_kind="entity"),
    )

    nadia = next(node for node in graph.nodes if node.title == "Nadia")
    assert nadia.status == "changed"
    assert not any(event.change_type == "contradiction" for event in graph.change_events if event.node_id == nadia.id)


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


@pytest.mark.asyncio
async def test_graph_intelligence_real_retain_corpus(memory, request_context):
    bank_id = f"graph_intelligence_real_eval_{datetime.now(UTC).timestamp()}"
    try:
        summary = await run_graph_intelligence_eval(memory, request_context, bank_id=bank_id)
        by_title = {row["title"]: row for row in summary}

        assert by_title["Anurag"]["status"] == "contradictory", format_graph_intelligence_eval(summary)
        assert "contradiction" in by_title["Anurag"]["event_types"], format_graph_intelligence_eval(summary)
        assert by_title["Atulya"]["status"] != "contradictory", format_graph_intelligence_eval(summary)
        assert by_title["Nadia"]["status"] != "contradictory", format_graph_intelligence_eval(summary)
        assert "Anthropic" in by_title["Nadia"]["current_state"], format_graph_intelligence_eval(summary)
        assert by_title["Priya"]["status"] != "contradictory", format_graph_intelligence_eval(summary)
        assert "Brain OS roadmap" in by_title["Priya"]["current_state"], format_graph_intelligence_eval(summary)
    finally:
        await memory.delete_bank(bank_id, request_context=request_context)


@pytest.mark.asyncio
async def test_graph_intelligence_endpoint_skips_contradiction_when_embeddings_missing(
    api_client, memory, request_context
):
    bank_id = f"graph_intelligence_missing_embed_{datetime.now(UTC).timestamp()}"
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
            "GitHub",
            datetime.now(UTC) - timedelta(days=20),
            datetime.now(UTC) - timedelta(days=1),
        )
        before_id = await conn.fetchval(
            f"""
            INSERT INTO {fq_table("memory_units")} (
                bank_id, text, event_date, occurred_start, mentioned_at, fact_type, tags, proof_count, embedding
            )
            VALUES ($1, $2, $3, $3, $3, 'world', $4::varchar[], 1, NULL)
            RETURNING id
            """,
            bank_id,
            "GitHub release policy has no force pushes.",
            datetime.now(UTC) - timedelta(days=20),
            ["policy"],
        )
        after_id = await conn.fetchval(
            f"""
            INSERT INTO {fq_table("memory_units")} (
                bank_id, text, event_date, occurred_start, mentioned_at, fact_type, tags, proof_count, embedding
            )
            VALUES ($1, $2, $3, $3, $3, 'world', $4::varchar[], 1, NULL)
            RETURNING id
            """,
            bank_id,
            "GitHub deployment policy is not mature.",
            datetime.now(UTC) - timedelta(days=1),
            ["policy"],
        )
        await conn.executemany(
            f"INSERT INTO {fq_table('unit_entities')} (unit_id, entity_id) VALUES ($1, $2)",
            [(before_id, entity_id), (after_id, entity_id)],
        )

    intelligence_response = await api_client.get(
        f"/v1/default/banks/{bank_id}/graph/intelligence",
        params={"confidence_min": 0.0, "node_kind": "entity"},
    )
    assert intelligence_response.status_code == 200
    intelligence = intelligence_response.json()
    github = next(node for node in intelligence["nodes"] if node["title"] == "GitHub")
    assert github["status"] == "changed"
    assert not any(
        event["change_type"] == "contradiction"
        for event in intelligence["change_events"]
        if event["node_id"] == github["id"]
    )
