"""
Flaw detection over causal and opinion structures.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from atulya_api.engine.anomaly_models import DetectedAnomaly
from atulya_api.engine.embedding_similarity import cosine_similarity, parse_embedding_text
from atulya_api.engine.memory_engine import fq_table


def _detect_cycle(adjacency: dict[str, set[str]]) -> list[list[str]]:
    visited: set[str] = set()
    stack: set[str] = set()
    path: list[str] = []
    cycles: list[list[str]] = []

    def dfs(node: str) -> None:
        visited.add(node)
        stack.add(node)
        path.append(node)
        for neighbor in adjacency.get(node, set()):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in stack:
                try:
                    start = path.index(neighbor)
                    cycles.append(path[start:] + [neighbor])
                except ValueError:
                    continue
        stack.discard(node)
        path.pop()

    for node in list(adjacency.keys()):
        if node not in visited:
            dfs(node)
    return cycles


async def detect_flaws(
    conn,
    *,
    bank_id: str,
    unit_ids: list[str],
) -> list[DetectedAnomaly]:
    if not unit_ids:
        return []

    anomalies: list[DetectedAnomaly] = []

    link_rows = await conn.fetch(
        f"""
        SELECT from_unit_id, to_unit_id, weight
        FROM {fq_table("memory_links")}
        WHERE link_type = 'caused_by'
          AND (from_unit_id = ANY($1::uuid[]) OR to_unit_id = ANY($1::uuid[]))
        """,
        unit_ids,
    )
    adjacency: dict[str, set[str]] = defaultdict(set)
    causal_pairs: list[tuple[str, str, float]] = []
    for row in link_rows:
        source = str(row["from_unit_id"])
        target = str(row["to_unit_id"])
        adjacency[source].add(target)
        causal_pairs.append((source, target, float(row["weight"] or 1.0)))

    for cycle in _detect_cycle(adjacency):
        anomalies.append(
            DetectedAnomaly(
                anomaly_type="flaw_circular",
                severity=1.0,
                unit_ids=cycle,
                description="Circular causal reasoning detected.",
                metadata={"cycle": cycle},
            )
        )

    if causal_pairs:
        rows = await conn.fetch(
            f"""
            SELECT id, occurred_start, embedding::text AS embedding_text
            FROM {fq_table("memory_units")}
            WHERE id = ANY($1::uuid[])
            """,
            list({unit_id for pair in causal_pairs for unit_id in (pair[0], pair[1])}),
        )
        row_map = {str(row["id"]): row for row in rows}
        for source, target, _ in causal_pairs:
            source_row = row_map.get(source)
            target_row = row_map.get(target)
            if not source_row or not target_row:
                continue

            source_time = source_row["occurred_start"]
            target_time = target_row["occurred_start"]
            if isinstance(source_time, datetime) and isinstance(target_time, datetime) and source_time > target_time:
                delta_seconds = (source_time - target_time).total_seconds()
                severity = max(0.0, min(1.0, delta_seconds / (7 * 86400)))
                anomalies.append(
                    DetectedAnomaly(
                        anomaly_type="flaw_temporal_violation",
                        severity=severity,
                        unit_ids=[source, target],
                        description="Cause occurs after effect in causal link.",
                        metadata={"delta_seconds": delta_seconds},
                    )
                )

            similarity = cosine_similarity(
                parse_embedding_text(source_row["embedding_text"]),
                parse_embedding_text(target_row["embedding_text"]),
            )
            if similarity is not None and similarity < 0.30:
                anomalies.append(
                    DetectedAnomaly(
                        anomaly_type="flaw_missing_step",
                        severity=0.5,
                        unit_ids=[source, target],
                        description="Causal relation appears to skip intermediate steps.",
                        metadata={"similarity": round(similarity, 6)},
                    )
                )

    opinion_rows = await conn.fetch(
        f"""
        SELECT id, embedding::text AS embedding_text
        FROM {fq_table("memory_units")}
        WHERE bank_id = $1
          AND id = ANY($2::uuid[])
          AND fact_type = 'opinion'
          AND embedding IS NOT NULL
        """,
        bank_id,
        unit_ids,
    )
    for row in opinion_rows:
        support = await conn.fetchval(
            f"""
            SELECT id
            FROM {fq_table("memory_units")}
            WHERE bank_id = $1
              AND fact_type = ANY($2::text[])
              AND embedding IS NOT NULL
              AND id != $3::uuid
              AND embedding <=> $4::vector < 0.40
            LIMIT 1
            """,
            bank_id,
            ["world", "experience"],
            row["id"],
            row["embedding_text"],
        )
        if support is None:
            anomalies.append(
                DetectedAnomaly(
                    anomaly_type="flaw_unsupported_opinion",
                    severity=0.4,
                    unit_ids=[str(row["id"])],
                    description="Opinion memory has no nearby evidence support.",
                    metadata={},
                )
            )
    return anomalies
