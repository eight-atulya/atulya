"""Database-backed LLM call tracing.

The recorder is intentionally best-effort: failures to serialize or persist a
trace row are logged at debug level and never break the user operation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator

import asyncpg

from .db_utils import acquire_with_retry

logger = logging.getLogger(__name__)


@dataclass
class LLMTraceContext:
    """Operation context shared by all LLM calls in one bank operation."""

    enabled: bool
    bank_id: str | None = None
    schema: str | None = None
    operation: str | None = None
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    max_payload_chars: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


_trace_ctx: ContextVar[LLMTraceContext | None] = ContextVar("atulya_llm_trace_context", default=None)
_request_ctx: ContextVar[dict[str, Any] | None] = ContextVar("atulya_llm_request_context", default=None)
_pool: asyncpg.pool.Pool | None = None


def init_llm_trace(pool: asyncpg.pool.Pool) -> None:
    """Initialize the trace recorder with the process database pool."""

    global _pool
    _pool = pool


def set_trace_context(ctx: LLMTraceContext) -> Token[LLMTraceContext | None]:
    """Set the current operation trace context."""

    return _trace_ctx.set(ctx)


def reset_trace_context(token: Token[LLMTraceContext | None]) -> None:
    """Reset the current operation trace context."""

    _trace_ctx.reset(token)


def current_trace_context() -> LLMTraceContext | None:
    """Return the current operation trace context, if any."""

    return _trace_ctx.get()


@contextmanager
def trace_operation(
    *,
    enabled: bool,
    bank_id: str,
    operation: str,
    schema: str | None,
    metadata: dict[str, Any] | None = None,
    max_payload_chars: int | None = None,
) -> Iterator[LLMTraceContext | None]:
    """Context manager for one traceable bank operation."""

    if not enabled:
        yield None
        return

    parent = current_trace_context()
    ctx = LLMTraceContext(
        enabled=True,
        bank_id=bank_id,
        schema=schema,
        operation=operation,
        trace_id=parent.trace_id if parent else uuid.uuid4().hex,
        max_payload_chars=max_payload_chars,
        metadata={**(parent.metadata if parent else {}), **(metadata or {})},
    )
    token = set_trace_context(ctx)
    try:
        yield ctx
    finally:
        reset_trace_context(token)


def set_request_context(ctx: dict[str, Any]) -> Token[dict[str, Any] | None]:
    """Set per-call metadata merged into the next trace row."""

    return _request_ctx.set(ctx)


def reset_request_context(token: Token[dict[str, Any] | None]) -> None:
    """Reset per-call metadata."""

    _request_ctx.reset(token)


def current_request_context() -> dict[str, Any] | None:
    """Return per-call metadata for the current task."""

    return _request_ctx.get()


def _json_default(obj: Any) -> Any:
    """Serialize common structured objects before falling back to string."""

    if isinstance(obj, datetime):
        return obj.isoformat()
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json")
        except Exception:
            return str(obj)
    return str(obj)


def _truncate_value(
    value: Any,
    *,
    max_string_chars: int,
    max_items: int,
    depth: int,
    max_depth: int,
) -> Any:
    if depth > max_depth:
        return "[truncated: max depth reached]"

    if isinstance(value, str):
        if len(value) <= max_string_chars:
            return value
        extra = len(value) - max_string_chars
        return f"{value[:max_string_chars]}...[truncated: {extra} chars]"

    if isinstance(value, list):
        out = [
            _truncate_value(
                item,
                max_string_chars=max_string_chars,
                max_items=max_items,
                depth=depth + 1,
                max_depth=max_depth,
            )
            for item in value[:max_items]
        ]
        if len(value) > max_items:
            out.append(f"[truncated: {len(value) - max_items} items]")
        return out

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        entries = list(value.items())
        for idx, (key, item) in enumerate(entries[:max_items]):
            out[str(key)] = _truncate_value(
                item,
                max_string_chars=max_string_chars,
                max_items=max_items,
                depth=depth + 1,
                max_depth=max_depth,
            )
        if len(entries) > max_items:
            out[f"[truncated: {len(entries) - max_items} items]"] = None
        return out

    return value


def _safe_json(data: Any, max_chars: int | None) -> str | None:
    if data is None:
        return None
    try:
        raw = json.dumps(data, default=_json_default, ensure_ascii=False)
    except Exception:
        try:
            raw = json.dumps(str(data), ensure_ascii=False)
        except Exception:
            return None

    if max_chars is not None and max_chars > 0 and len(raw) > max_chars:
        for max_string_chars, max_items in ((4000, 64), (2000, 48), (1000, 32), (500, 24), (250, 16)):
            try:
                payload = _truncate_value(
                    data,
                    max_string_chars=max_string_chars,
                    max_items=max_items,
                    depth=0,
                    max_depth=6,
                )
                candidate = json.dumps(
                    {"_truncated": True, "_original_chars": len(raw), "payload": payload},
                    default=_json_default,
                    ensure_ascii=False,
                )
                if len(candidate) <= max_chars:
                    return candidate
            except Exception:
                continue
        return json.dumps(
            {"_truncated": True, "_original_chars": len(raw), "preview": raw[: max(0, max_chars - 80)]},
            ensure_ascii=False,
        )

    return raw


def _table_name(schema: str | None) -> str:
    if schema:
        return f'"{schema}".llm_requests'
    return "llm_requests"


def _usage_value(usage: Any, *names: str) -> int | None:
    for name in names:
        if isinstance(usage, dict) and usage.get(name) is not None:
            return int(usage[name])
        if hasattr(usage, name) and getattr(usage, name) is not None:
            return int(getattr(usage, name))
    return None


def normalize_usage(usage: Any | None) -> dict[str, int | None]:
    """Normalize token usage across provider return types."""

    input_tokens = _usage_value(usage, "input_tokens", "prompt_tokens")
    output_tokens = _usage_value(usage, "output_tokens", "completion_tokens")
    cached_tokens = _usage_value(usage, "cached_tokens", "cached_token")
    total_tokens = _usage_value(usage, "total_tokens")
    if total_tokens is None and any(v is not None for v in (input_tokens, output_tokens, cached_tokens)):
        total_tokens = (input_tokens or 0) + (output_tokens or 0) + (cached_tokens or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "total_tokens": total_tokens,
    }


async def _insert_row(row: dict[str, Any]) -> None:
    if _pool is None:
        logger.debug("LLM trace recorder is not initialized with a database pool.")
        return

    try:
        async with acquire_with_retry(_pool) as conn:
            await conn.execute(
                f"""
                INSERT INTO {_table_name(row.get("schema"))} (
                    bank_id, operation, scope, trace_id, span_id, parent_span_id,
                    provider, model, status,
                    started_at, ended_at, duration_ms,
                    input_tokens, output_tokens, cached_tokens, total_tokens,
                    input, output, error, llm_info, metadata
                ) VALUES (
                    $1, $2, $3, $4, $5, $6,
                    $7, $8, $9,
                    $10, $11, $12,
                    $13, $14, $15, $16,
                    $17::jsonb, $18::jsonb, $19::jsonb, $20::jsonb, $21::jsonb
                )
                """,
                row.get("bank_id"),
                row.get("operation"),
                row.get("scope"),
                row.get("trace_id"),
                row.get("span_id"),
                row.get("parent_span_id"),
                row.get("provider"),
                row.get("model"),
                row.get("status"),
                row.get("started_at"),
                row.get("ended_at"),
                row.get("duration_ms"),
                row.get("input_tokens"),
                row.get("output_tokens"),
                row.get("cached_tokens"),
                row.get("total_tokens"),
                row.get("input_json"),
                row.get("output_json"),
                row.get("error_json"),
                row.get("llm_info_json") or "{}",
                row.get("metadata_json") or "{}",
            )
    except Exception:
        logger.debug("Failed to insert LLM trace row: %s", row, exc_info=True)


def _fire_and_forget(row: dict[str, Any]) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    try:
        loop.create_task(_insert_row(row))
    except Exception:
        logger.debug("Failed to schedule LLM trace insertion: %s", row, exc_info=True)


def record_llm_call(
    *,
    provider: str,
    model: str | None,
    scope: str,
    started_at: datetime,
    ended_at: datetime,
    status: str,
    input_messages: Any | None,
    output_payload: Any | None,
    error: Any | None = None,
    usage: Any | None = None,
    llm_info: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    max_payload_chars: int | None = None,
) -> None:
    """Record one completed LLM call."""

    ctx = current_trace_context()
    if ctx is None or not ctx.enabled:
        return

    effective_max_chars = ctx.max_payload_chars if ctx.max_payload_chars is not None else max_payload_chars
    normalized_usage = normalize_usage(usage)
    duration_ms = int(max(0.0, (ended_at - started_at).total_seconds() * 1000))

    row = {
        "bank_id": ctx.bank_id,
        "schema": ctx.schema,
        "operation": ctx.operation,
        "scope": scope,
        "trace_id": ctx.trace_id,
        "span_id": uuid.uuid4().hex,
        "parent_span_id": None,
        "provider": provider,
        "model": model,
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": duration_ms,
        **normalized_usage,
        "input_json": _safe_json(input_messages, effective_max_chars),
        "output_json": _safe_json(output_payload, effective_max_chars),
        "error_json": _safe_json(error, effective_max_chars),
        "llm_info_json": _safe_json({**(current_request_context() or {}), **(llm_info or {})}, effective_max_chars),
        "metadata_json": _safe_json({**ctx.metadata, **(metadata or {})}, effective_max_chars),
    }

    _fire_and_forget(row)


def new_trace_id() -> str:
    """Generate a new trace identifier."""

    return uuid.uuid4().hex


def utcnow() -> datetime:
    """Return the current UTC datetime."""

    return datetime.now(timezone.utc)
