"""Base types for forge recipes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ..models import (
    AtulyaTrainingRecord,
    FactSnapshot,
    LineageBlock,
    LinkSnapshot,
    ObsSnapshot,
    ProvenanceBlock,
    TimelineEpisode,
    TimelineSession,
    TimelineTurn,
    TrainingLabels,
    TrainingTask,
)

if TYPE_CHECKING:
    from atulya_api.engine.memory_engine import MemoryEngine
    from atulya_api.models import RequestContext


@dataclass
class ForgeRecipeContext:
    memory_engine: "MemoryEngine"
    bank_id: str
    forge_job_id: str
    recipe_id: str
    domain_tags: list[str]
    request_context: "RequestContext"
    options: dict[str, Any] = field(default_factory=dict)
    max_records: int = 500
    ingest_sessions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RecipeResult:
    records: list[AtulyaTrainingRecord] = field(default_factory=list)


class BaseForgeRecipe:
    recipe_id: str = "base"
    version: str = "1"

    async def run(self, ctx: ForgeRecipeContext) -> RecipeResult:
        raise NotImplementedError


def new_record_id() -> str:
    return str(uuid.uuid4())


def lineage_for(
    ctx: ForgeRecipeContext, *, snapshot_hash: str | None = None, commit_id: str | None = None
) -> LineageBlock:
    return LineageBlock(
        snapshot_hash=snapshot_hash,
        repo_commit_id=commit_id,
        recipe_id=ctx.recipe_id,
        recipe_version="1",
    )


def timeline_from_ingest(sessions: list[dict[str, Any]]) -> TimelineEpisode:
    episode = TimelineEpisode()
    for session in sessions:
        turns_raw = []
        content = session.get("content")
        if isinstance(content, str):
            import json

            try:
                turns_raw = json.loads(content)
            except json.JSONDecodeError:
                turns_raw = [{"role": "user", "content": content}]
        event_date = session.get("event_date")
        if isinstance(event_date, str):
            event_date = datetime.fromisoformat(event_date.replace("Z", "+00:00"))
        elif event_date is None:
            event_date = datetime.now(timezone.utc)
        turns = [
            TimelineTurn(
                role=t.get("role", "user"),
                content=t.get("content", ""),
                speaker=t.get("speaker"),
            )
            for t in turns_raw
        ]
        episode.sessions.append(
            TimelineSession(
                session_id=session.get("document_id") or new_record_id(),
                event_date=event_date,
                context=session.get("context"),
                document_id=session.get("document_id"),
                tags=list(session.get("tags") or []),
                turns=turns,
            )
        )
    return episode


async def load_bank_snapshots(
    ctx: ForgeRecipeContext,
) -> tuple[list[FactSnapshot], list[ObsSnapshot], list[LinkSnapshot]]:
    """Load facts, observations, and links from the bank."""
    from atulya_api.engine.db_utils import acquire_with_retry
    from atulya_api.engine.memory_engine import fq_table

    pool = await ctx.memory_engine._get_pool()
    facts: list[FactSnapshot] = []
    observations: list[ObsSnapshot] = []
    links: list[LinkSnapshot] = []

    async with acquire_with_retry(pool) as conn:
        fact_rows = await conn.fetch(
            f"""
            SELECT id, text, fact_type, context, occurred_start, occurred_end, mentioned_at, tags, chunk_id, document_id
            FROM {fq_table("memory_units")}
            WHERE bank_id = $1 AND fact_type IN ('world', 'experience')
            ORDER BY COALESCE(mentioned_at, created_at) ASC
            LIMIT $2
            """,
            ctx.bank_id,
            ctx.max_records * 10,
        )
        for row in fact_rows:
            facts.append(
                FactSnapshot(
                    id=str(row["id"]),
                    text=row["text"],
                    fact_type=row["fact_type"],
                    context=row["context"],
                    occurred_start=row["occurred_start"],
                    occurred_end=row["occurred_end"],
                    mentioned_at=row["mentioned_at"],
                    tags=list(row["tags"] or []),
                    chunk_id=row["chunk_id"],
                    document_id=str(row["document_id"]) if row["document_id"] else None,
                )
            )

        obs_rows = await conn.fetch(
            f"""
            SELECT id, text, proof_count, source_memory_ids, tags, history
            FROM {fq_table("memory_units")}
            WHERE bank_id = $1 AND fact_type = 'observation'
            ORDER BY created_at ASC
            LIMIT $2
            """,
            ctx.bank_id,
            ctx.max_records * 5,
        )
        for row in obs_rows:
            history = row["history"] or []
            if isinstance(history, str):
                import json

                history = json.loads(history)
            source_ids = [str(x) for x in (row["source_memory_ids"] or [])]
            observations.append(
                ObsSnapshot(
                    id=str(row["id"]),
                    text=row["text"],
                    proof_count=int(row["proof_count"] or 0),
                    source_memory_ids=source_ids,
                    tags=list(row["tags"] or []),
                    history=list(history) if history else [],
                )
            )

        if facts:
            unit_ids = [f.id for f in facts]
            link_rows = await conn.fetch(
                f"""
                SELECT from_unit_id, to_unit_id, link_type, weight, entity_id
                FROM {fq_table("memory_links")}
                WHERE from_unit_id = ANY($1::uuid[])
                LIMIT 5000
                """,
                unit_ids,
            )
            for row in link_rows:
                links.append(
                    LinkSnapshot(
                        from_unit_id=str(row["from_unit_id"]),
                        to_unit_id=str(row["to_unit_id"]),
                        link_type=row["link_type"],
                        weight=float(row["weight"]),
                        entity_id=str(row["entity_id"]) if row["entity_id"] else None,
                    )
                )

    return facts, observations, links


def provenance_from_facts(facts: list[FactSnapshot], *, adapter: str | None = None) -> ProvenanceBlock:
    doc_ids = sorted({f.document_id for f in facts if f.document_id})
    chunk_ids = sorted({f.chunk_id for f in facts if f.chunk_id})
    chains = [obs.source_memory_ids for obs in []]
    return ProvenanceBlock(
        document_ids=[d for d in doc_ids if d],
        chunk_ids=[c for c in chunk_ids if c],
        source_chains=chains,
        ingest_adapter=adapter,
    )
