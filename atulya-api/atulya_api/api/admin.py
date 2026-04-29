"""
Admin API router for atulya-api.

Provides superuser-gated endpoints for tenant management, worker control,
API key CRUD, and system health.  All routes require is_superuser=True.

Mount via create_app() when ATULYA_API_ADMIN_ENABLED=true.

PCRM metadata:
{
  "component": "admin-api",
  "security_model": "RBAC + ABAC via TenantContext",
  "auth_dependency": "require_superuser",
  "default_state": "disabled (ATULYA_API_ADMIN_ENABLED=false)"
}
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from atulya_api.extensions.tenant import TenantContext
from atulya_api.models import RequestContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic models (response + request)
# All field names match DB column names where applicable.
# ---------------------------------------------------------------------------


class SystemHealthResponse(BaseModel):
    status: str
    api_version: str
    db_pool_min: int
    db_pool_max: int
    db_pool_size: int
    db_pool_free: int
    migration_version: str | None
    worker_count: int
    admin_schema: str


class TenantSummaryResponse(BaseModel):
    schema_name: str
    bank_count: int


class WorkerStatusResponse(BaseModel):
    worker_id: str
    schema_name: str
    pending_count: int
    stuck_count: int
    last_seen_at: str | None


class DecommissionRequest(BaseModel):
    release_stuck: bool = Field(
        default=True,
        description="Re-queue stuck tasks so another worker can pick them up (default: true).",
    )


class DecommissionResponse(BaseModel):
    worker_id: str
    released_count: int


class OperationSummaryResponse(BaseModel):
    operation_id: str
    bank_id: str
    schema_name: str
    operation_type: str
    status: str
    worker_id: str | None
    created_at: str
    updated_at: str | None
    error_message: str | None


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., description="Human-readable label for this key")
    role: str = Field(default="user", description="Role: superuser | admin | user")
    schema_name: str = Field(default="public", description="PostgreSQL schema this key operates in")
    allowed_bank_ids: list[str] | None = Field(
        default=None,
        description="Restrict access to specific banks. None = unrestricted.",
    )
    expires_days: int | None = Field(
        default=None,
        description="Days until key expires. None = never expires.",
    )


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    role: str
    schema_name: str
    allowed_bank_ids: list[str] | None
    created_at: str
    expires_at: str | None
    revoked_at: str | None
    # raw_key is only present in create responses — never stored, never returned again.
    raw_key: str | None = None


class ApiKeyUpdateRequest(BaseModel):
    name: str | None = None
    role: str | None = None
    allowed_bank_ids: list[str] | None = None


# ---------------------------------------------------------------------------
# Auth dependencies
# ---------------------------------------------------------------------------


def _extract_api_key(authorization: str | None) -> str | None:
    if not authorization:
        return None
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return authorization.strip()


async def _resolve_tenant_context(
    request_context: RequestContext,
    memory: Any,
) -> TenantContext:
    """
    Resolve TenantContext for admin endpoints.

    Admin auth is SELF-CONTAINED: always checks ATULYA_API_SUPERUSER_KEY
    directly via hmac.compare_digest — independent of whichever TenantExtension
    is configured on the MemoryEngine. This means admin works even with
    DefaultTenantExtension (the default).

    Flow:
      1. Key present + matches config.superuser_key → role="superuser"
      2. Key present + no superuser key configured → 403
      3. Key absent → 401
    """
    from atulya_api.config import get_config

    config = get_config()
    provided_key = request_context.api_key

    if not provided_key:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="API key required for admin access")

    superuser_key = config.superuser_key
    if not superuser_key:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=503,
            detail="Admin is enabled but ATULYA_API_SUPERUSER_KEY is not configured",
        )

    if not hmac.compare_digest(provided_key.encode(), superuser_key.encode()):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Superuser access required")

    schema = config.superuser_schema or "public"
    return TenantContext(schema_name=schema, role="superuser")


def create_admin_router(memory: Any) -> APIRouter:
    """
    Build and return the admin APIRouter.

    Called once in create_app() when admin_enabled=True.
    The router captures the memory engine via closure — same pattern as
    the main http.py _register_routes() function.
    """
    router = APIRouter()

    # ------------------------------------------------------------------
    # Shared dependency: verify superuser + return TenantContext
    # ------------------------------------------------------------------

    def get_request_context(
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> RequestContext:
        # Prefer X-Api-Key header; fall back to Authorization: Bearer <key>
        key = x_api_key or _extract_api_key(authorization)
        return RequestContext(api_key=key)

    async def require_superuser(
        request_context: RequestContext = Depends(get_request_context),
    ) -> TenantContext:
        """FastAPI dependency — raises 401/403 for missing/non-superuser key."""
        # _resolve_tenant_context raises HTTPException directly (401/403/503).
        return await _resolve_tenant_context(request_context, memory)

    # ------------------------------------------------------------------
    # GET /v1/admin/system/health
    # ------------------------------------------------------------------

    @router.get(
        "/system/health",
        response_model=SystemHealthResponse,
        summary="Admin system health",
        description="Returns DB pool stats, migration version, and active worker count.",
        tags=["Admin"],
        operation_id="admin_system_health",
    )
    async def admin_system_health(
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> SystemHealthResponse:
        from atulya_api import __version__

        pool = await memory._get_pool()

        # Migration version
        migration_version: str | None = None
        try:
            row = await pool.fetchrow("SELECT version_num FROM alembic_version LIMIT 1")
            if row:
                migration_version = row["version_num"]
        except Exception:
            pass

        # Stuck/active worker count from async_operations
        worker_count = 0
        try:
            row = await pool.fetchrow(
                "SELECT COUNT(DISTINCT worker_id) AS cnt FROM async_operations WHERE worker_id IS NOT NULL AND status = 'pending'"
            )
            if row:
                worker_count = row["cnt"] or 0
        except Exception:
            pass

        return SystemHealthResponse(
            status="healthy",
            api_version=__version__,
            db_pool_min=pool.get_min_size(),
            db_pool_max=pool.get_max_size(),
            db_pool_size=pool.get_size(),
            db_pool_free=pool.get_idle_size(),
            migration_version=migration_version,
            worker_count=worker_count,
            admin_schema=tenant_ctx.schema_name,
        )

    # ------------------------------------------------------------------
    # GET /v1/admin/tenants
    # ------------------------------------------------------------------

    @router.get(
        "/tenants",
        response_model=list[TenantSummaryResponse],
        summary="List all tenants",
        description="Returns all tenants known to the tenant extension with bank counts.",
        tags=["Admin"],
        operation_id="admin_list_tenants",
    )
    async def admin_list_tenants(
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> list[TenantSummaryResponse]:
        tenant_ext = memory.tenant_extension
        if tenant_ext is None:
            return [TenantSummaryResponse(schema_name=tenant_ctx.schema_name, bank_count=0)]

        tenants = await tenant_ext.list_tenants()
        pool = await memory._get_pool()

        result: list[TenantSummaryResponse] = []
        for t in tenants:
            try:
                row = await pool.fetchrow(f"SELECT COUNT(*) AS cnt FROM {t.schema}.banks")
                bank_count = row["cnt"] if row else 0
            except Exception:
                bank_count = 0
            result.append(TenantSummaryResponse(schema_name=t.schema, bank_count=bank_count))

        return result

    # ------------------------------------------------------------------
    # GET /v1/admin/tenants/{schema}/banks
    # ------------------------------------------------------------------

    @router.get(
        "/tenants/{schema}/banks",
        summary="List banks in a tenant schema",
        description="Returns all bank IDs and names within the specified tenant schema.",
        tags=["Admin"],
        operation_id="admin_list_tenant_banks",
    )
    async def admin_list_tenant_banks(
        schema: str,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> list[dict[str, Any]]:
        pool = await memory._get_pool()
        try:
            rows = await pool.fetch(
                f"SELECT bank_id, name, created_at::text, updated_at::text FROM {schema}.banks ORDER BY created_at DESC"
            )
            return [dict(r) for r in rows]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Cannot list banks in schema '{schema}': {exc}")

    # ------------------------------------------------------------------
    # GET /v1/admin/workers
    # ------------------------------------------------------------------

    @router.get(
        "/workers",
        response_model=list[WorkerStatusResponse],
        summary="List active workers",
        description="Lists workers with pending/stuck operation counts from async_operations.",
        tags=["Admin"],
        operation_id="admin_list_workers",
    )
    async def admin_list_workers(
        schema: str = Query(default="public", description="Schema to inspect"),
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> list[WorkerStatusResponse]:
        pool = await memory._get_pool()
        fq = f"{schema}.async_operations"
        try:
            rows = await pool.fetch(
                f"""
                SELECT
                    worker_id,
                    COUNT(*) FILTER (WHERE status = 'pending') AS pending_count,
                    COUNT(*) FILTER (WHERE status = 'pending' AND updated_at < NOW() - INTERVAL '5 minutes') AS stuck_count,
                    MAX(updated_at)::text AS last_seen_at
                FROM {fq}
                WHERE worker_id IS NOT NULL
                GROUP BY worker_id
                ORDER BY last_seen_at DESC NULLS LAST
                """
            )
            return [
                WorkerStatusResponse(
                    worker_id=r["worker_id"],
                    schema_name=schema,
                    pending_count=r["pending_count"],
                    stuck_count=r["stuck_count"],
                    last_seen_at=r["last_seen_at"],
                )
                for r in rows
            ]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # ------------------------------------------------------------------
    # POST /v1/admin/workers/{worker_id}/decommission
    # ------------------------------------------------------------------

    @router.post(
        "/workers/{worker_id}/decommission",
        response_model=DecommissionResponse,
        summary="Decommission a worker",
        description=(
            "Release all tasks claimed by the specified worker so another worker can pick them up. "
            "Use worker_id='__all_stuck__' to release all tasks with no active worker."
        ),
        tags=["Admin"],
        operation_id="admin_decommission_worker",
    )
    async def admin_decommission_worker(
        worker_id: str,
        body: DecommissionRequest,
        schema: str = Query(default="public"),
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> DecommissionResponse:
        pool = await memory._get_pool()
        fq = f"{schema}.async_operations"

        if worker_id == "__all_stuck__":
            # Release all pending tasks with no assigned worker and last updated > 5 min ago.
            result = await pool.execute(
                f"""
                UPDATE {fq}
                SET worker_id = NULL, status = 'pending', updated_at = NOW()
                WHERE status = 'pending'
                  AND (worker_id IS NULL OR updated_at < NOW() - INTERVAL '5 minutes')
                """,
            )
        elif body.release_stuck:
            result = await pool.execute(
                f"""
                UPDATE {fq}
                SET worker_id = NULL, status = 'pending', updated_at = NOW()
                WHERE worker_id = $1 AND status = 'pending'
                """,
                worker_id,
            )
        else:
            # Just clear worker claim without re-queuing (leave as pending, detach worker_id).
            result = await pool.execute(
                f"UPDATE {fq} SET worker_id = NULL WHERE worker_id = $1",
                worker_id,
            )

        released = int(result.split()[-1]) if result else 0
        logger.info("[ADMIN] decommission worker=%s schema=%s released=%d", worker_id, schema, released)
        return DecommissionResponse(worker_id=worker_id, released_count=released)

    # ------------------------------------------------------------------
    # GET /v1/admin/operations
    # ------------------------------------------------------------------

    @router.get(
        "/operations",
        response_model=list[OperationSummaryResponse],
        summary="List operations across all tenants",
        description="Returns recent async operations across all tenant schemas visible to the superuser.",
        tags=["Admin"],
        operation_id="admin_list_operations",
    )
    async def admin_list_operations(
        schema: str = Query(default="public"),
        status: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> list[OperationSummaryResponse]:
        pool = await memory._get_pool()
        fq = f"{schema}.async_operations"

        where = ""
        params: list[Any] = []
        if status:
            params.append(status)
            where = f"WHERE status = ${len(params)}"

        params.append(limit)
        try:
            rows = await pool.fetch(
                f"""
                SELECT
                    operation_id::text, bank_id, operation_type, status,
                    worker_id, created_at::text, updated_at::text, error_message
                FROM {fq}
                {where}
                ORDER BY created_at DESC
                LIMIT ${len(params)}
                """,
                *params,
            )
            return [
                OperationSummaryResponse(
                    operation_id=r["operation_id"],
                    bank_id=r["bank_id"],
                    schema_name=schema,
                    operation_type=r["operation_type"],
                    status=r["status"],
                    worker_id=r["worker_id"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    error_message=r["error_message"],
                )
                for r in rows
            ]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # ------------------------------------------------------------------
    # POST /v1/admin/consolidate/{schema}
    # ------------------------------------------------------------------

    @router.post(
        "/consolidate/{schema}",
        summary="Trigger consolidation for all banks in a schema",
        description="Enqueues a consolidation task for every bank in the given schema.",
        tags=["Admin"],
        operation_id="admin_trigger_consolidation",
    )
    async def admin_trigger_consolidation(
        schema: str,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> dict[str, Any]:
        pool = await memory._get_pool()

        try:
            bank_rows = await pool.fetch(f"SELECT bank_id FROM {schema}.banks")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Cannot list banks in schema '{schema}': {exc}")

        queued: list[str] = []
        for row in bank_rows:
            bid = row["bank_id"]
            rc = RequestContext(internal=True)
            try:
                result = await memory.submit_async_consolidation(bank_id=bid, request_context=rc)
                queued.append(result["operation_id"])
            except Exception as exc:
                logger.warning("[ADMIN] consolidation queue failed bank=%s: %s", bid, exc)

        return {"schema": schema, "queued_count": len(queued), "operation_ids": queued}

    # ------------------------------------------------------------------
    # API Key management
    # NOTE: Requires the api_keys table (T7 migration).
    #       All routes return 503 if the table doesn't exist yet.
    # ------------------------------------------------------------------

    def _hash_key(raw_key: str) -> str:
        """SHA-256 hex digest used as the stored key_hash."""
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def _verify_key(raw_key: str, stored_hash: str) -> bool:
        return hmac.compare_digest(_hash_key(raw_key), stored_hash)

    async def _ensure_api_keys_table(pool: Any, schema: str) -> None:
        exists = await pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema=$1 AND table_name='api_keys')",
            schema,
        )
        if not exists:
            raise HTTPException(
                status_code=503,
                detail="api_keys table does not exist. Run 'atulya-admin migrate' to apply pending migrations.",
            )

    @router.get(
        "/api-keys",
        response_model=list[ApiKeyResponse],
        summary="List API keys",
        description="Returns all API keys (redacted — raw key is never returned after creation).",
        tags=["Admin"],
        operation_id="admin_list_api_keys",
    )
    async def admin_list_api_keys(
        schema: str = Query(default="public"),
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> list[ApiKeyResponse]:
        pool = await memory._get_pool()
        await _ensure_api_keys_table(pool, schema)
        rows = await pool.fetch(
            f"""
            SELECT id::text, name, role, schema_name, allowed_bank_ids,
                   created_at::text, expires_at::text, revoked_at::text
            FROM {schema}.api_keys
            ORDER BY created_at DESC
            """
        )
        return [
            ApiKeyResponse(
                id=r["id"],
                name=r["name"],
                role=r["role"],
                schema_name=r["schema_name"],
                allowed_bank_ids=list(r["allowed_bank_ids"]) if r["allowed_bank_ids"] else None,
                created_at=r["created_at"],
                expires_at=r["expires_at"],
                revoked_at=r["revoked_at"],
            )
            for r in rows
        ]

    @router.post(
        "/api-keys",
        response_model=ApiKeyResponse,
        status_code=201,
        summary="Create API key",
        description=(
            "Creates a new API key and returns the raw key **once**. Store it securely — it cannot be retrieved again."
        ),
        tags=["Admin"],
        operation_id="admin_create_api_key",
    )
    async def admin_create_api_key(
        body: ApiKeyCreateRequest,
        schema: str = Query(default="public"),
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> ApiKeyResponse:
        pool = await memory._get_pool()
        await _ensure_api_keys_table(pool, schema)

        # Validate role
        valid_roles = {"superuser", "admin", "user"}
        if body.role not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}")

        raw_key = f"atulya_{secrets.token_urlsafe(32)}"
        key_hash = _hash_key(raw_key)

        expires_at = None
        if body.expires_days:
            from datetime import timedelta

            expires_at = (datetime.now(timezone.utc) + timedelta(days=body.expires_days)).isoformat()

        key_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        await pool.execute(
            f"""
            INSERT INTO {schema}.api_keys
                (id, key_hash, name, role, schema_name, allowed_bank_ids, created_at, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW(), $7)
            """,
            uuid.UUID(key_id),
            key_hash,
            body.name,
            body.role,
            body.schema_name,
            body.allowed_bank_ids,
            expires_at,
        )
        logger.info("[ADMIN] created api_key id=%s name=%s role=%s", key_id, body.name, body.role)

        return ApiKeyResponse(
            id=key_id,
            name=body.name,
            role=body.role,
            schema_name=body.schema_name,
            allowed_bank_ids=body.allowed_bank_ids,
            created_at=now,
            expires_at=expires_at,
            revoked_at=None,
            raw_key=raw_key,  # Only present on creation response
        )

    @router.patch(
        "/api-keys/{key_id}",
        response_model=ApiKeyResponse,
        summary="Update API key",
        description="Update name, role, or allowed_bank_ids for an existing key.",
        tags=["Admin"],
        operation_id="admin_update_api_key",
    )
    async def admin_update_api_key(
        key_id: str,
        body: ApiKeyUpdateRequest,
        schema: str = Query(default="public"),
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> ApiKeyResponse:
        pool = await memory._get_pool()
        await _ensure_api_keys_table(pool, schema)

        set_clauses: list[str] = []
        params: list[Any] = [uuid.UUID(key_id)]

        if body.name is not None:
            params.append(body.name)
            set_clauses.append(f"name = ${len(params)}")
        if body.role is not None:
            valid_roles = {"superuser", "admin", "user"}
            if body.role not in valid_roles:
                raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}")
            params.append(body.role)
            set_clauses.append(f"role = ${len(params)}")
        if body.allowed_bank_ids is not None:
            params.append(body.allowed_bank_ids)
            set_clauses.append(f"allowed_bank_ids = ${len(params)}")

        if not set_clauses:
            raise HTTPException(status_code=422, detail="No fields provided to update")

        row = await pool.fetchrow(
            f"""
            UPDATE {schema}.api_keys
            SET {", ".join(set_clauses)}
            WHERE id = $1 AND revoked_at IS NULL
            RETURNING id::text, name, role, schema_name, allowed_bank_ids,
                      created_at::text, expires_at::text, revoked_at::text
            """,
            *params,
        )
        if not row:
            raise HTTPException(status_code=404, detail=f"API key '{key_id}' not found or already revoked")

        return ApiKeyResponse(
            id=row["id"],
            name=row["name"],
            role=row["role"],
            schema_name=row["schema_name"],
            allowed_bank_ids=list(row["allowed_bank_ids"]) if row["allowed_bank_ids"] else None,
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            revoked_at=row["revoked_at"],
        )

    @router.delete(
        "/api-keys/{key_id}",
        summary="Revoke API key",
        description="Soft-deletes an API key by setting revoked_at. The key is immediately inactive.",
        tags=["Admin"],
        operation_id="admin_revoke_api_key",
    )
    async def admin_revoke_api_key(
        key_id: str,
        schema: str = Query(default="public"),
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> dict[str, str]:
        pool = await memory._get_pool()
        await _ensure_api_keys_table(pool, schema)

        result = await pool.execute(
            f"UPDATE {schema}.api_keys SET revoked_at = NOW() WHERE id = $1 AND revoked_at IS NULL",
            uuid.UUID(key_id),
        )
        revoked = int(result.split()[-1]) if result else 0
        if revoked == 0:
            raise HTTPException(status_code=404, detail=f"API key '{key_id}' not found or already revoked")

        logger.info("[ADMIN] revoked api_key id=%s", key_id)
        return {"status": "revoked", "id": key_id}

    return router
