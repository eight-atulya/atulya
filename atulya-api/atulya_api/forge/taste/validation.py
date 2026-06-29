"""Validation helpers for Taste Studio payloads.

Purpose
    Enforce schema-specific payload shape at import and manual set update time.
    Centralizes rules so HTTP, store, and engine share one validation path.

Trigger path
    - ``store.import_sets`` and ``store.update_set`` when ``working_payload`` changes.
    - ``parse_import_sets`` during bulk import (JSONL or inline sets).

Inputs
    - ``schema_type``: ``openai_chat``, ``qa_pair``, or ``custom``.
    - Payload dicts or JSONL string (mutually exclusive with inline sets).

Outputs
    - ``validate_payload_for_schema``: None on success; raises on failure.
    - ``parse_import_sets``: list of validated payload dicts.

Side effects
    None — pure validation.

Mutability
    Input payloads are read-only; callers own the returned list.

Impact radius
    - All taste import/update error messages seen by operators.
    - ``MAX_IMPORT_ROWS`` caps bulk import size per request.

Core logic
    - Per-schema required fields (messages[], question/answer, non-empty custom).
    - JSONL: one JSON object per non-empty line, max 500 rows.

Failure modes
    - ``TasteValidationError`` with ``field`` hint for API error mapping.

Maintenance notes
    - Good: add a new ``schema_type`` with explicit rules here and in catalog.
    - Bad: skip validation in a new code path that writes ``working_payload``.
"""

from __future__ import annotations

import json
from typing import Any

from .errors import TasteValidationError
from .models import TasteSchemaType

MAX_IMPORT_ROWS = 500


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def validate_payload_for_schema(payload: dict[str, Any], schema_type: TasteSchemaType) -> None:
    """Raise ``TasteValidationError`` if payload does not match ``schema_type`` rules."""
    if schema_type == "openai_chat":
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise TasteValidationError("openai_chat payload requires non-empty messages[]", field="messages")
        for idx, msg in enumerate(messages):
            if not isinstance(msg, dict):
                raise TasteValidationError(f"messages[{idx}] must be an object", field="messages")
            if not _non_empty_str(msg.get("role")) or not _non_empty_str(msg.get("content")):
                raise TasteValidationError(f"messages[{idx}] requires non-empty role and content", field="messages")
        return
    if schema_type == "qa_pair":
        if not _non_empty_str(payload.get("question")) or not _non_empty_str(payload.get("answer")):
            raise TasteValidationError("qa_pair payload requires non-empty question and answer", field="question")
        return
    if schema_type == "custom":
        if not payload:
            raise TasteValidationError("custom payload cannot be empty", field="payload")
        return
    raise TasteValidationError(f"Unknown schema_type: {schema_type}", field="schema_type")


def parse_import_sets(
    *,
    schema_type: TasteSchemaType,
    sets: list[dict[str, Any]] | None = None,
    jsonl: str | None = None,
) -> list[dict[str, Any]]:
    """Parse and validate import input; ``jsonl`` and ``sets`` are mutually exclusive."""
    has_jsonl = bool(jsonl and jsonl.strip())
    has_sets = bool(sets)
    if has_jsonl and has_sets:
        raise TasteValidationError("Provide either jsonl or sets[], not both", field="jsonl")

    payloads: list[dict[str, Any]] = []
    if has_jsonl:
        for line_no, line in enumerate(jsonl.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise TasteValidationError(f"Invalid JSONL on line {line_no}: {exc}", field="jsonl") from exc
            if not isinstance(row, dict):
                raise TasteValidationError(f"JSONL line {line_no} must be a JSON object", field="jsonl")
            validate_payload_for_schema(row, schema_type)
            payloads.append(row)
    if has_sets:
        for idx, row in enumerate(sets):
            if not isinstance(row, dict):
                raise TasteValidationError(f"sets[{idx}] must be an object", field="sets")
            validate_payload_for_schema(row, schema_type)
            payloads.append(row)
    if not payloads:
        raise TasteValidationError("Import requires sets[] or jsonl content", field="sets")
    if len(payloads) > MAX_IMPORT_ROWS:
        raise TasteValidationError(
            f"Import exceeds maximum of {MAX_IMPORT_ROWS} rows per request",
            field="sets",
            details={"row_count": len(payloads), "max_rows": MAX_IMPORT_ROWS},
        )
    return payloads
