from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from atulya_api.engine.anomaly_models import DetectedAnomaly
from atulya_api.engine.db_utils import acquire_with_retry
from atulya_api.engine.memory_engine import fq_table
from atulya_api.engine.retain.anomaly_detection import (
    _score_contradiction,
    _token_set,
    detect_write_time_anomalies,
    persist_anomalies,
)
from atulya_api.engine.retain.types import ProcessedFact


def _embedding(a: float, b: float) -> list[float]:
    vec = [0.0] * 384
    vec[0] = a
    vec[1] = b
    return vec


def _fact(text: str, embedding: list[float], *, occurred_start: datetime | None = None) -> ProcessedFact:
    now = datetime.now(UTC)
    return ProcessedFact(
        fact_text=text,
        fact_type="world",
        embedding=embedding,
        occurred_start=occurred_start or now,
        occurred_end=None,
        mentioned_at=now,
        timeline_anchor_kind="recorded_only",
        temporal_direction="atemporal",
        temporal_confidence=None,
        temporal_reference_text=None,
        context="test",
        metadata={},
    )


def test_token_set_strips_noise_and_stop_tokens():
    tokens = _token_set("Bob is not remote; Bob resigned from office.")
    assert "bob" in tokens
    assert "remote" in tokens
    assert "resigned" in tokens


@pytest.mark.parametrize(
    "text",
    [
        "Service can't accept traffic.",
        "Service cannot accept traffic.",
        "Service isn't accepting traffic.",
        "Service won't accept traffic.",
        "Access is denied by policy.",
        "Endpoint is deprecated and disabled.",
    ],
)
def test_token_set_normalizes_negation_keywords(text):
    tokens = _token_set(text)
    assert any(
        marker in tokens
        for marker in {"cant", "isnt", "wont", "denied", "deprecated", "disabled", "not"}
    )


def test_contradiction_score_bounded_to_unit_interval():
    score = _score_contradiction(
        similarity=0.9,
        old_confidence=1.0,
        old_proof_count=10,
        old_created_at=datetime.now(UTC) - timedelta(days=1),
        now=datetime.now(UTC),
    )
    assert 0.0 <= score <= 1.0


@pytest.mark.asyncio
async def test_detect_write_time_anomalies_detects_contradiction(memory):
    bank_id = f"anomaly_contradiction_{uuid4()}"
    pool = await memory._get_pool()
    async with acquire_with_retry(pool) as conn:
        old_id = await conn.fetchval(
            f"""
            INSERT INTO {fq_table("memory_units")}
            (bank_id, text, embedding, fact_type, created_at, occurred_start, mentioned_at, proof_count)
            VALUES ($1, $2, $3::vector, 'world', $4, $4, $4, 3)
            RETURNING id
            """,
            bank_id,
            "Bob is remote for work.",
            str(_embedding(1.0, 0.0)),
            datetime.now(UTC) - timedelta(days=1),
        )
        anomalies = await detect_write_time_anomalies(
            conn,
            bank_id=bank_id,
            unit_ids=[str(uuid4())],
            facts=[_fact("Bob is not remote for work.", _embedding(0.8, 0.6))],
        )
    contradiction_events = [a for a in anomalies if a.anomaly_type == "contradiction"]
    assert contradiction_events, "expected contradiction anomaly"
    assert str(old_id) in contradiction_events[0].unit_ids
    assert contradiction_events[0].severity >= 0.30


@pytest.mark.asyncio
async def test_detect_write_time_anomalies_avoids_false_positive_same_polarity(memory):
    bank_id = f"anomaly_no_fp_{uuid4()}"
    pool = await memory._get_pool()
    async with acquire_with_retry(pool) as conn:
        await conn.execute(
            f"""
            INSERT INTO {fq_table("memory_units")}
            (bank_id, text, embedding, fact_type, created_at, occurred_start, mentioned_at, proof_count)
            VALUES ($1, $2, $3::vector, 'world', $4, $4, $4, 2)
            """,
            bank_id,
            "Alice works from home.",
            str(_embedding(1.0, 0.0)),
            datetime.now(UTC) - timedelta(days=2),
        )
        anomalies = await detect_write_time_anomalies(
            conn,
            bank_id=bank_id,
            unit_ids=[str(uuid4())],
            facts=[_fact("Alice works remotely from home.", _embedding(0.95, 0.05))],
        )
    assert not [a for a in anomalies if a.anomaly_type == "contradiction"]


@pytest.mark.asyncio
async def test_detect_write_time_anomalies_avoids_false_positive_topic_drift(memory):
    bank_id = f"anomaly_topic_drift_{uuid4()}"
    pool = await memory._get_pool()
    async with acquire_with_retry(pool) as conn:
        await conn.execute(
            f"""
            INSERT INTO {fq_table("memory_units")}
            (bank_id, text, embedding, fact_type, created_at, occurred_start, mentioned_at, proof_count)
            VALUES ($1, $2, $3::vector, 'world', $4, $4, $4, 2)
            """,
            bank_id,
            "Warehouse inventory increased this week.",
            str(_embedding(1.0, 0.0)),
            datetime.now(UTC) - timedelta(days=1),
        )
        anomalies = await detect_write_time_anomalies(
            conn,
            bank_id=bank_id,
            unit_ids=[str(uuid4())],
            facts=[_fact("Server is not accepting SSH traffic.", _embedding(0.8, 0.6))],
        )
    assert not anomalies, "topic drift with different tokens should not raise anomalies"


@pytest.mark.asyncio
async def test_detect_write_time_anomalies_skips_ultra_high_similarity_negation(memory):
    bank_id = f"anomaly_high_sim_{uuid4()}"
    pool = await memory._get_pool()
    async with acquire_with_retry(pool) as conn:
        await conn.execute(
            f"""
            INSERT INTO {fq_table("memory_units")}
            (bank_id, text, embedding, fact_type, created_at, occurred_start, mentioned_at, proof_count)
            VALUES ($1, $2, $3::vector, 'world', $4, $4, $4, 2)
            """,
            bank_id,
            "Nadia is on call this week.",
            str(_embedding(1.0, 0.0)),
            datetime.now(UTC) - timedelta(days=1),
        )
        anomalies = await detect_write_time_anomalies(
            conn,
            bank_id=bank_id,
            unit_ids=[str(uuid4())],
            facts=[_fact("Nadia is not on call this week.", _embedding(0.999, 0.001))],
        )
    # contradiction path explicitly blocks >0.96 cosine
    assert not [a for a in anomalies if a.anomaly_type == "contradiction"]


@pytest.mark.asyncio
async def test_persist_anomalies_round_trips_metadata_and_ids(memory):
    bank_id = f"anomaly_persist_{uuid4()}"
    pool = await memory._get_pool()
    async with acquire_with_retry(pool) as conn:
        inserted_ids = await persist_anomalies(
            conn,
            bank_id=bank_id,
            anomalies=[
                DetectedAnomaly(
                    anomaly_type="contradiction",
                    severity=0.81,
                    unit_ids=[str(uuid4()), str(uuid4())],
                    entity_ids=[],
                    description="Strict contradiction integration test",
                    metadata={"score": 0.81, "path": "unit-test"},
                )
            ],
        )
        assert len(inserted_ids) == 1

        row = await conn.fetchrow(
            f"""
            SELECT anomaly_type, severity, description, metadata
            FROM {fq_table("anomaly_events")}
            WHERE id = $1::uuid
            """,
            inserted_ids[0],
        )
    assert row is not None
    assert row["anomaly_type"] == "contradiction"
    assert float(row["severity"]) == pytest.approx(0.81, abs=1e-9)
    assert row["description"] == "Strict contradiction integration test"
    metadata = row["metadata"]
    if isinstance(metadata, str):
        import json

        metadata = json.loads(metadata)
    assert metadata["path"] == "unit-test"


@pytest.mark.asyncio
async def test_detect_write_time_anomalies_detects_temporal_inconsistency(memory):
    bank_id = f"anomaly_temporal_{uuid4()}"
    pool = await memory._get_pool()
    old_ts = datetime.now(UTC) - timedelta(days=5)
    new_ts = datetime.now(UTC) - timedelta(days=3)
    async with acquire_with_retry(pool) as conn:
        await conn.execute(
            f"""
            INSERT INTO {fq_table("memory_units")}
            (bank_id, text, embedding, fact_type, created_at, occurred_start, mentioned_at, proof_count)
            VALUES ($1, $2, $3::vector, 'world', $4, $4, $4, 1)
            """,
            bank_id,
            "Service is available in region us-east.",
            str(_embedding(1.0, 0.0)),
            old_ts,
        )
        anomalies = await detect_write_time_anomalies(
            conn,
            bank_id=bank_id,
            unit_ids=[str(uuid4())],
            facts=[_fact("Service is not available in region us-east.", _embedding(0.8, 0.6), occurred_start=new_ts)],
        )
    temporal_events = [a for a in anomalies if a.anomaly_type == "temporal_inconsistency"]
    assert temporal_events, "expected temporal inconsistency anomaly"


@pytest.mark.asyncio
async def test_detect_write_time_anomalies_deduplicates_same_pair_per_type(memory):
    bank_id = f"anomaly_dedup_{uuid4()}"
    pool = await memory._get_pool()
    async with acquire_with_retry(pool) as conn:
        await conn.execute(
            f"""
            INSERT INTO {fq_table("memory_units")}
            (bank_id, text, embedding, fact_type, created_at, occurred_start, mentioned_at, proof_count)
            VALUES ($1, $2, $3::vector, 'world', $4, $4, $4, 2)
            """,
            bank_id,
            "Cluster gateway is active in zone-a.",
            str(_embedding(1.0, 0.0)),
            datetime.now(UTC) - timedelta(days=1),
        )
        anomalies = await detect_write_time_anomalies(
            conn,
            bank_id=bank_id,
            unit_ids=[str(uuid4())],
            facts=[_fact("Cluster gateway is not active in zone-a.", _embedding(0.8, 0.6))],
        )

    contradiction = [a for a in anomalies if a.anomaly_type == "contradiction"]
    temporal = [a for a in anomalies if a.anomaly_type == "temporal_inconsistency"]
    entity = [a for a in anomalies if a.anomaly_type == "entity_inconsistency"]
    assert len(contradiction) <= 1
    assert len(temporal) <= 1
    assert len(entity) <= 1

