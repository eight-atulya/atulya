"""Shared forge helpers."""

from __future__ import annotations

from typing import Any


def memory_ids_from_reflect(based_on: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for fact_type in ("world", "experience", "opinion", "observation"):
        for item in based_on.get(fact_type) or []:
            if isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))
    return ids


def observation_ids_from_reflect(based_on: dict[str, Any]) -> list[str]:
    return [
        str(item["id"]) for item in (based_on.get("observation") or []) if isinstance(item, dict) and item.get("id")
    ]


def mental_model_ids_from_reflect(based_on: dict[str, Any]) -> list[str]:
    return [
        str(item["id"]) for item in (based_on.get("mental_models") or []) if isinstance(item, dict) and item.get("id")
    ]
