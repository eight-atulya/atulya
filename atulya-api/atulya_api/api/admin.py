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

import asyncio
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

from atulya_api.auth import (
    ALL_ACTIONS,
    fq,
    generate_api_key,
    hash_password,
    hash_secret,
    key_prefix,
    normalize_org_slug,
    schema_for_org,
)
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


class OrgCreateRequest(BaseModel):
    slug: str
    name: str
    owner_email: str
    owner_password: str = Field(min_length=12)
    owner_name: str | None = None


class OrgResponse(BaseModel):
    id: str
    slug: str
    name: str
    schema_name: str
    status: str
    created_at: str


class PrincipalCreateRequest(BaseModel):
    org_id: str
    email: str | None = None
    display_name: str
    principal_type: str = Field(default="user", description="user | service")
    role: str = Field(default="admin", description="owner | admin | operator | viewer | service")
    password: str | None = Field(default=None, min_length=12)


class PrincipalResponse(BaseModel):
    id: str
    org_id: str
    email: str | None
    display_name: str
    principal_type: str
    role: str
    status: str
    created_at: str


class PasswordResetRequest(BaseModel):
    password: str = Field(min_length=12)


class AccessGrantRequest(BaseModel):
    org_id: str
    subject_type: str = Field(description="principal | role")
    subject_id: str
    action: str
    scope_type: str = Field(description="org | bank | system")
    scope_id: str


class AccessGrantResponse(BaseModel):
    id: str
    org_id: str
    subject_type: str
    subject_id: str
    action: str
    scope_type: str
    scope_id: str
    created_at: str


class AuditEventResponse(BaseModel):
    id: str
    org_id: str | None
    actor_principal_id: str | None
    action: str
    target_type: str | None
    target_id: str | None
    result: str
    metadata: dict[str, Any]
    created_at: str


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
    principal_id: str | None = None
    description: str | None = None


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    role: str
    schema_name: str
    allowed_bank_ids: list[str] | None
    created_at: str
    expires_at: str | None
    revoked_at: str | None
    principal_id: str | None = None
    key_prefix: str | None = None
    last_used_at: str | None = None
    description: str | None = None
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

    async def _audit(
        *,
        org_id: str | None,
        actor_principal_id: str | None,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        result: str = "success",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            pool = await memory._get_pool()
            await pool.execute(
                f"""
                INSERT INTO {fq("audit_events")} (org_id, actor_principal_id, action, target_type, target_id, result, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                uuid.UUID(org_id) if org_id else None,
                uuid.UUID(actor_principal_id) if actor_principal_id else None,
                action,
                target_type,
                target_id,
                result,
                metadata or {},
            )
        except Exception:
            logger.debug("[ADMIN] failed to write audit event", exc_info=True)

    async def _run_schema_migration(schema_name: str) -> None:
        from atulya_api.migrations import run_migrations

        db_url = getattr(memory, "db_url", None)
        if not db_url:
            raise HTTPException(status_code=503, detail="Database URL unavailable for schema migration")
        await asyncio.to_thread(run_migrations, db_url, schema=schema_name)

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
    # Org / principal / grant management
    # ------------------------------------------------------------------

    @router.get("/orgs", response_model=list[OrgResponse], tags=["Admin"], operation_id="admin_list_orgs")
    async def admin_list_orgs(
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> list[OrgResponse]:
        pool = await memory._get_pool()
        rows = await pool.fetch(
            f"SELECT id::text, slug, name, schema_name, status, created_at::text FROM {fq('orgs')} ORDER BY created_at DESC"
        )
        return [OrgResponse(**dict(r)) for r in rows]

    @router.post("/orgs", response_model=OrgResponse, status_code=201, tags=["Admin"], operation_id="admin_create_org")
    async def admin_create_org(
        body: OrgCreateRequest,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> OrgResponse:
        pool = await memory._get_pool()
        slug = normalize_org_slug(body.slug)
        schema_name = schema_for_org(slug)

        await _run_schema_migration(schema_name)
        row = await pool.fetchrow(
            f"""
            INSERT INTO {fq("orgs")} (slug, name, schema_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, updated_at = NOW()
            RETURNING id::text, slug, name, schema_name, status, created_at::text
            """,
            slug,
            body.name,
            schema_name,
        )
        owner_email = body.owner_email.strip().lower()
        owner = await pool.fetchrow(
            f"SELECT id::text FROM {fq('principals')} WHERE org_id = $1 AND lower(email) = $2",
            uuid.UUID(row["id"]),
            owner_email,
        )
        if owner:
            owner = await pool.fetchrow(
                f"""
                UPDATE {fq("principals")}
                SET display_name = $3, role = 'owner', status = 'active', updated_at = NOW()
                WHERE org_id = $1 AND lower(email) = $2
                RETURNING id::text
                """,
                uuid.UUID(row["id"]),
                owner_email,
                body.owner_name or owner_email,
            )
        else:
            owner = await pool.fetchrow(
                f"""
                INSERT INTO {fq("principals")} (org_id, email, display_name, principal_type, role)
                VALUES ($1, $2, $3, 'user', 'owner')
                RETURNING id::text
                """,
                uuid.UUID(row["id"]),
                owner_email,
                body.owner_name or owner_email,
            )
        await pool.execute(
            f"""
            INSERT INTO {fq("principal_credentials")} (principal_id, password_hash)
            VALUES ($1, $2)
            ON CONFLICT (principal_id) DO UPDATE
            SET password_hash = EXCLUDED.password_hash, password_changed_at = NOW()
            """,
            uuid.UUID(owner["id"]),
            hash_password(body.owner_password),
        )
        await _audit(
            org_id=row["id"],
            actor_principal_id=None,
            action="admin.orgs.create",
            target_type="org",
            target_id=row["id"],
            metadata={"slug": slug, "owner_principal_id": owner["id"]},
        )
        return OrgResponse(**dict(row))

    @router.get(
        "/principals",
        response_model=list[PrincipalResponse],
        tags=["Admin"],
        operation_id="admin_list_principals",
    )
    async def admin_list_principals(
        org_id: str = Query(...),
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> list[PrincipalResponse]:
        pool = await memory._get_pool()
        rows = await pool.fetch(
            f"""
            SELECT id::text, org_id::text, email, display_name, principal_type, role, status, created_at::text
            FROM {fq("principals")}
            WHERE org_id = $1
            ORDER BY created_at DESC
            """,
            uuid.UUID(org_id),
        )
        return [PrincipalResponse(**dict(r)) for r in rows]

    @router.post(
        "/principals",
        response_model=PrincipalResponse,
        status_code=201,
        tags=["Admin"],
        operation_id="admin_create_principal",
    )
    async def admin_create_principal(
        body: PrincipalCreateRequest,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> PrincipalResponse:
        if body.principal_type not in {"user", "service"}:
            raise HTTPException(status_code=400, detail="principal_type must be user or service")
        if body.role not in {"owner", "admin", "operator", "viewer", "service", "user"}:
            raise HTTPException(status_code=400, detail="Invalid role")
        if body.principal_type == "user" and (not body.email or not body.password):
            raise HTTPException(status_code=400, detail="Human users require email and password")
        pool = await memory._get_pool()
        row = await pool.fetchrow(
            f"""
            INSERT INTO {fq("principals")} (org_id, email, display_name, principal_type, role)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id::text, org_id::text, email, display_name, principal_type, role, status, created_at::text
            """,
            uuid.UUID(body.org_id),
            body.email.strip().lower() if body.email else None,
            body.display_name,
            body.principal_type,
            body.role,
        )
        if body.password:
            await pool.execute(
                f"INSERT INTO {fq('principal_credentials')} (principal_id, password_hash) VALUES ($1, $2)",
                uuid.UUID(row["id"]),
                hash_password(body.password),
            )
        await _audit(
            org_id=body.org_id,
            actor_principal_id=None,
            action="admin.users.create",
            target_type="principal",
            target_id=row["id"],
            metadata={"role": body.role, "principal_type": body.principal_type},
        )
        return PrincipalResponse(**dict(row))

    @router.patch(
        "/principals/{principal_id}",
        response_model=PrincipalResponse,
        tags=["Admin"],
        operation_id="admin_update_principal",
    )
    async def admin_update_principal(
        principal_id: str,
        status: str | None = Query(default=None),
        role: str | None = Query(default=None),
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> PrincipalResponse:
        if status is not None and status not in {"active", "disabled"}:
            raise HTTPException(status_code=400, detail="status must be active or disabled")
        if role is not None and role not in {"owner", "admin", "operator", "viewer", "service", "user"}:
            raise HTTPException(status_code=400, detail="Invalid role")
        pool = await memory._get_pool()
        row = await pool.fetchrow(
            f"""
            UPDATE {fq("principals")}
            SET status = COALESCE($2, status), role = COALESCE($3, role), updated_at = NOW()
            WHERE id = $1
            RETURNING id::text, org_id::text, email, display_name, principal_type, role, status, created_at::text
            """,
            uuid.UUID(principal_id),
            status,
            role,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Principal not found")
        await _audit(
            org_id=row["org_id"],
            actor_principal_id=None,
            action="admin.users.update",
            target_type="principal",
            target_id=row["id"],
            metadata={"status": status, "role": role},
        )
        return PrincipalResponse(**dict(row))

    @router.post(
        "/principals/{principal_id}/password",
        tags=["Admin"],
        operation_id="admin_reset_principal_password",
    )
    async def admin_reset_principal_password(
        principal_id: str,
        body: PasswordResetRequest,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> dict[str, str]:
        pool = await memory._get_pool()
        await pool.execute(
            f"""
            INSERT INTO {fq("principal_credentials")} (principal_id, password_hash)
            VALUES ($1, $2)
            ON CONFLICT (principal_id) DO UPDATE
            SET password_hash = EXCLUDED.password_hash, password_changed_at = NOW()
            """,
            uuid.UUID(principal_id),
            hash_password(body.password),
        )
        principal_org_id = await pool.fetchval(
            f"SELECT org_id::text FROM {fq('principals')} WHERE id = $1",
            uuid.UUID(principal_id),
        )
        await _audit(
            org_id=principal_org_id,
            actor_principal_id=None,
            action="admin.users.password_reset",
            target_type="principal",
            target_id=principal_id,
        )
        return {"status": "updated"}

    @router.get(
        "/access-grants",
        response_model=list[AccessGrantResponse],
        tags=["Admin"],
        operation_id="admin_list_access_grants",
    )
    async def admin_list_access_grants(
        org_id: str = Query(...),
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> list[AccessGrantResponse]:
        pool = await memory._get_pool()
        rows = await pool.fetch(
            f"""
            SELECT id::text, org_id::text, subject_type, subject_id, action, scope_type, scope_id, created_at::text
            FROM {fq("access_grants")}
            WHERE org_id = $1
            ORDER BY subject_type, subject_id, action, scope_type, scope_id
            """,
            uuid.UUID(org_id),
        )
        return [AccessGrantResponse(**dict(r)) for r in rows]

    @router.post(
        "/access-grants",
        response_model=AccessGrantResponse,
        status_code=201,
        tags=["Admin"],
        operation_id="admin_create_access_grant",
    )
    async def admin_create_access_grant(
        body: AccessGrantRequest,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> AccessGrantResponse:
        if body.action not in ALL_ACTIONS:
            raise HTTPException(status_code=400, detail="Invalid action")
        if body.subject_type not in {"principal", "role"}:
            raise HTTPException(status_code=400, detail="subject_type must be principal or role")
        if body.scope_type not in {"org", "bank", "system"}:
            raise HTTPException(status_code=400, detail="scope_type must be org, bank, or system")
        pool = await memory._get_pool()
        row = await pool.fetchrow(
            f"""
            INSERT INTO {fq("access_grants")} (org_id, subject_type, subject_id, action, scope_type, scope_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (org_id, subject_type, subject_id, action, scope_type, scope_id)
            DO UPDATE SET action = EXCLUDED.action
            RETURNING id::text, org_id::text, subject_type, subject_id, action, scope_type, scope_id, created_at::text
            """,
            uuid.UUID(body.org_id),
            body.subject_type,
            body.subject_id,
            body.action,
            body.scope_type,
            body.scope_id,
        )
        await _audit(
            org_id=body.org_id,
            actor_principal_id=None,
            action="admin.grants.create",
            target_type=body.subject_type,
            target_id=body.subject_id,
            metadata={"grant_action": body.action, "scope": f"{body.scope_type}:{body.scope_id}"},
        )
        return AccessGrantResponse(**dict(row))

    @router.delete(
        "/access-grants/{grant_id}",
        tags=["Admin"],
        operation_id="admin_delete_access_grant",
    )
    async def admin_delete_access_grant(
        grant_id: str,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> dict[str, str]:
        pool = await memory._get_pool()
        grant = await pool.fetchrow(
            f"""
            DELETE FROM {fq("access_grants")}
            WHERE id = $1
            RETURNING org_id::text, subject_type, subject_id, action, scope_type, scope_id
            """,
            uuid.UUID(grant_id),
        )
        result = "DELETE 1" if grant else "DELETE 0"
        deleted = int(result.split()[-1]) if result else 0
        if deleted == 0:
            raise HTTPException(status_code=404, detail="Grant not found")
        await _audit(
            org_id=grant["org_id"],
            actor_principal_id=None,
            action="admin.grants.delete",
            target_type=grant["subject_type"],
            target_id=grant["subject_id"],
            metadata={"grant_action": grant["action"], "scope": f"{grant['scope_type']}:{grant['scope_id']}"},
        )
        return {"status": "deleted"}

    @router.get(
        "/audit-events",
        response_model=list[AuditEventResponse],
        tags=["Admin"],
        operation_id="admin_list_audit_events",
    )
    async def admin_list_audit_events(
        org_id: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> list[AuditEventResponse]:
        pool = await memory._get_pool()
        if org_id:
            rows = await pool.fetch(
                f"""
                SELECT id::text, org_id::text, actor_principal_id::text, action, target_type, target_id,
                       result, metadata, created_at::text
                FROM {fq("audit_events")}
                WHERE org_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                uuid.UUID(org_id),
                limit,
            )
        else:
            rows = await pool.fetch(
                f"""
                SELECT id::text, org_id::text, actor_principal_id::text, action, target_type, target_id,
                       result, metadata, created_at::text
                FROM {fq("audit_events")}
                ORDER BY created_at DESC
                LIMIT $1
                """,
                limit,
            )
        return [AuditEventResponse(**dict(r)) for r in rows]

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
        return hash_secret(raw_key)

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
                   created_at::text, expires_at::text, revoked_at::text,
                   principal_id::text, key_prefix, last_used_at::text, description
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
                principal_id=r["principal_id"],
                key_prefix=r["key_prefix"],
                last_used_at=r["last_used_at"],
                description=r["description"],
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
        valid_roles = {"superuser", "owner", "admin", "operator", "viewer", "service", "user"}
        if body.role not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}")

        raw_key = generate_api_key()
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
                (id, key_hash, name, role, schema_name, allowed_bank_ids, created_at, expires_at,
                 principal_id, key_prefix, hash_version, description)
            VALUES ($1, $2, $3, $4, $5, $6, NOW(), $7, $8, $9, 2, $10)
            """,
            uuid.UUID(key_id),
            key_hash,
            body.name,
            body.role,
            body.schema_name,
            body.allowed_bank_ids,
            expires_at,
            uuid.UUID(body.principal_id) if body.principal_id else None,
            key_prefix(raw_key),
            body.description,
        )
        logger.info("[ADMIN] created api_key id=%s name=%s role=%s", key_id, body.name, body.role)
        await _audit(
            org_id=None,
            actor_principal_id=None,
            action="admin.keys.create",
            target_type="api_key",
            target_id=key_id,
            metadata={"name": body.name, "role": body.role, "principal_id": body.principal_id},
        )

        return ApiKeyResponse(
            id=key_id,
            name=body.name,
            role=body.role,
            schema_name=body.schema_name,
            allowed_bank_ids=body.allowed_bank_ids,
            created_at=now,
            expires_at=expires_at,
            revoked_at=None,
            principal_id=body.principal_id,
            key_prefix=key_prefix(raw_key),
            last_used_at=None,
            description=body.description,
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
            valid_roles = {"superuser", "owner", "admin", "operator", "viewer", "service", "user"}
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
                      created_at::text, expires_at::text, revoked_at::text,
                      principal_id::text, key_prefix, last_used_at::text, description
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
            principal_id=row["principal_id"],
            key_prefix=row["key_prefix"],
            last_used_at=row["last_used_at"],
            description=row["description"],
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
        await _audit(
            org_id=None,
            actor_principal_id=None,
            action="admin.keys.revoke",
            target_type="api_key",
            target_id=key_id,
        )
        return {"status": "revoked", "id": key_id}

    return router
