"""Shared forge helpers.

Purpose
    Extract memory, observation, and mental-model IDs from reflect ``based_on``
    payloads when building training label citation fields in agent_trace and
    related recipes.

Trigger path
    - Called from forge recipes (e.g. ``agent_trace``, ``temporal_qa``) when
      mapping reflect evidence to ``TrainingLabels.cited_*_ids``.

Inputs
    - ``based_on`` dict shaped like reflect response evidence groupings.

Outputs
    - Deduplication is caller responsibility; these return flat ID lists.

Side effects
    None.

Mutability
    Input dict is read-only.

Impact radius
    - Citation validity in quality audit depends on correct ID extraction.

Maintenance notes
    - ``memory_ids_from_reflect`` includes world, experience, opinion, and
      observation fact types; do not add observation twice via both helpers.
"""

from __future__ import annotations

from typing import Any


def memory_ids_from_reflect(based_on: dict[str, Any]) -> list[str]:
    """Collect memory unit IDs from world, experience, opinion, and observation buckets."""
    ids: list[str] = []
    for fact_type in ("world", "experience", "opinion", "observation"):
        for item in based_on.get(fact_type) or []:
            if isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))
    return ids


def observation_ids_from_reflect(based_on: dict[str, Any]) -> list[str]:
    """Collect observation memory unit IDs only (subset of memory_ids_from_reflect)."""
    return [
        str(item["id"]) for item in (based_on.get("observation") or []) if isinstance(item, dict) and item.get("id")
    ]


def mental_model_ids_from_reflect(based_on: dict[str, Any]) -> list[str]:
    """Collect mental model IDs from reflect based_on payload."""
    return [
        str(item["id"]) for item in (based_on.get("mental_models") or []) if isinstance(item, dict) and item.get("id")
    ]
