"""Human-readable forge recipe, exporter, and domain metadata."""

from __future__ import annotations

from typing import Any

RECIPE_METADATA: dict[str, dict[str, Any]] = {
    "consolidation_pairs": {
        "title": "Consolidation pairs",
        "description": "Facts → observations with full source_memory_ids provenance. Best for summarization fine-tunes.",
        "requires_ingest": False,
        "cost_tier": "low",
        "training_signal": "Abstraction / summarization",
    },
    "temporal_qa": {
        "title": "Temporal Q&A",
        "description": "Multi-hop questions with recall + reflect and cited memory IDs. Mirrors LongMemEval-style eval.",
        "requires_ingest": False,
        "cost_tier": "medium",
        "training_signal": "Temporal reasoning with citations",
    },
    "agent_trace": {
        "title": "Agent traces",
        "description": "Full reflect tool traces (recall, expand, done) for agentic fine-tuning.",
        "requires_ingest": False,
        "cost_tier": "high",
        "training_signal": "Multi-step memory agent behavior",
    },
    "graph_state": {
        "title": "Graph state labels",
        "description": "Graph intelligence node statuses (stable/changed/contradictory/stale) as training labels.",
        "requires_ingest": False,
        "cost_tier": "low",
        "training_signal": "Graph classification",
    },
    "belief_update": {
        "title": "Belief updates",
        "description": "Observation history chains: before/after text when new evidence arrives.",
        "requires_ingest": False,
        "cost_tier": "low",
        "training_signal": "Knowledge-update fine-tuning",
    },
    "synthetic_expand": {
        "title": "Synthetic expand",
        "description": "Seed scenario facts then generate multi-session timelines. Requires scenario source.",
        "requires_ingest": True,
        "ingest_hint": "Provide a scenario source with dated facts, or pass scenario_payload in options.",
        "cost_tier": "high",
        "training_signal": "Synthetic multi-session timelines",
    },
}

EXPORTER_METADATA: dict[str, dict[str, str]] = {
    "atr_jsonl": {
        "title": "ATR JSONL",
        "description": "Canonical Atulya Training Record format — future-proof archive.",
    },
    "openai_chat_jsonl": {
        "title": "OpenAI chat JSONL",
        "description": "messages[] format for OpenAI / compatible SFT pipelines.",
    },
    "graph_intelligence_jsonl": {
        "title": "Graph intelligence JSONL",
        "description": "Compatible with graph_intelligence_ft test/export schema.",
    },
}

DOMAIN_PROFILES: dict[str, dict[str, Any]] = {
    "startup_ops": {
        "title": "Startup ops",
        "description": "Customer calls, deals, incidents, product decisions.",
        "suggested_recipes": ["agent_trace", "temporal_qa", "consolidation_pairs"],
    },
    "family_office": {
        "title": "Family office",
        "description": "Holdings, beneficiaries, advisors, compliance events.",
        "suggested_recipes": ["belief_update", "temporal_qa", "graph_state"],
    },
    "macro": {
        "title": "Macro / world",
        "description": "Economic indicators, geopolitical events, time-series facts.",
        "suggested_recipes": ["belief_update", "graph_state", "consolidation_pairs"],
    },
    "social": {
        "title": "Social / web",
        "description": "High-volume feeds, posts, and conversational streams.",
        "suggested_recipes": ["consolidation_pairs", "temporal_qa"],
    },
    "synthetic": {
        "title": "Synthetic",
        "description": "Generate multi-session timelines from seed scenarios.",
        "suggested_recipes": ["synthetic_expand", "graph_state"],
    },
}

BANK_ONLY_RECIPES = frozenset(
    {
        "consolidation_pairs",
        "temporal_qa",
        "agent_trace",
        "graph_state",
        "belief_update",
    }
)

FORGE_STAGES = [
    {"id": "queued", "label": "Queued"},
    {"id": "ingest", "label": "Ingesting source"},
    {"id": "purify", "label": "Purifying memories"},
    {"id": "recipe", "label": "Generating training records"},
    {"id": "audit", "label": "Quality audit"},
    {"id": "repo_commit", "label": "Versioning dataset"},
]
