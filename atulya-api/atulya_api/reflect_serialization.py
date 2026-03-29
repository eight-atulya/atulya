"""Helpers for serializing reflect requests and responses."""

from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from atulya_api.engine.response_models import ReflectResult


def compose_reflect_query(query: str, context: str | None) -> str:
    """Preserve the legacy context concatenation behavior for reflect requests."""
    if not context:
        return query
    return f"{query}\n\nAdditional context: {context}"


def _json_safe(value: Any) -> Any:
    """Convert nested values into JSON-safe primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, BaseModel):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return str(value)


def serialize_reflect_response(
    core_result: ReflectResult,
    *,
    include_facts: bool,
    include_tool_calls: bool,
    include_tool_call_output: bool = True,
) -> dict[str, Any]:
    """Serialize a reflect result into the public JSON response shape."""
    based_on_result: dict[str, Any] | None = None
    if include_facts:
        memories: list[dict[str, Any]] = []
        mental_models: list[dict[str, Any]] = []
        directives: list[dict[str, Any]] = []

        for fact_type, facts in core_result.based_on.items():
            if fact_type == "directives":
                for directive in facts:
                    directives.append(
                        {
                            "id": _json_safe(directive["id"]),
                            "name": directive["name"],
                            "content": directive["content"],
                        }
                    )
                continue

            if fact_type == "mental-models":
                for fact in facts:
                    mental_models.append(
                        {
                            "id": _json_safe(fact.id),
                            "text": fact.text,
                            "context": fact.context,
                        }
                    )
                continue

            for fact in facts:
                memories.append(
                    {
                        "id": _json_safe(fact.id),
                        "text": fact.text,
                        "type": fact.fact_type,
                        "context": fact.context,
                        "occurred_start": _json_safe(fact.occurred_start),
                        "occurred_end": _json_safe(fact.occurred_end),
                    }
                )

        based_on_result = {
            "memories": memories,
            "mental_models": mental_models,
            "directives": directives,
        }

    trace_result: dict[str, Any] | None = None
    if include_tool_calls:
        tool_calls = [
            {
                "tool": tool_call.tool,
                "input": _json_safe(tool_call.input),
                "output": _json_safe(tool_call.output) if include_tool_call_output else None,
                "duration_ms": tool_call.duration_ms,
                "iteration": tool_call.iteration,
            }
            for tool_call in core_result.tool_trace
        ]
        llm_calls = [
            {
                "scope": llm_call.scope,
                "duration_ms": llm_call.duration_ms,
            }
            for llm_call in core_result.llm_trace
        ]
        trace_result = {
            "tool_calls": tool_calls,
            "llm_calls": llm_calls,
        }

    return {
        "text": core_result.text,
        "based_on": based_on_result,
        "structured_output": _json_safe(core_result.structured_output),
        "usage": _json_safe(core_result.usage),
        "trace": trace_result,
    }
