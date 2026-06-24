"""Validate forge ingest sources and job requests before execution."""

from __future__ import annotations

from typing import Any

from .adapters import ForgeChatAdapter, ForgeScenarioAdapter, ForgeTimeSeriesAdapter
from .errors import ForgeExportError, ForgeValidationError
from .metadata import BANK_ONLY_RECIPES, RECIPE_METADATA
from .models import ForgeExportRequest, ForgeIngestSource, ForgeJobRequest
from .registry import get_exporter

_KNOWN_SOURCE_TYPES = frozenset({"chat", "timeseries", "scenario", "sessions", "bank_only"})


def normalize_ingest_source_sync(source: dict[str, Any] | ForgeIngestSource | None) -> list[dict[str, Any]]:
    """Normalize ingest source to retain batch items (sync, for validation)."""
    if source is None:
        return []
    if isinstance(source, ForgeIngestSource):
        payload = source.model_dump(mode="python")
    else:
        payload = source

    source_type = payload.get("source_type")
    if source_type == "bank_only":
        return []

    if source_type not in _KNOWN_SOURCE_TYPES:
        raise ForgeValidationError(
            f"Unknown source_type '{source_type}'. Use one of: {', '.join(sorted(_KNOWN_SOURCE_TYPES))}.",
            field="source.source_type",
        )

    inner = payload.get("payload") or {}
    try:
        if source_type == "chat":
            return ForgeChatAdapter().normalize(inner)
        if source_type == "timeseries":
            return ForgeTimeSeriesAdapter().normalize(inner)
        if source_type == "scenario":
            return ForgeScenarioAdapter().normalize(inner)
        if source_type == "sessions":
            sessions = list(inner.get("sessions") or [])
            if not sessions:
                raise ForgeValidationError(
                    "sessions payload is empty — add at least one session with content.",
                    field="source.payload.sessions",
                )
            return sessions
    except ValueError as exc:
        raise ForgeValidationError(str(exc), field="source.payload") from exc

    return []


def validate_ingest_source(source: dict[str, Any] | ForgeIngestSource | None) -> list[dict[str, Any]]:
    """Validate and normalize ingest source; raises ForgeValidationError on failure."""
    items = normalize_ingest_source_sync(source)
    if source is not None:
        src = source if isinstance(source, dict) else source.model_dump()
        source_type = src.get("source_type")
        if source_type and source_type != "bank_only" and not items:
            raise ForgeValidationError(
                "Source parsed successfully but produced zero retain items. Check your payload shape.",
                field="source.payload",
            )
    return items


def validate_forge_job_request(request: ForgeJobRequest) -> list[dict[str, Any]]:
    """Validate a forge job request before queueing."""
    meta = RECIPE_METADATA.get(request.recipe_id)
    if meta is None:
        raise ForgeValidationError(f"Unknown recipe '{request.recipe_id}'.", field="recipe_id")

    ingest_items: list[dict[str, Any]] = []
    if request.source is not None:
        ingest_items = validate_ingest_source(request.source)

    requires_ingest = bool(meta.get("requires_ingest"))
    if requires_ingest and not ingest_items:
        if request.recipe_id == "synthetic_expand" and request.options.get("scenario_payload"):
            pass
        else:
            raise ForgeValidationError(
                meta.get("ingest_hint") or f"Recipe '{request.recipe_id}' requires a source payload.",
                field="source",
            )

    if request.recipe_id not in BANK_ONLY_RECIPES and not ingest_items and request.source is None:
        # Warn-level: allowed but user should know bank must already have memories
        pass

    return ingest_items


def validate_export_request(
    request: ForgeExportRequest,
    *,
    record_count: int,
    exportable_count: int,
) -> None:
    """Validate export can proceed."""
    get_exporter(request.adapter_id)  # raises ValueError if unknown
    if record_count == 0:
        raise ForgeExportError(
            "No training records found for this job. Run forge again or pick a different recipe.",
            details={"operation_id": request.operation_id},
        )
    if exportable_count == 0 and request.quality_threshold is not None:
        raise ForgeExportError(
            "No records pass the quality threshold. Lower the threshold or improve source data.",
            details={"operation_id": request.operation_id, "quality_threshold": request.quality_threshold},
        )
