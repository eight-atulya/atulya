"""MemoryEngine integration for Taste Studio.

Purpose
    Orchestrates Taste Studio workflows: dataset/set CRUD, transform chains,
    LLM variant generation, ATR export, and one-click retain into bank memory.
    Sits between HTTP routes (``api/http.py``) / async worker jobs and the
  ``store``, ``transforms``, ``variants``, and ``retain`` submodules.

Trigger path
    - Sync: ``taste_*`` handlers called from HTTP routes after auth.
    - Async: ``submit_taste_transform`` / ``submit_taste_generate`` enqueue
      worker tasks when batch size exceeds thresholds; worker invokes
      ``handle_taste_transform_job`` / ``handle_taste_variant_job``.

Inputs
    - ``MemoryEngine`` for pool access, tenant auth, LLM config resolution,
      and async operation submission.
    - Pydantic request models from ``.models`` (``TasteTransformRequest``, etc.).
    - ``RequestContext`` for tenant/API-key propagation into jobs.

Outputs
    - JSON-serializable dict responses for HTTP; async jobs return the same
      shape via operation result storage.
    - On persist transforms: updated ``forge_taste_sets`` rows via ``store``.

Side effects
    - PostgreSQL writes through ``store`` (sets, transform logs, variants).
    - LLM calls during transforms and variant generation.
    - ``retain_taste_sets`` creates ``memory_units`` in the target bank.
    - Async path: ``memory_engine._submit_async_operation`` inserts task rows.

Mutability
    - ``preview=True`` transforms mutate only in-memory copies of ``TasteSet``.
    - ``persist`` path appends to ``transform_log`` and overwrites
      ``working_payload``; ``source_payload`` stays immutable until revert.

Impact radius
    - Control-plane Taste Studio UI, OpenAPI taste routes, forge exporters
      (``atr_jsonl``, ``openai_chat_jsonl``), and bank memory when retain runs.
    - Changing async thresholds affects latency vs worker load tradeoff.

Core logic
    - Resolve target sets → apply transform op chain (or saved chain) per set →
      optionally persist with hashed audit log entries.
    - Export materializes sets to ATR records then delegates to forge exporters.

Failure modes
    - ``TasteNotFoundError`` / ``TasteValidationError`` for bad IDs, schema, or
      empty targets; worker jobs raise ``ValueError`` on missing ``bank_id``.
    - Unknown transform ops bubble from ``get_transform`` as validation errors.

Maintenance notes
    - Good: add a new transform op via ``transforms/registry`` without touching
      this file beyond catalog exposure.
    - Bad: bypass ``_authenticate_tenant`` in CRUD wrappers or run transforms
      without schema validation from the parent dataset.
    - ``ASYNC_TRANSFORM_THRESHOLD`` and ``ASYNC_GENERATE_WORK_THRESHOLD`` are
      tuning knobs; document changes in release notes when adjusted.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from atulya_api.forge.registry import get_exporter

from .errors import TasteNotFoundError, TasteValidationError
from .materialize import materialize_taste_sets, payload_hash
from .models import (
    CreateTasteDatasetRequest,
    ImportTasteSetsRequest,
    TasteExportRequest,
    TasteGenerateRequest,
    TasteRetainRequest,
    TasteTransformRequest,
    TransformLogEntry,
    TransformOpSpec,
    UpdateTasteDatasetRequest,
    UpdateTasteSetRequest,
)
from .retain import retain_taste_sets
from .store import (
    append_transform_log,
    create_dataset,
    create_variant_sets,
    delete_dataset,
    get_dataset,
    get_set,
    get_sets_by_ids,
    get_transform_chain,
    import_sets,
    list_all_sets,
    list_datasets,
    list_sets,
    list_transform_chains,
    revert_set,
    update_dataset,
    update_set,
)
from .transforms.base import TasteTransformContext
from .transforms.registry import get_transform, list_transform_ops
from .variants import generate_variants_for_set

if TYPE_CHECKING:
    from atulya_api.engine.memory_engine import MemoryEngine
    from atulya_api.models import RequestContext

logger = logging.getLogger(__name__)

# Sets above this count (or full-dataset transform) go through the async worker.
ASYNC_TRANSFORM_THRESHOLD = 3
# LLM work units = len(set_ids) * count; above this, variant generation is async.
ASYNC_GENERATE_WORK_THRESHOLD = 12


def _ensure_sets_in_dataset(taste_sets: list[Any], dataset_id: str) -> None:
    """Raise if any set does not belong to the requested dataset."""
    mismatched = [row.id for row in taste_sets if row.dataset_id != dataset_id]
    if mismatched:
        raise TasteValidationError(
            "All sets must belong to the requested dataset",
            field="set_ids",
            details={"dataset_id": dataset_id, "mismatched_set_ids": mismatched},
        )


async def _resolve_target_sets(
    memory_engine: "MemoryEngine",
    bank_id: str,
    dataset_id: str,
    set_ids: list[str],
) -> list[Any]:
    """Return explicit sets by ID, or all sets in the dataset when ``set_ids`` is empty."""
    if set_ids:
        taste_sets = await get_sets_by_ids(memory_engine, bank_id, set_ids)
        if len(taste_sets) != len(set_ids):
            raise TasteNotFoundError("One or more taste sets were not found")
        _ensure_sets_in_dataset(taste_sets, dataset_id)
        return taste_sets
    return await list_all_sets(memory_engine, bank_id, dataset_id)


def taste_catalog_payload() -> dict[str, Any]:
    """Build static catalog of schema types, transform ops, and taste-safe exporters."""
    from atulya_api.forge.metadata import EXPORTER_METADATA

    return {
        "schema_types": [
            {"id": "openai_chat", "title": "OpenAI chat", "description": "messages[] with role/content"},
            {"id": "qa_pair", "title": "Q&A pair", "description": "question and answer fields"},
            {"id": "custom", "title": "Custom JSON", "description": "Arbitrary JSON object"},
        ],
        "transform_ops": list_transform_ops(),
        "exporters": [
            {"adapter_id": adapter_id, **meta}
            for adapter_id, meta in EXPORTER_METADATA.items()
            if adapter_id in {"atr_jsonl", "openai_chat_jsonl"}
        ],
    }


async def _resolve_llm(memory_engine: "MemoryEngine", bank_id: str, request_context: "RequestContext"):
    """Resolve bank-hierarchical LLM config used by LLM-backed transforms."""
    config = await memory_engine._config_resolver.resolve_full_config(bank_id, request_context)
    llm_config = memory_engine._consolidation_llm_config.with_config(config)
    return llm_config, getattr(config, "llm_model", None)


async def _resolve_ops(
    memory_engine: "MemoryEngine",
    bank_id: str,
    request: TasteTransformRequest,
) -> list[TransformOpSpec]:
    """Load ops from a saved chain or inline ``request.ops``; requires one source."""
    if request.chain_id:
        chain = await get_transform_chain(memory_engine, bank_id, request.chain_id)
        return chain.ops
    if request.ops:
        return request.ops
    raise TasteValidationError("Transform requires ops[] or chain_id")


async def _apply_ops_to_set(
    memory_engine: "MemoryEngine",
    bank_id: str,
    taste_set: Any,
    *,
    schema_type: str,
    ops: list[TransformOpSpec],
    request_context: "RequestContext",
    persist: bool,
) -> dict[str, Any]:
    """Run a transform op chain on one set; persist appends audit log entries to the DB."""
    llm_config, model_name = await _resolve_llm(memory_engine, bank_id, request_context)
    ctx = TasteTransformContext(bank_id=bank_id, schema_type=schema_type, llm_config=llm_config, model_name=model_name)
    before = dict(taste_set.working_payload)
    current = taste_set
    last_model = None
    for op_spec in ops:
        try:
            transform = get_transform(op_spec.op)
        except TasteValidationError:
            raise
        result = await transform.run(ctx, current, op_spec.params)
        last_model = result.model
        if persist:
            entry = TransformLogEntry(
                op_id=op_spec.op,
                params=op_spec.params,
                before_hash=payload_hash(current.working_payload),
                after_hash=payload_hash(result.payload),
                at=datetime.now(timezone.utc),
                model=result.model,
            )
            current = await append_transform_log(
                memory_engine,
                bank_id,
                current.id,
                entry=entry,
                working_payload=result.payload,
            )
        else:
            current = current.model_copy(update={"working_payload": result.payload})
    return {
        "set_id": taste_set.id,
        "set_key": taste_set.set_key,
        "before": before,
        "after": dict(current.working_payload),
        "model": last_model,
    }


async def run_taste_transform(
    memory_engine: "MemoryEngine",
    bank_id: str,
    request: TasteTransformRequest,
    *,
    request_context: "RequestContext",
) -> dict[str, Any]:
    """Apply transform ops to target sets; ``preview`` skips DB persistence."""
    await memory_engine._authenticate_tenant(request_context)
    dataset = await get_dataset(memory_engine, bank_id, request.dataset_id)
    ops = await _resolve_ops(memory_engine, bank_id, request)
    if not ops:
        raise TasteValidationError("At least one transform op is required")

    target_sets = await _resolve_target_sets(memory_engine, bank_id, request.dataset_id, request.set_ids)
    if not target_sets:
        raise TasteValidationError("No taste sets available to transform", field="set_ids")

    items: list[dict[str, Any]] = []
    for taste_set in target_sets:
        item = await _apply_ops_to_set(
            memory_engine,
            bank_id,
            taste_set,
            schema_type=dataset.schema_type,
            ops=ops,
            request_context=request_context,
            persist=not request.preview,
        )
        items.append(item)

    return {
        "preview": request.preview,
        "items": items,
        "updated_count": 0 if request.preview else len(items),
        "processed_count": len(items),
        "total_in_dataset": len(target_sets),
    }


async def handle_taste_transform_job(memory_engine: "MemoryEngine", task_dict: dict[str, Any]) -> dict[str, Any]:
    """Worker entry point for async taste transform jobs."""
    from atulya_api.models import RequestContext

    bank_id = task_dict.get("bank_id")
    if not bank_id:
        raise ValueError("bank_id is required for taste transform job")
    request = TasteTransformRequest.model_validate(task_dict.get("taste_request") or {})
    internal_context = RequestContext(
        internal=True,
        tenant_id=task_dict.get("_tenant_id"),
        api_key_id=task_dict.get("_api_key_id"),
    )
    operation_id = task_dict.get("operation_id")
    if operation_id:
        await memory_engine._set_operation_stage(operation_id, "transform", {"set_count": len(request.set_ids)})
    result = await run_taste_transform(memory_engine, bank_id, request, request_context=internal_context)
    if operation_id:
        await memory_engine._set_operation_stage(operation_id, "persist", {"updated_count": result["updated_count"]})
    return result


async def submit_taste_transform(
    memory_engine: "MemoryEngine",
    bank_id: str,
    request: TasteTransformRequest,
    *,
    request_context: "RequestContext",
) -> dict[str, Any]:
    """Run transform inline or enqueue async job based on target set count."""
    await memory_engine._authenticate_tenant(request_context)
    if request.preview:
        return await run_taste_transform(memory_engine, bank_id, request, request_context=request_context)

    if request.set_ids:
        target_count = len(request.set_ids)
    else:
        dataset = await get_dataset(memory_engine, bank_id, request.dataset_id)
        target_count = dataset.set_count

    if target_count <= ASYNC_TRANSFORM_THRESHOLD:
        return await run_taste_transform(memory_engine, bank_id, request, request_context=request_context)

    return await memory_engine._submit_async_operation(
        bank_id=bank_id,
        operation_type="taste_transform",
        task_type="taste_transform_job",
        task_payload={
            "taste_request": request.model_dump(mode="json"),
            "_tenant_id": request_context.tenant_id,
            "_api_key_id": request_context.api_key_id,
        },
        result_metadata={"operation_stage": "queued", "dataset_id": request.dataset_id},
    )


async def run_taste_generate(
    memory_engine: "MemoryEngine",
    bank_id: str,
    dataset_id: str,
    request: TasteGenerateRequest,
    *,
    request_context: "RequestContext",
) -> dict[str, Any]:
    """LLM-generate variant sets from parent sets and persist as child rows."""
    await memory_engine._authenticate_tenant(request_context)
    dataset = await get_dataset(memory_engine, bank_id, dataset_id)
    parents = await get_sets_by_ids(memory_engine, bank_id, request.set_ids)
    if request.set_ids and len(parents) != len(request.set_ids):
        raise TasteNotFoundError("One or more taste sets were not found")
    if not parents:
        raise TasteValidationError("generate requires at least one set_id")
    _ensure_sets_in_dataset(parents, dataset_id)

    llm_config, _ = await _resolve_llm(memory_engine, bank_id, request_context)
    created_total = 0
    created_sets: list[dict[str, Any]] = []
    for parent in parents:
        variants = await generate_variants_for_set(
            llm_config=llm_config,
            schema_type=dataset.schema_type,
            taste_set=parent,
            count=request.count,
            options=request.options,
        )
        rows = await create_variant_sets(memory_engine, bank_id, parent, variants=variants)
        created_total += len(rows)
        created_sets.extend([row.model_dump(mode="json") for row in rows])

    return {
        "created_count": created_total,
        "sets": created_sets,
        "parent_count": len(parents),
        "count_per_parent": request.count,
    }


async def handle_taste_variant_job(memory_engine: "MemoryEngine", task_dict: dict[str, Any]) -> dict[str, Any]:
    """Worker entry point for async taste variant generation jobs."""
    from atulya_api.models import RequestContext

    bank_id = task_dict.get("bank_id")
    dataset_id = task_dict.get("dataset_id")
    if not bank_id or not dataset_id:
        raise ValueError("bank_id and dataset_id are required for taste variant job")
    request = TasteGenerateRequest.model_validate(task_dict.get("generate_request") or {})
    internal_context = RequestContext(
        internal=True,
        tenant_id=task_dict.get("_tenant_id"),
        api_key_id=task_dict.get("_api_key_id"),
    )
    operation_id = task_dict.get("operation_id")
    if operation_id:
        await memory_engine._set_operation_stage(operation_id, "generate", {"parent_count": len(request.set_ids)})
    result = await run_taste_generate(
        memory_engine,
        bank_id,
        dataset_id,
        request,
        request_context=internal_context,
    )
    return result


async def submit_taste_generate(
    memory_engine: "MemoryEngine",
    bank_id: str,
    dataset_id: str,
    request: TasteGenerateRequest,
    *,
    request_context: "RequestContext",
) -> dict[str, Any]:
    """Run variant generation inline or enqueue when LLM work exceeds threshold."""
    await memory_engine._authenticate_tenant(request_context)
    llm_work = len(request.set_ids) * request.count
    if llm_work <= ASYNC_GENERATE_WORK_THRESHOLD:
        return await run_taste_generate(
            memory_engine,
            bank_id,
            dataset_id,
            request,
            request_context=request_context,
        )
    return await memory_engine._submit_async_operation(
        bank_id=bank_id,
        operation_type="taste_variant",
        task_type="taste_variant_job",
        task_payload={
            "dataset_id": dataset_id,
            "generate_request": request.model_dump(mode="json"),
            "_tenant_id": request_context.tenant_id,
            "_api_key_id": request_context.api_key_id,
        },
        result_metadata={"operation_stage": "queued", "dataset_id": dataset_id},
    )


async def export_taste_dataset(
    memory_engine: "MemoryEngine",
    bank_id: str,
    request: TasteExportRequest,
    *,
    request_context: "RequestContext",
) -> dict[str, Any]:
    """Materialize taste sets to ATR records and export via a forge adapter."""
    await memory_engine._authenticate_tenant(request_context)
    dataset = await get_dataset(memory_engine, bank_id, request.dataset_id)
    if request.set_ids:
        taste_sets = await get_sets_by_ids(memory_engine, bank_id, request.set_ids)
        _ensure_sets_in_dataset(taste_sets, request.dataset_id)
    else:
        taste_sets = await list_all_sets(memory_engine, bank_id, request.dataset_id)
    if not taste_sets:
        raise TasteValidationError("No taste sets available to export")

    records = materialize_taste_sets(
        taste_sets,
        schema_type=dataset.schema_type,
        dataset_id=request.dataset_id,
        bank_id=bank_id,
    )
    try:
        exporter = get_exporter(request.adapter_id)
    except ValueError as exc:
        raise TasteValidationError(str(exc), field="adapter_id") from exc
    manifest = exporter.export(records, options=dict(request.options or {}))
    return manifest.model_dump(mode="json")


async def retain_taste_sets_request(
    memory_engine: "MemoryEngine",
    bank_id: str,
    request: TasteRetainRequest,
    *,
    request_context: "RequestContext",
) -> dict[str, Any]:
    """Retain selected taste sets into bank memory and mark sets as ``retained``."""
    await memory_engine._authenticate_tenant(request_context)
    taste_sets = await get_sets_by_ids(memory_engine, bank_id, request.set_ids)
    if len(taste_sets) != len(request.set_ids):
        raise TasteNotFoundError("One or more taste sets were not found")
    dataset_id = taste_sets[0].dataset_id
    dataset = await get_dataset(memory_engine, bank_id, dataset_id)
    if any(row.dataset_id != dataset_id for row in taste_sets):
        raise TasteValidationError("All sets must belong to the same dataset")

    return await retain_taste_sets(
        memory_engine,
        bank_id,
        taste_sets=taste_sets,
        schema_type=dataset.schema_type,
        dataset_id=dataset_id,
        request_context=request_context,
    )


# --- CRUD wrappers ---


async def taste_list_datasets(memory_engine: "MemoryEngine", bank_id: str, *, request_context: "RequestContext"):
    await memory_engine._authenticate_tenant(request_context)
    rows = await list_datasets(memory_engine, bank_id)
    return {"datasets": [row.model_dump(mode="json") for row in rows]}


async def taste_create_dataset(
    memory_engine: "MemoryEngine",
    bank_id: str,
    request: CreateTasteDatasetRequest,
    *,
    request_context: "RequestContext",
):
    await memory_engine._authenticate_tenant(request_context)
    row = await create_dataset(
        memory_engine,
        bank_id,
        name=request.name,
        description=request.description,
        schema_type=request.schema_type,
        taste_tags=request.taste_tags,
    )
    return row.model_dump(mode="json")


async def taste_get_dataset(
    memory_engine: "MemoryEngine",
    bank_id: str,
    dataset_id: str,
    *,
    request_context: "RequestContext",
):
    await memory_engine._authenticate_tenant(request_context)
    row = await get_dataset(memory_engine, bank_id, dataset_id)
    return row.model_dump(mode="json")


async def taste_update_dataset(
    memory_engine: "MemoryEngine",
    bank_id: str,
    dataset_id: str,
    request: UpdateTasteDatasetRequest,
    *,
    request_context: "RequestContext",
):
    await memory_engine._authenticate_tenant(request_context)
    row = await update_dataset(
        memory_engine,
        bank_id,
        dataset_id,
        name=request.name,
        description=request.description,
        taste_tags=request.taste_tags,
        taste_profile_json=request.taste_profile_json,
    )
    return row.model_dump(mode="json")


async def taste_delete_dataset(
    memory_engine: "MemoryEngine",
    bank_id: str,
    dataset_id: str,
    *,
    request_context: "RequestContext",
):
    await memory_engine._authenticate_tenant(request_context)
    await delete_dataset(memory_engine, bank_id, dataset_id)
    return {"deleted": True, "dataset_id": dataset_id}


async def taste_import_sets(
    memory_engine: "MemoryEngine",
    bank_id: str,
    dataset_id: str,
    request: ImportTasteSetsRequest,
    *,
    request_context: "RequestContext",
):
    await memory_engine._authenticate_tenant(request_context)
    rows = await import_sets(
        memory_engine,
        bank_id,
        dataset_id,
        sets=request.sets,
        jsonl=request.jsonl,
        taste_tags=request.taste_tags,
        set_key_prefix=request.set_key_prefix,
    )
    return {"imported_count": len(rows), "sets": [row.model_dump(mode="json") for row in rows]}


async def taste_list_sets(
    memory_engine: "MemoryEngine",
    bank_id: str,
    dataset_id: str,
    *,
    limit: int,
    offset: int,
    request_context: "RequestContext",
):
    await memory_engine._authenticate_tenant(request_context)
    return await list_sets(memory_engine, bank_id, dataset_id, limit=limit, offset=offset)


async def taste_get_set(
    memory_engine: "MemoryEngine",
    bank_id: str,
    set_id: str,
    *,
    request_context: "RequestContext",
):
    await memory_engine._authenticate_tenant(request_context)
    row = await get_set(memory_engine, bank_id, set_id)
    return row.model_dump(mode="json")


async def taste_update_set(
    memory_engine: "MemoryEngine",
    bank_id: str,
    set_id: str,
    request: UpdateTasteSetRequest,
    *,
    request_context: "RequestContext",
):
    await memory_engine._authenticate_tenant(request_context)
    row = await update_set(
        memory_engine,
        bank_id,
        set_id,
        working_payload=request.working_payload,
        taste_tags=request.taste_tags,
        status=request.status,
    )
    return row.model_dump(mode="json")


async def taste_revert_set(
    memory_engine: "MemoryEngine",
    bank_id: str,
    set_id: str,
    *,
    request_context: "RequestContext",
):
    await memory_engine._authenticate_tenant(request_context)
    row = await revert_set(memory_engine, bank_id, set_id)
    return row.model_dump(mode="json")


async def taste_list_chains(memory_engine: "MemoryEngine", bank_id: str, *, request_context: "RequestContext"):
    await memory_engine._authenticate_tenant(request_context)
    rows = await list_transform_chains(memory_engine, bank_id)
    return {"chains": [row.model_dump(mode="json") for row in rows]}
