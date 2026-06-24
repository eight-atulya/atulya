"""Recipe and exporter registries."""

from __future__ import annotations

from typing import Any

from .exporters import AtrJsonlExporter, GraphIntelligenceJsonlExporter, OpenAIChatJsonlExporter
from .metadata import DOMAIN_PROFILES, EXPORTER_METADATA, RECIPE_METADATA
from .recipes import (
    AgentTraceRecipe,
    BeliefUpdateRecipe,
    ConsolidationPairsRecipe,
    GraphStateRecipe,
    SyntheticExpandRecipe,
    TemporalQARecipe,
)

_RECIPES: dict[str, Any] = {
    "consolidation_pairs": ConsolidationPairsRecipe,
    "temporal_qa": TemporalQARecipe,
    "agent_trace": AgentTraceRecipe,
    "graph_state": GraphStateRecipe,
    "belief_update": BeliefUpdateRecipe,
    "synthetic_expand": SyntheticExpandRecipe,
}

_EXPORTERS: dict[str, Any] = {
    "atr_jsonl": AtrJsonlExporter,
    "openai_chat_jsonl": OpenAIChatJsonlExporter,
    "graph_intelligence_jsonl": GraphIntelligenceJsonlExporter,
}


def get_recipe(recipe_id: str):
    cls = _RECIPES.get(recipe_id)
    if cls is None:
        raise ValueError(f"Unknown forge recipe: {recipe_id}")
    return cls()


def get_exporter(adapter_id: str):
    cls = _EXPORTERS.get(adapter_id)
    if cls is None:
        raise ValueError(f"Unknown forge exporter: {adapter_id}")
    return cls()


def list_recipes() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for recipe_id, cls in _RECIPES.items():
        meta = RECIPE_METADATA.get(recipe_id, {})
        result.append(
            {
                "recipe_id": recipe_id,
                "version": getattr(cls(), "version", "1"),
                "title": meta.get("title", recipe_id),
                "description": meta.get("description") or (cls.__doc__ or "").strip(),
                "requires_ingest": meta.get("requires_ingest", False),
                "cost_tier": meta.get("cost_tier", "medium"),
                "training_signal": meta.get("training_signal"),
            }
        )
    return result


def list_exporters() -> list[dict[str, str]]:
    return [
        {
            "adapter_id": adapter_id,
            "version": "1",
            "title": EXPORTER_METADATA.get(adapter_id, {}).get("title", adapter_id),
            "description": EXPORTER_METADATA.get(adapter_id, {}).get("description", ""),
        }
        for adapter_id in _EXPORTERS
    ]


def suggest_recipes(domain_tags: list[str]) -> list[str]:
    suggestions: list[str] = []
    for tag in domain_tags:
        profile = DOMAIN_PROFILES.get(tag, {})
        for recipe in profile.get("suggested_recipes", []):
            if recipe not in suggestions and recipe in _RECIPES:
                suggestions.append(recipe)
    if not suggestions:
        suggestions = ["consolidation_pairs", "temporal_qa"]
    return suggestions


def forge_catalog_payload(domain_tags: list[str] | None = None) -> dict[str, Any]:
    tags = domain_tags or []
    profiles = [
        {"id": pid, **{k: v for k, v in meta.items() if k != "suggested_recipes"}}
        for pid, meta in DOMAIN_PROFILES.items()
    ]
    return {
        "recipes": list_recipes(),
        "exporters": list_exporters(),
        "domain_profiles": profiles,
        "suggested_recipes": suggest_recipes(tags),
        "stages": [
            {"id": "queued", "label": "Queued"},
            {"id": "ingest", "label": "Ingesting source"},
            {"id": "purify", "label": "Purifying memories"},
            {"id": "recipe", "label": "Generating training records"},
            {"id": "audit", "label": "Quality audit"},
            {"id": "repo_commit", "label": "Versioning dataset"},
        ],
    }
