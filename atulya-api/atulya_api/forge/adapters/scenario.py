"""Normalize synthetic scenario seeds into retain batch payloads."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ..models import RetainBatchItem


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class ForgeScenarioAdapter:
    """Convert memory_to_skill-style scenario facts into dated retain items."""

    adapter_id = "scenario"

    def normalize(self, payload: dict[str, Any]) -> list[RetainBatchItem]:
        scenarios = payload.get("scenarios") or [payload]
        tags = list(payload.get("tags") or ["forge_scenario"])
        items: list[RetainBatchItem] = []

        for scenario in scenarios:
            scenario_id = scenario.get("id") or uuid.uuid4().hex[:8]
            bucket = scenario.get("bucket")
            scenario_tags = tags + ([bucket] if bucket else [])
            for fact in scenario.get("facts") or []:
                ts = _parse_datetime(fact.get("timestamp"))
                key = fact.get("key", "fact")
                value = fact.get("value", "")
                text = f"{key}: {value}"
                if fact.get("supersedes"):
                    text = f"{text} (supersedes: {', '.join(fact['supersedes'])})"
                items.append(
                    {
                        "content": text,
                        "context": scenario.get("title") or scenario.get("query") or f"scenario {scenario_id}",
                        "event_date": ts,
                        "document_id": fact.get("id") or f"forge_scenario_{scenario_id}_{uuid.uuid4().hex[:6]}",
                        "tags": scenario_tags,
                        "metadata": {
                            "scenario_id": scenario_id,
                            "fact_id": fact.get("id"),
                            "supersedes": fact.get("supersedes"),
                            "expected": scenario.get("expected"),
                            "query": scenario.get("query"),
                        },
                    }
                )
        return items
