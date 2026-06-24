"""MemoryEngine forge integration."""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

from .errors import ForgeExportError, ForgeValidationError
from .job import parse_forge_request, run_forge_job
from .models import AtulyaTrainingRecord, ForgeExportRequest, ForgeJobRequest
from .registry import forge_catalog_payload, get_exporter
from .validation import validate_export_request, validate_forge_job_request

if TYPE_CHECKING:
    from atulya_api.engine.memory_engine import MemoryEngine
    from atulya_api.models import RequestContext

logger = logging.getLogger(__name__)


def _parse_operation_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ForgeValidationError(
            "Invalid operation_id. Expected a UUID.",
            field="operation_id",
            details={"operation_id": value},
        ) from exc


async def persist_forge_records(
    memory_engine: "MemoryEngine",
    *,
    operation_id: str,
    bank_id: str,
    records: list[dict[str, Any]],
) -> None:
    from atulya_api.engine.db_utils import acquire_with_retry
    from atulya_api.engine.memory_engine import fq_table

    pool = await memory_engine._get_pool()
    async with acquire_with_retry(pool) as conn:
        for record in records:
            quality = record.get("quality") or {}
            await conn.execute(
                f"""
                INSERT INTO {fq_table("forge_records")}
                    (operation_id, bank_id, record_id, recipe_id, record_json, quality_score, exportable)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
                """,
                uuid.UUID(operation_id),
                bank_id,
                record["record_id"],
                record["recipe_id"],
                json.dumps(record),
                float(quality.get("overall") or 0.0),
                bool(quality.get("exportable")),
            )


async def handle_forge_job(memory_engine: "MemoryEngine", task_dict: dict[str, Any]) -> dict[str, Any]:
    from atulya_api.models import RequestContext

    bank_id = task_dict.get("bank_id")
    operation_id = task_dict.get("operation_id")
    if not bank_id or not operation_id:
        raise ValueError("bank_id and operation_id are required for forge job")

    request_payload = task_dict.get("forge_request") or {}
    request = parse_forge_request(request_payload)
    internal_context = RequestContext(
        internal=True,
        tenant_id=task_dict.get("_tenant_id"),
        api_key_id=task_dict.get("_api_key_id"),
    )

    async def stage_callback(stage: str, extra: dict[str, Any]) -> None:
        await memory_engine._set_operation_stage(operation_id, stage, extra)

    result = await run_forge_job(
        memory_engine,
        bank_id,
        request,
        operation_id=operation_id,
        request_context=internal_context,
        stage_callback=stage_callback,
    )
    await persist_forge_records(
        memory_engine,
        operation_id=operation_id,
        bank_id=bank_id,
        records=result["records"],
    )
    return {
        "records_total": result["records_total"],
        "records_exportable": result["records_exportable"],
        "quality_summary": result["quality_summary"],
        "recipe_id": result["recipe_id"],
        "repo_commit_id": result.get("repo_commit_id"),
        "ingest_count": result.get("ingest_count", 0),
    }


async def submit_forge_job(
    memory_engine: "MemoryEngine",
    bank_id: str,
    request: ForgeJobRequest,
    *,
    request_context: "RequestContext",
) -> dict[str, Any]:
    await memory_engine._authenticate_tenant(request_context)
    validate_forge_job_request(request)
    return await memory_engine._submit_async_operation(
        bank_id=bank_id,
        operation_type="forge",
        task_type="forge_job",
        task_payload={
            "forge_request": request.model_dump(mode="json"),
            "_tenant_id": request_context.tenant_id,
            "_api_key_id": request_context.api_key_id,
        },
        result_metadata={
            "operation_stage": "queued",
            "recipe_id": request.recipe_id,
            "domain_tags": request.domain_tags,
        },
    )


async def list_forge_records_for_job(
    memory_engine: "MemoryEngine",
    bank_id: str,
    *,
    operation_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    request_context: "RequestContext",
) -> dict[str, Any]:
    from atulya_api.engine.db_utils import acquire_with_retry
    from atulya_api.engine.memory_engine import fq_table

    await memory_engine._authenticate_tenant(request_context)
    pool = await memory_engine._get_pool()
    params: list[Any] = [bank_id]
    where = "bank_id = $1"
    if operation_id:
        where += " AND operation_id = $2"
        params.append(_parse_operation_uuid(operation_id))
        limit_param = 3
        offset_param = 4
    else:
        limit_param = 2
        offset_param = 3
    params.extend([limit, offset])

    async with acquire_with_retry(pool) as conn:
        rows = await conn.fetch(
            f"""
            SELECT record_id, recipe_id, record_json, quality_score, exportable, created_at, operation_id
            FROM {fq_table("forge_records")}
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ${limit_param} OFFSET ${offset_param}
            """,
            *params,
        )
        count_row = await conn.fetchrow(
            f"SELECT COUNT(*) AS total FROM {fq_table('forge_records')} WHERE {where}",
            *params[: len(params) - 2],
        )
        exportable_row = await conn.fetchrow(
            f"SELECT COUNT(*) AS exportable FROM {fq_table('forge_records')} WHERE {where} AND exportable = true",
            *params[: len(params) - 2],
        )
    return {
        "records": [
            {
                "record_id": row["record_id"],
                "recipe_id": row["recipe_id"],
                "record": row["record_json"],
                "quality_score": row["quality_score"],
                "exportable": row["exportable"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "operation_id": str(row["operation_id"]),
            }
            for row in rows
        ],
        "total": count_row["total"] if count_row else 0,
        "exportable_total": exportable_row["exportable"] if exportable_row else 0,
        "limit": limit,
        "offset": offset,
    }


async def export_forge_job(
    memory_engine: "MemoryEngine",
    bank_id: str,
    request: ForgeExportRequest,
    *,
    request_context: "RequestContext",
) -> dict[str, Any]:
    from atulya_api.engine.db_utils import acquire_with_retry
    from atulya_api.engine.memory_engine import fq_table

    await memory_engine._authenticate_tenant(request_context)
    pool = await memory_engine._get_pool()
    async with acquire_with_retry(pool) as conn:
        rows = await conn.fetch(
            f"""
            SELECT record_json, exportable
            FROM {fq_table("forge_records")}
            WHERE bank_id = $1 AND operation_id = $2
            ORDER BY created_at ASC
            """,
            bank_id,
            _parse_operation_uuid(request.operation_id),
        )
    records = [AtulyaTrainingRecord.model_validate(row["record_json"]) for row in rows]
    exportable_count = sum(1 for row in rows if row["exportable"])
    validate_export_request(
        request,
        record_count=len(records),
        exportable_count=exportable_count,
    )

    opts = dict(request.options or {})
    if request.quality_threshold is not None:
        opts["quality_threshold"] = request.quality_threshold

    exporter = get_exporter(request.adapter_id)
    manifest = exporter.export(records, options=opts)
    if not manifest.content and manifest.exportable_count == 0:
        raise ForgeExportError(
            "Exporter produced no output. Try a different adapter or lower the quality threshold.",
            details={"adapter_id": request.adapter_id},
        )
    return manifest.model_dump(mode="json")


def forge_recipes_payload(domain_tags: list[str] | None = None) -> dict[str, Any]:
    return forge_catalog_payload(domain_tags)
