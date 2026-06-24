"""agent_trace recipe — full reflect tool traces."""

from __future__ import annotations

from datetime import datetime, timezone

from ..models import AtulyaTrainingRecord, ToolTraceStep, TrainingLabels, TrainingTask
from ..utils import memory_ids_from_reflect, mental_model_ids_from_reflect, observation_ids_from_reflect
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


class AgentTraceRecipe(BaseForgeRecipe):
    recipe_id = "agent_trace"

    async def run(self, ctx: ForgeRecipeContext) -> RecipeResult:
        facts, observations, links = await load_bank_snapshots(ctx)
        queries = list(ctx.options.get("queries") or [])
        if not queries:
            queries = [q for q in (ctx.options.get("qa_pairs") or []) if q.get("question")]
        if not queries:
            for obs in observations[:5]:
                queries.append({"question": f"Explain: {obs.text[:200]}"})

        records: list[AtulyaTrainingRecord] = []
        for qa in queries[: ctx.max_records]:
            question = qa["question"]
            question_date = qa.get("question_date")
            if isinstance(question_date, str):
                question_date = datetime.fromisoformat(question_date.replace("Z", "+00:00"))
            elif question_date is None:
                question_date = datetime.now(timezone.utc)

            reflect_result = await ctx.memory_engine.reflect_async(
                bank_id=ctx.bank_id,
                query=question,
                max_tokens=4096,
                response_schema=ctx.options.get("response_schema"),
                request_context=ctx.request_context,
            )

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
                tasks=[TrainingTask(task_type="agent_trace", query=question)],
                labels=TrainingLabels(
                    answer=reflect_result.text,
                    cited_memory_ids=memory_ids_from_reflect(reflect_result.based_on or {}),
                    cited_observation_ids=observation_ids_from_reflect(reflect_result.based_on or {}),
                    cited_mental_model_ids=mental_model_ids_from_reflect(reflect_result.based_on or {}),
                    tool_trace=tool_trace,
                    structured_output=reflect_result.structured_output,
                ),
                provenance=provenance_from_facts(facts),
                lineage=lineage_for(ctx),
            )
            records.append(record)
        return RecipeResult(records=records)
