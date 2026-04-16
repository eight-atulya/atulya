"""Load ordered observation sequence for an entity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atulya_api.engine.embedding_similarity import parse_embedding_text
from atulya_api.engine.memory_engine import fq_table

if TYPE_CHECKING:
    import asyncpg

from atulya_api.engine.entity_trajectory.models import TrajectoryObservation


async def fetch_observations_for_entity(
    conn: "asyncpg.Connection",
    *,
    bank_id: str,
    entity_id: str,
    max_facts: int,
) -> list[TrajectoryObservation]:
    """
    Memory units linked to entity, oldest-first for narrative progression.

    Ordering: COALESCE(occurred_start, event_date, created_at), then id.
    """
    rows = await conn.fetch(
        f"""
        SELECT mu.id::text AS unit_id,
               mu.text AS fact_text,
               mu.fact_type::text AS fact_type,
               COALESCE(mu.occurred_start, mu.event_date, mu.created_at) AS occurred_sort_at,
               mu.embedding::text AS embedding_text
        FROM {fq_table("memory_units")} mu
        INNER JOIN {fq_table("unit_entities")} ue ON ue.unit_id = mu.id
        WHERE ue.entity_id = $1::uuid
          AND mu.bank_id = $2
          AND mu.embedding IS NOT NULL
        ORDER BY COALESCE(mu.occurred_start, mu.event_date, mu.created_at) ASC, mu.id ASC
        LIMIT $3
        """,
        entity_id,
        bank_id,
        max_facts,
    )
    out: list[TrajectoryObservation] = []
    for row in rows:
        emb_text = row["embedding_text"]
        if not emb_text:
            continue
        emb = parse_embedding_text(str(emb_text))
        if emb is None:
            continue
        out.append(
            TrajectoryObservation(
                unit_id=str(row["unit_id"]),
                fact_text=str(row["fact_text"] or "")[:8000],
                fact_type=str(row["fact_type"] or "world"),
                occurred_sort_at=row["occurred_sort_at"],
                embedding=emb,
            )
        )
    return out


async def fetch_prior_vocabulary(
    conn: "asyncpg.Connection",
    *,
    bank_id: str,
    entity_id: str,
) -> list[str] | None:
    row = await conn.fetchrow(
        f"""
        SELECT state_vocabulary
        FROM {fq_table("entity_trajectories")}
        WHERE bank_id = $1 AND entity_id = $2::uuid
        """,
        bank_id,
        entity_id,
    )
    if not row or row["state_vocabulary"] is None:
        return None
    raw = row["state_vocabulary"]
    if isinstance(raw, str):
        import json

        raw = json.loads(raw)
    if not isinstance(raw, list):
        return None
    return [str(x) for x in raw]
