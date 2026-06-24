"""graph_state recipe — graph intelligence labels."""

from __future__ import annotations

from ..models import (
    AtulyaTrainingRecord,
    GraphChangeEventSnapshot,
    GraphNodeSnapshot,
    GraphSnapshot,
    TrainingLabels,
    TrainingTask,
)
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


class GraphStateRecipe(BaseForgeRecipe):
    recipe_id = "graph_state"

    async def run(self, ctx: ForgeRecipeContext) -> RecipeResult:
        facts, observations, links = await load_bank_snapshots(ctx)
        from atulya_api.engine.graph_intelligence import GraphIntelligenceResponse

        graph_raw = await ctx.memory_engine.get_graph_intelligence(
            ctx.bank_id,
            limit=ctx.options.get("graph_limit", 18),
            request_context=ctx.request_context,
        )
        graph_resp = (
            graph_raw
            if isinstance(graph_raw, GraphIntelligenceResponse)
            else GraphIntelligenceResponse.model_validate(graph_raw)
        )

        nodes = [
            GraphNodeSnapshot(
                title=n.title,
                node_kind=n.kind,
                status=n.status,
                confidence=n.confidence,
                change_score=n.change_score,
                evidence_ids=list(n.evidence_ids),
            )
            for n in graph_resp.nodes
        ]
        change_events = [
            GraphChangeEventSnapshot(
                change_type=e.change_type,
                summary=e.summary,
                evidence_ids=list(e.evidence_ids),
                before_text=e.before_state,
                after_text=e.after_state,
            )
            for e in graph_resp.change_events
        ]
        graph = GraphSnapshot(
            nodes=nodes,
            edges=[e.model_dump(mode="json") for e in graph_resp.edges],
            change_events=change_events,
        )

        expected = {
            "node_titles": [n.title for n in nodes],
            "statuses": {n.title: n.status for n in nodes},
            "change_types": [e.change_type for e in change_events],
        }

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
            graph=graph,
            tasks=[TrainingTask(task_type="graph_classify", query="Classify graph node states")],
            labels=TrainingLabels(
                expected_graph=expected,
            ),
            provenance=provenance_from_facts(facts),
            lineage=lineage_for(ctx),
        )
        return RecipeResult(records=[record])
