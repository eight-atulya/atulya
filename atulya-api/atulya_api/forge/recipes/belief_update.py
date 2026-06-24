"""belief_update recipe — observation history chains."""

from __future__ import annotations

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


class BeliefUpdateRecipe(BaseForgeRecipe):
    recipe_id = "belief_update"

    async def run(self, ctx: ForgeRecipeContext) -> RecipeResult:
        facts, observations, links = await load_bank_snapshots(ctx)
        fact_by_id = {f.id: f for f in facts}
        records: list[AtulyaTrainingRecord] = []

        for obs in observations:
            if not obs.history:
                continue
            for entry in obs.history:
                previous_text = entry.get("previous_text")
                new_sources = [str(x) for x in (entry.get("new_source_memory_ids") or [])]
                if not previous_text:
                    continue
                source_facts = [fact_by_id[sid] for sid in new_sources if sid in fact_by_id]
                record = AtulyaTrainingRecord(
                    record_id=new_record_id(),
                    forge_job_id=ctx.forge_job_id,
                    bank_id=ctx.bank_id,
                    recipe_id=self.recipe_id,
                    domain_tags=list(ctx.domain_tags),
                    timeline=timeline_from_ingest(ctx.ingest_sessions),
                    facts=source_facts or facts[:10],
                    observations=[obs],
                    links=links,
                    tasks=[TrainingTask(task_type="belief_update", query="Update belief from new evidence")],
                    labels=TrainingLabels(
                        answer=obs.text,
                        belief_update={
                            "previous_text": previous_text,
                            "updated_text": obs.text,
                            "new_source_memory_ids": new_sources,
                            "changed_at": entry.get("changed_at"),
                        },
                        cited_memory_ids=new_sources,
                        cited_observation_ids=[obs.id],
                    ),
                    provenance=provenance_from_facts(source_facts or facts[:10]),
                    lineage=lineage_for(ctx),
                )
                records.append(record)
                if len(records) >= ctx.max_records:
                    break
            if len(records) >= ctx.max_records:
                break

        return RecipeResult(records=records)
