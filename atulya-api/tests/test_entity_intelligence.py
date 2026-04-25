from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from atulya_api.engine.db_utils import acquire_with_retry
from atulya_api.engine.entity_trajectory.bank_intelligence import (
    EntityIntelligenceService,
    build_entity_intelligence_context,
    categorize_entity_name,
)
from atulya_api.engine.entity_trajectory.intelligence_persisted_row import (
    entity_intelligence_payload_from_record,
)
from atulya_api.engine.memory_engine import fq_table


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        enable_entity_intelligence=True,
        entity_intelligence_min_entities=3,
        entity_intelligence_max_entities=50,
        entity_intelligence_max_context_tokens=2000,
        entity_intelligence_max_completion_tokens=4096,
        entity_intelligence_prompt_version="v2-digital-person-map",
        retain_max_completion_tokens=8192,
    )


def _mock_llm(*responses: str) -> MagicMock:
    llm = MagicMock()
    llm.provider = "mock"
    llm.model = "entity-intel-test"
    llm.call = AsyncMock(side_effect=list(responses))
    return llm


def test_context_compaction_preserves_counts_when_truncated():
    rows = [
        {
            "id": str(uuid4()),
            "canonical_name": f"Entity {i}",
            "mention_count": 200 - i,
            "first_seen": datetime.now(UTC),
            "last_seen": datetime.now(UTC),
            "current_state": "ACTIVE_DISCOVERY",
            "anomaly_score": 0.25,
            "forecast_distribution": {"ACTIVE_DISCOVERY": 0.7, "MAINTENANCE": 0.3},
            "viterbi_path": [{"fact_preview": "Long repeated preview " * 20}],
        }
        for i in range(30)
    ]

    context = build_entity_intelligence_context(
        rows,
        source_entity_count=30,
        max_context_tokens=250,
        min_entities=5,
    )

    assert context["source_entity_count"] == 30
    assert context["included_entity_count"] >= 5
    assert context["omitted_entity_count"] == 30 - context["included_entity_count"]
    assert context["compaction"] in {
        "dropped_recent_fact_previews",
        "dropped_recent_fact_previews_and_forecasts",
        "truncated_lowest_signal_entities",
    }


def test_entity_categorization_builds_digital_person_map():
    assert categorize_entity_name("user") == "self_anchor"
    assert categorize_entity_name("Antara Das") == "human_name"
    assert categorize_entity_name("random lowercase person", {"entity_type": "person", "entity_type_confidence": 0.91}) == "human_name"
    assert categorize_entity_name("LM Studio") == "organization"
    assert categorize_entity_name("PostgreSQL worker") == "tool_technology"
    assert categorize_entity_name("Atulya Brain") == "project_product"
    assert categorize_entity_name("marriage planning") == "event_goal"

    rows = [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "canonical_name": "user",
            "mention_count": 40,
        },
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "canonical_name": "Antara Das",
            "mention_count": 14,
        },
        {
            "id": "00000000-0000-0000-0000-000000000003",
            "canonical_name": "PostgreSQL worker",
            "mention_count": 9,
        },
        {
            "id": "00000000-0000-0000-0000-000000000004",
            "canonical_name": "semantic memory",
            "mention_count": 7,
        },
    ]
    relationships = [
        {
            "entity_id_1": "00000000-0000-0000-0000-000000000001",
            "entity_id_2": "00000000-0000-0000-0000-000000000002",
            "cooccurrence_count": 6,
        },
        {
            "entity_id_1": "00000000-0000-0000-0000-000000000001",
            "entity_id_2": "00000000-0000-0000-0000-000000000003",
            "cooccurrence_count": 5,
        },
    ]

    context = build_entity_intelligence_context(
        rows,
        relationship_rows=relationships,
        source_entity_count=4,
        max_context_tokens=2000,
        min_entities=3,
    )

    digital_map = context["digital_person_map"]
    assert context["map_version"] == "digital-person-v2"
    assert digital_map["category_counts"]["self_anchor"] == 1
    assert digital_map["category_counts"]["human_name"] == 1
    assert digital_map["circles"]["inner_people"][0]["name"] == "Antara Das"
    assert digital_map["people_system"][0]["name"] == "user"
    assert digital_map["strong_relationships"][0]["a"] == "user"
    assert digital_map["strong_relationships"][0]["b"] == "Antara Das"


@pytest.mark.asyncio
async def test_entity_resolver_persists_root_classification(memory):
    bank_id = f"entity_type_{uuid4()}"
    pool = await memory._get_pool()
    async with acquire_with_retry(pool) as conn:
        entity_ids = await memory.entity_resolver.resolve_entities_batch(
            bank_id=bank_id,
            entities_data=[
                {
                    "text": "lowercase nickname",
                    "type": "CONCEPT",
                    "entity_type": "person",
                    "confidence": 0.88,
                    "evidence": "speaker says this is my close friend",
                    "role_hint": "close friend",
                    "nearby_entities": [],
                    "event_date": datetime.now(UTC),
                }
            ],
            context="",
            unit_event_date=None,
            conn=conn,
        )
    await memory.entity_resolver.flush_pending_stats()

    async with acquire_with_retry(pool) as conn:
        row = await conn.fetchrow(
            f"SELECT metadata FROM {fq_table('entities')} WHERE id = $1::uuid",
            entity_ids[0],
        )

    assert row is not None
    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    assert metadata["entity_type"] == "person"
    assert metadata["entity_type_confidence"] == 0.88
    assert metadata["role_hint"] == "close friend"


def test_entity_intelligence_payload_normalizes_json_fields():
    now = datetime.now(UTC)
    row = {
        "bank_id": "bank-a",
        "computed_at": now,
        "entity_count": 2,
        "source_entity_count": 4,
        "entity_snapshot_hash": "abc",
        "content": "## Hidden Meaning\n",
        "structured_content": json.dumps({"version": 1, "sections": []}),
        "entity_context": json.dumps({"entities": []}),
        "delta_metadata": json.dumps({"mode": "full"}),
        "llm_model": "mock/model",
        "prompt_version": "v1",
    }

    out = entity_intelligence_payload_from_record(row)

    assert out["computed_at"] == now.isoformat()
    assert out["structured_content"] == {"version": 1, "sections": []}
    assert out["entity_context"] == {"entities": []}
    assert out["delta_metadata"] == {"mode": "full"}


@pytest.mark.asyncio
async def test_entity_intelligence_full_then_delta_persists(memory):
    bank_id = f"entity_intel_{uuid4()}"
    base = datetime.now(UTC) - timedelta(days=5)
    first_doc = {
        "version": 1,
        "sections": [
            {
                "id": "hidden-meaning",
                "heading": "Hidden Meaning",
                "level": 2,
                "blocks": [{"type": "paragraph", "text": "The bank is converging around delivery."}],
            },
            {
                "id": "predictions",
                "heading": "Predictions",
                "level": 2,
                "blocks": [{"type": "bullet_list", "items": ["More implementation work is likely."]}],
            },
        ],
    }
    delta = {
        "operations": [
            {
                "op": "replace_block",
                "section_id": "hidden-meaning",
                "index": 0,
                "block": {
                    "type": "paragraph",
                    "text": "The bank is shifting from delivery into operational learning.",
                },
            }
        ]
    }
    llm = _mock_llm(json.dumps(first_doc), json.dumps(delta))

    pool = await memory._get_pool()
    async with acquire_with_retry(pool) as conn:
        for i in range(4):
            await conn.execute(
                f"""
                INSERT INTO {fq_table("entities")} (bank_id, canonical_name, first_seen, last_seen, mention_count)
                VALUES ($1, $2, $3, $4, $5)
                """,
                bank_id,
                f"Project {i}",
                base + timedelta(days=i),
                base + timedelta(days=i),
                10 + i,
            )

        ok = await EntityIntelligenceService.compute_and_persist(
            conn,
            bank_id=bank_id,
            llm_config=llm,
            resolved_config=_config(),
        )
        assert ok is True

        row = await conn.fetchrow(
            f"SELECT content, delta_metadata, entity_count, source_entity_count FROM {fq_table('entity_intelligence')} WHERE bank_id = $1",
            bank_id,
        )
        assert row is not None
        assert "converging around delivery" in row["content"]

        ok = await EntityIntelligenceService.compute_and_persist(
            conn,
            bank_id=bank_id,
            llm_config=llm,
            resolved_config=_config(),
        )
        assert ok is True

        row = await conn.fetchrow(
            f"SELECT content, delta_metadata, entity_count, source_entity_count FROM {fq_table('entity_intelligence')} WHERE bank_id = $1",
            bank_id,
        )

    assert row is not None
    assert "operational learning" in row["content"]
    meta = row["delta_metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    assert meta["delta_attempted"] is True
    assert meta["delta_succeeded"] is True
    assert row["entity_count"] == 4
    assert row["source_entity_count"] == 4
