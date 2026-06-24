"""temporal_qa recipe — recall + reflect at query anchor."""

from __future__ import annotations

from datetime import datetime, timezone

from ..models import (
    AtulyaTrainingRecord,
    ToolTraceStep,
    TrainingLabels,
    TrainingTask,
)
from ..utils import memory_ids_from_reflect
from .base import (
    BaseForgeRecipe,
    ForgeRecipeContext,
    RecipeResult,
    lineage_for,
    load_bank_snapshots,
    new_record_id,
    provenance_from_facts,
    timeline_from_ingest,
)


class TemporalQARecipe(BaseForgeRecipe):
    recipe_id = "temporal_qa"

    async def run(self, ctx: ForgeRecipeContext) -> RecipeResult:
        facts, observations, links = await load_bank_snapshots(ctx)
        queries: list[dict] = list(ctx.options.get("qa_pairs") or [])

        if not queries and ctx.ingest_sessions:
            for session in ctx.ingest_sessions:
                meta = session.get("metadata") or {}
                if meta.get("query"):
                    queries.append(
                        {
                            "question": meta["query"],
                            "answer": (meta.get("expected") or {}).get("answer"),
                            "question_date": session.get("event_date"),
                            "category": "temporal-reasoning",
                        }
                    )

        if not queries:
            timeline_data = await ctx.memory_engine.get_timeline(
                ctx.bank_id,
                limit=min(20, ctx.max_records),
                request_context=ctx.request_context,
            )
            for item in (timeline_data.get("items") or [])[: ctx.max_records]:
                text = item.get("text") or ""
                if text:
                    queries.append(
                        {
                            "question": f"What do we know about: {text[:120]}?",
                            "answer": None,
                            "question_date": item.get("mentioned_at") or item.get("occurred_start"),
                            "category": "single-hop",
                        }
                    )

        records: list[AtulyaTrainingRecord] = []
        for qa in queries[: ctx.max_records]:
            question = qa["question"]
            question_date = qa.get("question_date")
            if isinstance(question_date, str):
                question_date = datetime.fromisoformat(question_date.replace("Z", "+00:00"))
            elif question_date is None:
                question_date = datetime.now(timezone.utc)

            recall_result = await ctx.memory_engine.recall_async(
                bank_id=ctx.bank_id,
                query=question,
                max_tokens=2048,
                question_date=question_date,
                request_context=ctx.request_context,
            )
            reflect_result = await ctx.memory_engine.reflect_async(
                bank_id=ctx.bank_id,
                query=question,
                max_tokens=2048,
                request_context=ctx.request_context,
            )

            cited_ids = memory_ids_from_reflect(reflect_result.based_on or {})
            tool_trace = [
                ToolTraceStep(
                    tool=step.tool,
                    reason=step.reason,
                    input=dict(step.input),
                    output=dict(step.output),
                    duration_ms=step.duration_ms,
                    iteration=step.iteration,
                )
                for step in (reflect_result.tool_trace or [])
            ]

            record = AtulyaTrainingRecord(
                record_id=new_record_id(),
                forge_job_id=ctx.forge_job_id,
                bank_id=ctx.bank_id,
                recipe_id=self.recipe_id,
                domain_tags=list(ctx.domain_tags),
                timeline=timeline_from_ingest(ctx.ingest_sessions),
                query_anchor=question_date,
                facts=facts[:50],
                observations=observations[:20],
                links=links,
                tasks=[
                    TrainingTask(
                        task_type="temporal_qa",
                        query=question,
                        category=qa.get("category"),
                        metadata={"recall_count": len(recall_result.results or [])},
                    )
                ],
                labels=TrainingLabels(
                    answer=reflect_result.text,
                    gold_answer=qa.get("answer"),
                    cited_memory_ids=cited_ids,
                    tool_trace=tool_trace,
                ),
                provenance=provenance_from_facts(facts),
                lineage=lineage_for(ctx),
            )
            records.append(record)
        return RecipeResult(records=records)
