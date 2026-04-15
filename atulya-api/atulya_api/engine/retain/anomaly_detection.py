"""
Write-time anomaly detection for retain pipeline.
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime

from atulya_api.engine.anomaly_models import DetectedAnomaly
from atulya_api.engine.embedding_similarity import cosine_similarity, parse_embedding_text
from atulya_api.engine.memory_engine import fq_table
from atulya_api.engine.retain.types import ProcessedFact

_NEGATION_MARKERS = {
    "not",
    "no",
    "never",
    "cannot",
    "cant",
    "won't",
    "wont",
    "don't",
    "dont",
    "didn't",
    "didnt",
    "isn't",
    "isnt",
    "aren't",
    "arent",
    "wasn't",
    "wasnt",
    "weren't",
    "werent",
    "n't",
    "neither",
    "nor",
    "none",
    "without",
    "non",
    "deprecated",
    "disabled",
    "decommissioned",
    "revoked",
    "terminated",
    "blocked",
    "forbidden",
    "prohibited",
    "denied",
    "stopped",
    "quit",
    "left",
    "resigned",
    "retired",
    "ended",
    "cancelled",
    "abandoned",
    "removed",
    "deleted",
    "closed",
    "rejected",
    "former",
    "ex",
    "previously",
}
_TOKEN_PATTERN = re.compile(r"[a-z0-9_']+")
_NEGATION_EQUIVALENTS = {
    "can't": "cant",
    "cannot": "cant",
    "won't": "wont",
    "don't": "dont",
    "didn't": "didnt",
    "isn't": "isnt",
    "aren't": "arent",
    "wasn't": "wasnt",
    "weren't": "werent",
}


def _token_set(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in _TOKEN_PATTERN.findall(text.lower()):
        normalized = _NEGATION_EQUIVALENTS.get(token, token)
        if len(normalized) > 1:
            tokens.add(normalized)
    return tokens


def _is_negated(text: str) -> bool:
    return bool(_token_set(text) & _NEGATION_MARKERS)


def _score_contradiction(
    similarity: float,
    old_confidence: float | None,
    old_proof_count: int,
    old_created_at: datetime | None,
    now: datetime,
) -> float:
    w_sem = similarity
    w_conf = old_confidence if old_confidence is not None else 1.0
    if old_created_at is None:
        w_temp = 1.0
    else:
        delta_hours = max((now - old_created_at).total_seconds() / 3600.0, 0.0)
        w_temp = math.exp(-0.001 * delta_hours)
    w_recency = 1.0 + 0.5 * min(max(old_proof_count, 0), 10) / 10.0
    raw = w_sem * w_conf * w_temp * w_recency
    return max(0.0, min(1.0, raw / 1.44))


async def detect_write_time_anomalies(
    conn,
    *,
    bank_id: str,
    unit_ids: list[str],
    facts: list[ProcessedFact],
) -> list[DetectedAnomaly]:
    """
    Detect contradiction, temporal, and entity inconsistency anomalies.
    """
    if not unit_ids or not facts:
        return []

    anomalies: list[DetectedAnomaly] = []
    seen_keys: set[tuple[str, str, str]] = set()
    now = datetime.now(UTC)
    new_unit_ids = [str(unit_id) for unit_id in unit_ids]

    for unit_id, fact in zip(new_unit_ids, facts, strict=False):
        new_tokens = _token_set(fact.fact_text)
        if len(new_tokens) < 2:
            continue

        rows = await conn.fetch(
            f"""
            SELECT id, text, embedding::text AS embedding_text, confidence_score, proof_count, created_at,
                   occurred_start, fact_type
            FROM {fq_table("memory_units")}
            WHERE bank_id = $1
              AND id != ALL($2::uuid[])
              AND embedding IS NOT NULL
              AND embedding <=> $3::vector < 0.45
            ORDER BY embedding <=> $3::vector
            LIMIT 20
            """,
            bank_id,
            new_unit_ids,
            str(fact.embedding),
        )

        new_negated = _is_negated(fact.fact_text)
        for row in rows:
            old_text = str(row["text"] or "")
            overlap = new_tokens & _token_set(old_text)
            if len(overlap) < 2:
                continue
            old_negated = _is_negated(old_text)
            if old_negated == new_negated:
                continue

            old_embedding = parse_embedding_text(row["embedding_text"])
            similarity = cosine_similarity(fact.embedding, old_embedding)
            if similarity is None or similarity < 0.55 or similarity > 0.96:
                continue

            contradiction_score = _score_contradiction(
                similarity,
                row["confidence_score"],
                int(row["proof_count"] or 0),
                row["created_at"],
                now,
            )
            if contradiction_score >= 0.30:
                pair_key = tuple(sorted((unit_id, str(row["id"]))))
                dedup_key = ("contradiction", pair_key[0], pair_key[1])
                if dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    anomalies.append(
                        DetectedAnomaly(
                            anomaly_type="contradiction",
                            severity=contradiction_score,
                            unit_ids=[unit_id, str(row["id"])],
                            description="Contradictory memory statements detected.",
                            metadata={
                                "similarity": round(similarity, 6),
                                "overlap_tokens": sorted(overlap),
                                "candidate_id": str(row["id"]),
                            },
                        )
                    )

            new_time = fact.occurred_start
            old_time = row["occurred_start"]
            if new_time is not None and old_time is not None:
                delta_days = abs((new_time - old_time).total_seconds()) / 86400.0
                if delta_days <= 30 and 0.45 <= similarity <= 0.88:
                    pair_key = tuple(sorted((unit_id, str(row["id"]))))
                    dedup_key = ("temporal_inconsistency", pair_key[0], pair_key[1])
                    if dedup_key not in seen_keys:
                        seen_keys.add(dedup_key)
                        anomalies.append(
                            DetectedAnomaly(
                                anomaly_type="temporal_inconsistency",
                                severity=max(0.0, min(1.0, similarity * 0.8)),
                                unit_ids=[unit_id, str(row["id"])],
                                description="Temporal inconsistency detected for semantically similar facts.",
                                metadata={
                                    "similarity": round(similarity, 6),
                                    "delta_days": round(delta_days, 2),
                                    "candidate_id": str(row["id"]),
                                },
                            )
                        )

        if fact.entities:
            entity_rows = await conn.fetch(
                f"""
                SELECT DISTINCT mu.id, mu.text, mu.embedding::text AS embedding_text
                FROM {fq_table("memory_units")} mu
                JOIN {fq_table("unit_entities")} ue ON ue.unit_id = mu.id
                JOIN {fq_table("entities")} e ON e.id = ue.entity_id
                WHERE mu.bank_id = $1
                  AND e.canonical_name = ANY($2::text[])
                  AND mu.id != ALL($3::uuid[])
                  AND mu.embedding IS NOT NULL
                ORDER BY mu.id DESC
                LIMIT 15
                """,
                bank_id,
                [entity.name for entity in fact.entities],
                new_unit_ids,
            )
            for row in entity_rows:
                similarity = cosine_similarity(fact.embedding, parse_embedding_text(row["embedding_text"]))
                if similarity is None or similarity < 0.50 or similarity > 0.95:
                    continue
                if _is_negated(str(row["text"] or "")) == _is_negated(fact.fact_text):
                    continue
                pair_key = tuple(sorted((unit_id, str(row["id"]))))
                dedup_key = ("entity_inconsistency", pair_key[0], pair_key[1])
                if dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    anomalies.append(
                        DetectedAnomaly(
                            anomaly_type="entity_inconsistency",
                            severity=max(0.0, min(1.0, similarity * 0.7)),
                            unit_ids=[unit_id, str(row["id"])],
                            description="Entity-level inconsistent statements detected.",
                            metadata={"similarity": round(similarity, 6), "candidate_id": str(row["id"])},
                        )
                    )

    return anomalies


async def persist_anomalies(conn, *, bank_id: str, anomalies: list[DetectedAnomaly]) -> list[str]:
    if not anomalies:
        return []

    inserted_ids: list[str] = []
    for anomaly in anomalies:
        anomaly_id = await conn.fetchval(
            f"""
            INSERT INTO {fq_table("anomaly_events")}
            (bank_id, anomaly_type, severity, unit_ids, entity_ids, description, metadata)
            VALUES ($1, $2, $3, $4::uuid[], $5::uuid[], $6, $7::jsonb)
            RETURNING id
            """,
            bank_id,
            anomaly.anomaly_type,
            anomaly.severity,
            anomaly.unit_ids,
            anomaly.entity_ids,
            anomaly.description,
            json.dumps(anomaly.metadata),
        )
        inserted_ids.append(str(anomaly_id))
    return inserted_ids
