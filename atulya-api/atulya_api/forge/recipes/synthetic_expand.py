"""synthetic_expand recipe — seed scenario + simulated sessions."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from ..adapters.scenario import ForgeScenarioAdapter
from ..models import AtulyaTrainingRecord, TrainingLabels, TrainingTask
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


class SyntheticExpandRecipe(BaseForgeRecipe):
    recipe_id = "synthetic_expand"

    async def run(self, ctx: ForgeRecipeContext) -> RecipeResult:
        sessions_count = int(ctx.options.get("sessions_count", 3))
        turns_per_session = int(ctx.options.get("turns_per_session", 4))
        persona = ctx.options.get("persona", "A knowledgeable assistant documenting operational changes over time.")
        base_date = datetime.now(timezone.utc) - timedelta(days=30)

        # Ingest seed facts if provided
        if ctx.options.get("scenario_payload"):
            adapter = ForgeScenarioAdapter()
            seed_items = adapter.normalize(ctx.options["scenario_payload"])
            await ctx.memory_engine.retain_batch_async(
                bank_id=ctx.bank_id,
                contents=[
                    {
                        "content": item["content"],
                        "context": item["context"],
                        "event_date": item["event_date"],
                        "document_id": item["document_id"],
                        **({"tags": item["tags"]} if item.get("tags") else {}),
                    }
                    for item in seed_items
                ],
                request_context=ctx.request_context,
            )
            ctx.ingest_sessions.extend(seed_items)

        generated_sessions: list[dict] = []
        for s_idx in range(sessions_count):
            event_date = base_date + timedelta(days=s_idx * 7)
            turns = []
            for t_idx in range(turns_per_session):
                role = "user" if t_idx % 2 == 0 else "assistant"
                if role == "user":
                    content = ctx.options.get(
                        "user_prompt_template",
                        f"Session {s_idx + 1}: What changed since last week regarding our operations?",
                    )
                else:
                    content = (
                        f"[{persona}] Documenting session {s_idx + 1} turn {t_idx + 1}: "
                        f"operational update recorded at {event_date.isoformat()}."
                    )
                turns.append({"role": role, "content": content})
            session = {
                "content": json.dumps(turns),
                "context": f"synthetic_expand session {s_idx + 1}",
                "event_date": event_date,
                "document_id": f"forge_synth_{uuid.uuid4().hex[:10]}",
                "tags": list(ctx.domain_tags) + ["synthetic_expand"],
            }
            generated_sessions.append(session)

        if generated_sessions:
            await ctx.memory_engine.retain_batch_async(
                bank_id=ctx.bank_id,
                contents=[
                    {
                        "content": s["content"],
                        "context": s["context"],
                        "event_date": s["event_date"],
                        "document_id": s["document_id"],
                        **({"tags": s["tags"]} if s.get("tags") else {}),
                    }
                    for s in generated_sessions
                ],
                request_context=ctx.request_context,
            )
            ctx.ingest_sessions.extend(generated_sessions)

        if ctx.options.get("wait_consolidation", True):
            from ..job import wait_for_consolidation

            await ctx.memory_engine.submit_async_consolidation(
                bank_id=ctx.bank_id,
                request_context=ctx.request_context,
            )
            await wait_for_consolidation(ctx.memory_engine, ctx.bank_id, request_context=ctx.request_context)

        facts, observations, links = await load_bank_snapshots(ctx)
        record = AtulyaTrainingRecord(
            record_id=new_record_id(),
            forge_job_id=ctx.forge_job_id,
            bank_id=ctx.bank_id,
            recipe_id=self.recipe_id,
            domain_tags=list(ctx.domain_tags),
            timeline=timeline_from_ingest(ctx.ingest_sessions),
            facts=facts,
            observations=observations,
            links=links,
            tasks=[
                TrainingTask(
                    task_type="synthetic_expand",
                    metadata={
                        "sessions_count": sessions_count,
                        "turns_per_session": turns_per_session,
                    },
                )
            ],
            labels=TrainingLabels(
                answer=f"Generated {len(generated_sessions)} synthetic sessions with {len(facts)} facts",
            ),
            provenance=provenance_from_facts(facts, adapter="synthetic_expand"),
            lineage=lineage_for(ctx),
        )
        return RecipeResult(records=[record])
