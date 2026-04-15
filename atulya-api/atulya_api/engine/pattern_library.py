"""
Pattern matching and evolution helpers.
"""

from __future__ import annotations

import json

from atulya_api.engine.anomaly_models import DetectedAnomaly
from atulya_api.engine.embedding_similarity import cosine_similarity, parse_embedding_text
from atulya_api.engine.memory_engine import fq_table
from atulya_api.engine.retain.types import ProcessedFact


def _feature_set(fact: ProcessedFact) -> set[str]:
    features: set[str] = {f"fact_type:{fact.fact_type}"}
    if fact.causal_relations:
        features.add("has_causal")
    if fact.entities:
        features.add("has_entities")
    if fact.context:
        features.add("has_context")
    if fact.occurred_start is not None:
        features.add("has_occurred_start")
    if fact.metadata:
        features.add("has_metadata")
    return features


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


async def match_patterns_for_facts(
    conn,
    *,
    bank_id: str,
    unit_ids: list[str],
    facts: list[ProcessedFact],
) -> list[DetectedAnomaly]:
    if not unit_ids or not facts:
        return []

    anomalies: list[DetectedAnomaly] = []
    for unit_id, fact in zip(unit_ids, facts, strict=False):
        rows = await conn.fetch(
            f"""
            SELECT id, name, pattern_type, structure_template, semantic_embedding::text AS embedding_text,
                   match_threshold
            FROM {fq_table("pattern_library")}
            WHERE is_active = true
              AND domain = ANY($1::text[])
              AND (bank_id = $2 OR bank_id IS NULL)
              AND semantic_embedding IS NOT NULL
              AND semantic_embedding <=> $3::vector < 0.60
            ORDER BY semantic_embedding <=> $3::vector
            LIMIT 10
            """,
            ["memory", "reasoning"],
            bank_id,
            str(fact.embedding),
        )
        current_features = _feature_set(fact)
        for row in rows:
            semantic_similarity = cosine_similarity(
                parse_embedding_text(row["embedding_text"]),
                fact.embedding,
            )
            if semantic_similarity is None:
                continue
            template_raw = row["structure_template"] or {}
            if isinstance(template_raw, str):
                try:
                    template_raw = json.loads(template_raw)
                except json.JSONDecodeError:
                    template_raw = {}
            template_features = {f"{k}:{v}" for k, v in dict(template_raw).items()}
            structural_similarity = _jaccard(current_features, template_features)
            context_match = 1.0 if fact.context else 0.0
            match_score = 0.4 * structural_similarity + 0.4 * semantic_similarity + 0.2 * context_match
            threshold = float(row["match_threshold"] or 0.65)
            if match_score < threshold:
                continue
            pattern_type = str(row["pattern_type"])
            if pattern_type not in {"anti_pattern", "pattern"}:
                continue
            anomaly_type = "pattern_anti_pattern" if pattern_type == "anti_pattern" else "pattern_violation"
            anomalies.append(
                DetectedAnomaly(
                    anomaly_type=anomaly_type,
                    severity=max(0.0, min(1.0, match_score)),
                    unit_ids=[str(unit_id)],
                    description=f"Pattern match triggered: {row['name']}",
                    metadata={
                        "pattern_id": str(row["id"]),
                        "pattern_name": str(row["name"]),
                        "match_score": round(match_score, 6),
                    },
                )
            )
    return anomalies


async def match_patterns_for_code_chunks(
    conn,
    *,
    bank_id: str,
    chunk_records: list[dict[str, object]],
) -> list[DetectedAnomaly]:
    if not chunk_records:
        return []

    patterns = await conn.fetch(
        f"""
        SELECT id, name, pattern_type, semantic_description, match_threshold
        FROM {fq_table("pattern_library")}
        WHERE is_active = true
          AND domain = 'code'
          AND (bank_id = $1 OR bank_id IS NULL)
        """,
        bank_id,
    )
    if not patterns:
        return []

    anomalies: list[DetectedAnomaly] = []
    for chunk in chunk_records:
        chunk_id = str(chunk["id"])
        label = str(chunk.get("label") or "")
        preview_text = str(chunk.get("preview_text") or "")
        haystack = f"{label} {preview_text}".lower()
        token_count = max(1, len(haystack.split()))
        for pattern in patterns:
            desc_tokens = [token for token in str(pattern["semantic_description"]).lower().split() if len(token) > 2]
            if not desc_tokens:
                continue
            overlap = sum(1 for token in desc_tokens if token in haystack)
            score = overlap / min(len(desc_tokens), token_count)
            if score >= float(pattern["match_threshold"] or 0.65):
                pattern_type = str(pattern["pattern_type"])
                anomaly_type = "pattern_anti_pattern" if pattern_type == "anti_pattern" else "pattern_violation"
                anomalies.append(
                    DetectedAnomaly(
                        anomaly_type=anomaly_type,
                        severity=max(0.0, min(1.0, score)),
                        unit_ids=[chunk_id],
                        description=f"Code chunk matched pattern: {pattern['name']}",
                        metadata={
                            "pattern_id": str(pattern["id"]),
                            "pattern_name": str(pattern["name"]),
                            "score": score,
                        },
                    )
                )
    return anomalies
