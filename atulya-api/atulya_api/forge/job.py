"""Forge job orchestration.

Purpose
    Execute the staged Data Forge pipeline: optional ingest retain, consolidation
    wait, recipe materialization, quality audit, and optional memory-repo commit.

Trigger path
    - ``forge/engine.handle_forge_job`` (async worker) calls ``run_forge_job``.
    - ``stage_callback`` reports progress to operation stage tracking.

Inputs
    - ``ForgeJobRequest`` with recipe_id, ingest source, quality threshold.
    - ``operation_id`` becomes ``forge_job_id`` on each ATR record.
    - ``RequestContext`` for tenant auth and retain/consolidation calls.

Outputs
    - Dict with audited record JSON, quality summary, exportable count, optional
      ``repo_commit_id``.

Side effects
    - ``retain_batch_async`` when ingest sessions present.
    - ``submit_async_consolidation`` + poll when ``wait_consolidation``.
    - Recipe may read bank DB via ``ForgeRecipeContext``.
    - Optional ``commit_memory_repo`` snapshot on completion.

Mutability
    - ``audited`` records get ``lineage.repo_commit_id`` mutated in-place when
      repo commit succeeds.

Impact radius
    - Entire forge job lifecycle, ``forge_records`` persistence, training exports.

Core logic
    Stages: ingest → purify (consolidation) → recipe → audit → [repo_commit].

Failure modes
    - ``TimeoutError`` if consolidation pending exceeds 300s.
    - Zero records logs warning but returns success with empty list.

Maintenance notes
    - Good: add a stage via ``set_stage`` without changing return contract.
    - Bad: skip consolidation when recipe depends on observations.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from .errors import ForgeValidationError
from .models import AtulyaTrainingRecord, ForgeJobRequest
from .quality import audit_record, summarize_quality
from .recipes.base import ForgeRecipeContext
from .registry import get_recipe
from .validation import normalize_ingest_source_sync, validate_forge_job_request

if TYPE_CHECKING:
    from atulya_api.engine.memory_engine import MemoryEngine
    from atulya_api.models import RequestContext

logger = logging.getLogger(__name__)


async def normalize_ingest_source(source: dict[str, Any] | None) -> list[dict[str, Any]]:
    return normalize_ingest_source_sync(source)


async def wait_for_consolidation(
    memory_engine: "MemoryEngine",
    bank_id: str,
    *,
    request_context: "RequestContext",
    poll_interval: float = 2.0,
    timeout: float = 300.0,
) -> None:
    """Poll bank stats until ``pending_consolidation`` reaches zero or timeout."""
    start = time.time()
    while True:
        if time.time() - start > timeout:
            raise TimeoutError(f"Consolidation did not complete within {timeout}s")
        stats = await memory_engine.get_bank_stats(bank_id, request_context=request_context)
        pending = int(stats.get("pending_consolidation") or 0)
        if pending == 0:
            return
        await asyncio.sleep(poll_interval)


async def run_forge_job(
    memory_engine: "MemoryEngine",
    bank_id: str,
    request: ForgeJobRequest,
    *,
    operation_id: str,
    request_context: "RequestContext",
    stage_callback: Any | None = None,
) -> dict[str, Any]:
    """Run full forge pipeline; ``stage_callback(stage, extra)`` is optional progress hook."""
    async def set_stage(stage: str, extra: dict[str, Any] | None = None) -> None:
        if stage_callback:
            await stage_callback(stage, extra or {})

    ingest_sessions = validate_forge_job_request(request)

    await set_stage("ingest", {"ingest_count": len(ingest_sessions)})
    if ingest_sessions:
        contents = []
        for item in ingest_sessions:
            entry: dict[str, Any] = {
                "content": item["content"],
                "context": item.get("context", "forge ingest"),
                "event_date": item.get("event_date"),
                "document_id": item.get("document_id"),
            }
            if item.get("tags"):
                entry["tags"] = item["tags"]
            contents.append(entry)
        await memory_engine.retain_batch_async(
            bank_id=bank_id,
            contents=contents,
            request_context=request_context,
        )

    await set_stage("purify")
    if request.wait_consolidation:
        await memory_engine.submit_async_consolidation(bank_id=bank_id, request_context=request_context)
        await wait_for_consolidation(memory_engine, bank_id, request_context=request_context)

    await set_stage("recipe", {"recipe_id": request.recipe_id})
    recipe = get_recipe(request.recipe_id)
    ctx = ForgeRecipeContext(
        memory_engine=memory_engine,
        bank_id=bank_id,
        forge_job_id=operation_id,
        recipe_id=request.recipe_id,
        domain_tags=list(request.domain_tags),
        request_context=request_context,
        options=dict(request.options),
        max_records=request.max_records,
        ingest_sessions=ingest_sessions,
    )
    result = await recipe.run(ctx)
    records = result.records

    if not records:
        logger.warning("Forge recipe %s produced zero records for bank %s", request.recipe_id, bank_id)

    await set_stage("audit")
    audited: list[AtulyaTrainingRecord] = []
    for record in records:
        audited.append(audit_record(record, threshold=request.quality_threshold))

    repo_commit_id: str | None = None
    if request.repo_commit_on_complete:
        await set_stage("repo_commit")
        repo_commit_id = await _commit_repo_snapshot(
            memory_engine,
            bank_id,
            message=request.commit_message or f"forge:{request.recipe_id}",
            request_context=request_context,
        )
        for record in audited:
            if record.lineage:
                record.lineage.repo_commit_id = repo_commit_id

    quality_summary = summarize_quality(audited)
    return {
        "records": [r.model_dump(mode="json") for r in audited],
        "quality_summary": quality_summary,
        "records_total": len(audited),
        "records_exportable": int(quality_summary.get("exportable", 0)),
        "repo_commit_id": repo_commit_id,
        "recipe_id": request.recipe_id,
        "ingest_count": len(ingest_sessions),
    }


async def _commit_repo_snapshot(
    memory_engine: "MemoryEngine",
    bank_id: str,
    *,
    message: str,
    request_context: "RequestContext",
) -> str | None:
    try:
        repo = await memory_engine.get_memory_repo_for_bank(bank_id, request_context=request_context)
    except Exception:
        logger.info("No repo enabled for bank %s; skipping forge commit", bank_id)
        return None
    if not repo or not repo.get("repo_id"):
        return None
    commit = await memory_engine.commit_memory_repo(
        repo_id=str(repo["repo_id"]),
        message=message,
        request_context=request_context,
    )
    return str(commit.get("commit_id") or commit.get("id") or "")


def parse_forge_request(payload: dict[str, Any]) -> ForgeJobRequest:
    try:
        return ForgeJobRequest.model_validate(payload)
    except Exception as exc:
        raise ForgeValidationError(f"Invalid forge job request: {exc}", field="request") from exc
