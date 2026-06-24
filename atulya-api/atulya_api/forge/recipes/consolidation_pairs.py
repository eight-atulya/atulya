"""consolidation_pairs recipe — facts to observations with provenance."""

from __future__ import annotations

from ..models import AtulyaTrainingRecord, ProvenanceBlock, TrainingLabels, TrainingTask
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


class ConsolidationPairsRecipe(BaseForgeRecipe):
    recipe_id = "consolidation_pairs"

    async def run(self, ctx: ForgeRecipeContext) -> RecipeResult:
        facts, observations, links = await load_bank_snapshots(ctx)
        fact_by_id = {f.id: f for f in facts}
        records: list[AtulyaTrainingRecord] = []

        for obs in observations[: ctx.max_records]:
            source_facts = [fact_by_id[sid] for sid in obs.source_memory_ids if sid in fact_by_id]
            if not source_facts:
                continue
            record = AtulyaTrainingRecord(
                record_id=new_record_id(),
                forge_job_id=ctx.forge_job_id,
                bank_id=ctx.bank_id,
                recipe_id=self.recipe_id,
                domain_tags=list(ctx.domain_tags),
                timeline=timeline_from_ingest(ctx.ingest_sessions),
                facts=source_facts,
                observations=[obs],
                links=links,
                tasks=[
                    TrainingTask(
                        task_type="consolidation",
                        query="Synthesize supporting facts into an observation",
                        metadata={"proof_count": obs.proof_count},
                    )
                ],
                labels=TrainingLabels(
                    answer=obs.text,
                    gold_answer=obs.text,
                    cited_memory_ids=[f.id for f in source_facts],
                    cited_observation_ids=[obs.id],
                    consolidation_pair={
                        "source_fact_ids": [f.id for f in source_facts],
                        "observation_id": obs.id,
                        "source_texts": [f.text for f in source_facts],
                        "observation_text": obs.text,
                    },
                ),
                provenance=ProvenanceBlock(
                    document_ids=provenance_from_facts(source_facts).document_ids,
                    chunk_ids=provenance_from_facts(source_facts).chunk_ids,
                    source_chains=[obs.source_memory_ids],
                ),
                lineage=lineage_for(ctx),
            )
            records.append(record)
        return RecipeResult(records=records)
