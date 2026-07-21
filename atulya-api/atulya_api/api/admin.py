"""
Admin API router for atulya-api.

Provides platform-operator endpoints for organization provisioning, worker
control, schema inspection, and system health. Routes require a normal session
with system.admin on system:*; the environment key is recovery-only.

Mount via create_app() when ATULYA_API_ADMIN_ENABLED=true.

PCRM metadata:
{
  "component": "admin-api",
  "security_model": "RBAC + ABAC via TenantContext",
  "auth_dependency": "system.admin or emergency recovery key",
  "default_state": "disabled (ATULYA_API_ADMIN_ENABLED=false)"
}
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from atulya_api.auth import (
    ALL_ACTIONS,
    auth_schema,
    fq,
    normalize_org_slug,
    quote_ident,
)
from atulya_api.engine.jsonb_compat import decode_jsonb
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
    owner_password: str | None = Field(default=None, min_length=12, deprecated=True)
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

    Human platform operators authenticate with normal database sessions. The
    environment superuser key remains an emergency recovery credential.
    """
    from atulya_api.config import get_config

    config = get_config()
    provided_key = request_context.api_key

    if not provided_key:
        raise HTTPException(status_code=401, detail={"code": "session_required"})

    if provided_key.startswith("atulya_sess_"):
        from atulya_api.auth_service import require_permission, resolve_identity, write_audit

        pool = await memory._get_pool()
        identity = await resolve_identity(pool, provided_key)
        if identity is None:
            raise HTTPException(status_code=401, detail={"code": "invalid_or_expired_session"})
        try:
            require_permission(identity, "system.admin")
        except HTTPException:
            await write_audit(
                pool,
                identity,
                "access.denied",
                org_id=identity.active_org_id,
                target_type="platform_route",
                result="denied",
                metadata={"missing_action": "system.admin", "required_scope": "system:*"},
            )
            raise
        return TenantContext(
            schema_name=identity.schema_name,
            org_id=identity.active_org_id,
            principal_id=identity.principal_id,
            membership_id=identity.membership_id,
            role="superuser",
            allowed_actions=identity.allowed_actions,
            action_scopes=identity.action_scopes,
        )

    superuser_key = config.superuser_key
    if not superuser_key:
        raise HTTPException(
            status_code=503,
            detail={"code": "emergency_key_not_configured"},
        )

    if not hmac.compare_digest(provided_key.encode(), superuser_key.encode()):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "permission_denied",
                "missing_action": "system.admin",
                "required_scope": "system:*",
            },
        )

    schema = config.superuser_schema or "public"
    return TenantContext(
        schema_name=schema,
        role="superuser",
        allowed_actions=list(ALL_ACTIONS),
        action_scopes={"system.admin": ["system:*"]},
    )


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
                json.dumps(metadata or {}),
            )
        except Exception:
            logger.debug("[ADMIN] failed to write audit event", exc_info=True)

    async def _run_schema_migration(schema_name: str) -> None:
        from atulya_api.migrations import run_migrations

        db_url = getattr(memory, "db_url", None)
        if not db_url:
            raise HTTPException(status_code=503, detail="Database URL unavailable for schema migration")
        await asyncio.to_thread(run_migrations, db_url, schema=schema_name)

    async def _validated_schema(pool: Any, schema_name: str) -> str:
        if schema_name == "public":
            return quote_ident(schema_name)
        exists = await pool.fetchval(
            f"SELECT 1 FROM {fq('orgs')} WHERE schema_name = $1",
            schema_name,
        )
        if not exists:
            raise HTTPException(status_code=404, detail={"code": "organization_schema_not_found"})
        return quote_ident(schema_name)

    # ------------------------------------------------------------------
    # GET /v1/admin/system/health
    # ------------------------------------------------------------------

    @router.get(
        "/system/health",
        response_model=SystemHealthResponse,
        summary="Admin system health",
        description="Returns DB pool stats, migration version, and active worker count.",
        operation_id="admin_system_health",
    )
    async def admin_system_health(
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> SystemHealthResponse:
        from atulya_api import __version__

        pool = await memory._get_pool()

        configured_auth_schema = auth_schema()
        qualified_auth_schema = quote_ident(configured_auth_schema)

        # Migration version
        migration_version: str | None = None
        try:
            row = await pool.fetchrow(f"SELECT version_num FROM {qualified_auth_schema}.alembic_version LIMIT 1")
            if row:
                migration_version = row["version_num"]
        except Exception:
            pass

        worker_ids: set[str] = set()
        tenant_ext = memory.tenant_extension
        if tenant_ext:
            for tenant in await tenant_ext.list_tenants():
                try:
                    schema = await _validated_schema(pool, tenant.schema)
                    rows = await pool.fetch(
                        f"SELECT DISTINCT worker_id FROM {schema}.async_operations "
                        "WHERE worker_id IS NOT NULL AND status = 'pending'"
                    )
                    worker_ids.update(row["worker_id"] for row in rows)
                except Exception:
                    logger.debug("Could not inspect worker state for %s", tenant.schema, exc_info=True)

        return SystemHealthResponse(
            status="healthy",
            api_version=__version__,
            db_pool_min=pool.get_min_size(),
            db_pool_max=pool.get_max_size(),
            db_pool_size=pool.get_size(),
            db_pool_free=pool.get_idle_size(),
            migration_version=migration_version,
            worker_count=len(worker_ids),
            admin_schema=configured_auth_schema,
        )

    # ------------------------------------------------------------------
    # Org / principal / grant management
    # ------------------------------------------------------------------

    @router.get("/orgs", response_model=list[OrgResponse], operation_id="admin_list_orgs")
    async def admin_list_orgs(
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> list[OrgResponse]:
        pool = await memory._get_pool()
        rows = await pool.fetch(
            f"SELECT id::text, slug, name, schema_name, status, created_at::text FROM {fq('orgs')} ORDER BY created_at DESC"
        )
        return [OrgResponse(**dict(r)) for r in rows]

    @router.post("/orgs", response_model=OrgResponse, status_code=201, operation_id="admin_create_org")
    async def admin_create_org(
        body: OrgCreateRequest,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> OrgResponse:
        pool = await memory._get_pool()
        owner_email = body.owner_email.strip().lower()
        owner = await pool.fetchrow(
            f"""
            SELECT id::text FROM {fq("principals")}
            WHERE lower(email) = $1 AND principal_type = 'user'
              AND status = 'active' AND email_verified_at IS NOT NULL
            """,
            owner_email,
        )
        if not owner:
            raise HTTPException(
                status_code=422,
                detail={"code": "verified_owner_account_required", "owner_email": owner_email},
            )
        from atulya_api.auth_service import provision_workspace

        try:
            org_id = await provision_workspace(
                memory,
                pool,
                owner["id"],
                slug=normalize_org_slug(body.slug),
                name=body.name,
            )
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise HTTPException(status_code=409, detail={"code": "workspace_exists"}) from exc
            raise
        row = await pool.fetchrow(
            f"SELECT id::text, slug, name, schema_name, status, created_at::text FROM {fq('orgs')} WHERE id = $1",
            uuid.UUID(org_id),
        )
        await _audit(
            org_id=org_id,
            actor_principal_id=tenant_ctx.principal_id,
            action="platform.orgs.create",
            target_type="org",
            target_id=org_id,
            metadata={"slug": row["slug"], "owner_principal_id": owner["id"]},
        )
        return OrgResponse(**dict(row))

    @router.patch("/orgs/{org_id}", response_model=OrgResponse, operation_id="admin_update_org")
    async def admin_update_org(
        org_id: str,
        status: str = Query(...),
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> OrgResponse:
        if status not in {"active", "disabled"}:
            raise HTTPException(status_code=400, detail={"code": "invalid_organization_status"})
        pool = await memory._get_pool()
        row = await pool.fetchrow(
            f"""
            UPDATE {fq("orgs")} SET status = $2, updated_at = NOW() WHERE id = $1
            RETURNING id::text, slug, name, schema_name, status, created_at::text
            """,
            uuid.UUID(org_id),
            status,
        )
        if not row:
            raise HTTPException(status_code=404, detail={"code": "organization_not_found"})
        if status == "disabled":
            await pool.execute(
                f"""
                UPDATE {fq("principal_sessions")} s
                SET revoked_at = NOW(), revocation_reason = 'organization_disabled'
                WHERE s.active_org_id = $1 AND s.revoked_at IS NULL
                """,
                uuid.UUID(org_id),
            )
        await _audit(
            org_id=org_id,
            actor_principal_id=tenant_ctx.principal_id,
            action="platform.orgs.status",
            target_type="org",
            target_id=org_id,
            metadata={"status": status},
        )
        return OrgResponse(**dict(row))

    @router.post("/orgs/{org_id}/retry-provisioning", response_model=OrgResponse, operation_id="admin_retry_org")
    async def admin_retry_org(
        org_id: str,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> OrgResponse:
        pool = await memory._get_pool()
        org = await pool.fetchrow(
            f"SELECT id::text, slug, name, schema_name, status, created_at::text FROM {fq('orgs')} WHERE id = $1",
            uuid.UUID(org_id),
        )
        if not org:
            raise HTTPException(status_code=404, detail={"code": "organization_not_found"})
        if org["status"] != "failed":
            raise HTTPException(status_code=409, detail={"code": "organization_not_failed"})
        await pool.execute(f"UPDATE {fq('orgs')} SET status = 'provisioning' WHERE id = $1", uuid.UUID(org_id))
        try:
            await _run_schema_migration(org["schema_name"])
        except Exception:
            await pool.execute(f"UPDATE {fq('orgs')} SET status = 'failed' WHERE id = $1", uuid.UUID(org_id))
            raise
        row = await pool.fetchrow(
            f"""
            UPDATE {fq("orgs")} SET status = 'active', updated_at = NOW() WHERE id = $1
            RETURNING id::text, slug, name, schema_name, status, created_at::text
            """,
            uuid.UUID(org_id),
        )
        await _audit(
            org_id=org_id,
            actor_principal_id=tenant_ctx.principal_id,
            action="platform.orgs.retry_provisioning",
            target_type="org",
            target_id=org_id,
        )
        return OrgResponse(**dict(row))

    @router.get(
        "/principals",
        response_model=list[PrincipalResponse],
        include_in_schema=False,
        operation_id="admin_list_principals",
    )
    async def admin_list_principals(
        org_id: str = Query(...),
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> list[PrincipalResponse]:
        pool = await memory._get_pool()
        rows = await pool.fetch(
            f"""
            SELECT p.id::text, m.org_id::text, p.email, p.display_name, p.principal_type,
                   r.name AS role, m.status, p.created_at::text
            FROM {fq("principals")} p
            JOIN {fq("org_memberships")} m ON m.principal_id = p.id
            JOIN {fq("roles")} r ON r.id = m.role_id
            WHERE m.org_id = $1
            ORDER BY p.created_at DESC
            """,
            uuid.UUID(org_id),
        )
        return [PrincipalResponse(**dict(r)) for r in rows]

    @router.post(
        "/principals",
        response_model=PrincipalResponse,
        status_code=201,
        include_in_schema=False,
        operation_id="admin_create_principal",
    )
    async def admin_create_principal(
        body: PrincipalCreateRequest,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> PrincipalResponse:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "deprecated_principal_mutation",
                "message": "Use organization invitations or service-account endpoints.",
            },
        )

    @router.patch(
        "/principals/{principal_id}",
        response_model=PrincipalResponse,
        include_in_schema=False,
        operation_id="admin_update_principal",
    )
    async def admin_update_principal(
        principal_id: str,
        status: str | None = Query(default=None),
        role: str | None = Query(default=None),
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> PrincipalResponse:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "deprecated_principal_mutation",
                "message": "Use organization membership or service-account endpoints.",
            },
        )

    @router.post(
        "/principals/{principal_id}/password",
        include_in_schema=False,
        operation_id="admin_reset_principal_password",
    )
    async def admin_reset_principal_password(
        principal_id: str,
        body: PasswordResetRequest,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> dict[str, str]:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "admin_password_reset_removed",
                "message": "Use the enumeration-safe password recovery flow.",
            },
        )

    @router.get(
        "/access-grants",
        response_model=list[AccessGrantResponse],
        include_in_schema=False,
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
        include_in_schema=False,
        operation_id="admin_create_access_grant",
    )
    async def admin_create_access_grant(
        body: AccessGrantRequest,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> AccessGrantResponse:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "deprecated_grant_mutation",
                "message": "Manage grants through the organization authorization service.",
                "replacement": "/v1/orgs/{org_id}/grants",
            },
        )

    @router.delete(
        "/access-grants/{grant_id}",
        include_in_schema=False,
        operation_id="admin_delete_access_grant",
    )
    async def admin_delete_access_grant(
        grant_id: str,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> dict[str, str]:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "deprecated_grant_mutation",
                "message": "Manage grants through the organization authorization service.",
                "replacement": "/v1/orgs/{org_id}/grants/{grant_id}",
            },
        )

    @router.get(
        "/audit-events",
        response_model=list[AuditEventResponse],
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
        return [AuditEventResponse(**{**dict(row), "metadata": decode_jsonb(row["metadata"], {})}) for row in rows]

    # ------------------------------------------------------------------
    # GET /v1/admin/tenants
    # ------------------------------------------------------------------

    @router.get(
        "/tenants",
        response_model=list[TenantSummaryResponse],
        summary="List all tenants",
        description="Returns all tenants known to the tenant extension with bank counts.",
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
                qualified_schema = await _validated_schema(pool, t.schema)
                row = await pool.fetchrow(f"SELECT COUNT(*) AS cnt FROM {qualified_schema}.banks")
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
        operation_id="admin_list_tenant_banks",
    )
    async def admin_list_tenant_banks(
        schema: str,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> list[dict[str, Any]]:
        pool = await memory._get_pool()
        qualified_schema = await _validated_schema(pool, schema)
        try:
            rows = await pool.fetch(
                f"SELECT bank_id, name, created_at::text, updated_at::text FROM {qualified_schema}.banks ORDER BY created_at DESC"
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
        operation_id="admin_list_workers",
    )
    async def admin_list_workers(
        schema: str = Query(default="public", description="Schema to inspect"),
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> list[WorkerStatusResponse]:
        pool = await memory._get_pool()
        qualified_schema = await _validated_schema(pool, schema)
        operations_table = f"{qualified_schema}.async_operations"
        try:
            rows = await pool.fetch(
                f"""
                SELECT
                    worker_id,
                    COUNT(*) FILTER (WHERE status = 'pending') AS pending_count,
                    COUNT(*) FILTER (WHERE status = 'pending' AND updated_at < NOW() - INTERVAL '5 minutes') AS stuck_count,
                    MAX(updated_at)::text AS last_seen_at
                FROM {operations_table}
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
        operation_id="admin_decommission_worker",
    )
    async def admin_decommission_worker(
        worker_id: str,
        body: DecommissionRequest,
        schema: str = Query(default="public"),
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> DecommissionResponse:
        pool = await memory._get_pool()
        qualified_schema = await _validated_schema(pool, schema)
        operations_table = f"{qualified_schema}.async_operations"

        if worker_id == "__all_stuck__":
            # Release all pending tasks with no assigned worker and last updated > 5 min ago.
            result = await pool.execute(
                f"""
                UPDATE {operations_table}
                SET worker_id = NULL, status = 'pending', updated_at = NOW()
                WHERE status = 'pending'
                  AND (worker_id IS NULL OR updated_at < NOW() - INTERVAL '5 minutes')
                """,
            )
        elif body.release_stuck:
            result = await pool.execute(
                f"""
                UPDATE {operations_table}
                SET worker_id = NULL, status = 'pending', updated_at = NOW()
                WHERE worker_id = $1 AND status = 'pending'
                """,
                worker_id,
            )
        else:
            # Just clear worker claim without re-queuing (leave as pending, detach worker_id).
            result = await pool.execute(
                f"UPDATE {operations_table} SET worker_id = NULL WHERE worker_id = $1",
                worker_id,
            )

        released = int(result.split()[-1]) if result else 0
        logger.info("[ADMIN] decommission worker=%s schema=%s released=%d", worker_id, schema, released)
        await _audit(
            org_id=None,
            actor_principal_id=tenant_ctx.principal_id,
            action="platform.workers.decommission",
            target_type="worker",
            target_id=worker_id,
            metadata={"schema": schema, "released_count": released},
        )
        return DecommissionResponse(worker_id=worker_id, released_count=released)

    # ------------------------------------------------------------------
    # GET /v1/admin/operations
    # ------------------------------------------------------------------

    @router.get(
        "/operations",
        response_model=list[OperationSummaryResponse],
        summary="List operations across all tenants",
        description="Returns recent async operations across all tenant schemas visible to the superuser.",
        operation_id="admin_list_operations",
    )
    async def admin_list_operations(
        schema: str = Query(default="public"),
        status: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> list[OperationSummaryResponse]:
        pool = await memory._get_pool()
        qualified_schema = await _validated_schema(pool, schema)
        operations_table = f"{qualified_schema}.async_operations"

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
                FROM {operations_table}
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
        operation_id="admin_trigger_consolidation",
    )
    async def admin_trigger_consolidation(
        schema: str,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> dict[str, Any]:
        pool = await memory._get_pool()
        qualified_schema = await _validated_schema(pool, schema)

        try:
            bank_rows = await pool.fetch(f"SELECT bank_id FROM {qualified_schema}.banks")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Cannot list banks in schema '{schema}': {exc}")

        queued: list[str] = []
        for row in bank_rows:
            bid = row["bank_id"]
            # Platform jobs may target a schema different from the operator's
            # active workspace. Preserve the real actor and authorization while
            # binding the internal task to the validated target schema.
            rc = RequestContext(
                internal=True,
                user_initiated=True,
                role=tenant_ctx.role,
                principal_id=tenant_ctx.principal_id,
                principal_type=tenant_ctx.principal_type,
                display_name=tenant_ctx.display_name,
                email=tenant_ctx.email,
                allowed_actions=tenant_ctx.allowed_actions,
                action_scopes=tenant_ctx.action_scopes,
                schema_name=schema,
            )
            try:
                result = await memory.submit_async_consolidation(bank_id=bid, request_context=rc)
                queued.append(result["operation_id"])
            except Exception as exc:
                logger.warning("[ADMIN] consolidation queue failed bank=%s: %s", bid, exc)

        await _audit(
            org_id=None,
            actor_principal_id=tenant_ctx.principal_id,
            action="platform.consolidation.trigger",
            target_type="schema",
            target_id=schema,
            metadata={"queued_count": len(queued)},
        )
        return {"schema": schema, "queued_count": len(queued), "operation_ids": queued}

    @router.get(
        "/api-keys",
        response_model=list[ApiKeyResponse],
        include_in_schema=False,
        summary="List API keys",
        description="Returns all API keys (redacted — raw key is never returned after creation).",
        operation_id="admin_list_api_keys",
    )
    async def admin_list_api_keys(
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> list[ApiKeyResponse]:
        pool = await memory._get_pool()
        rows = await pool.fetch(
            f"""
            SELECT k.id::text, k.name, r.name AS role, o.schema_name,
                   ARRAY(
                       SELECT ms.scope_id
                       FROM {fq("org_memberships")} m2
                       JOIN {fq("membership_scopes")} ms ON ms.membership_id = m2.id
                       WHERE m2.principal_id = k.principal_id
                         AND m2.org_id = o.id
                         AND ms.scope_type = 'bank'
                       ORDER BY ms.scope_id
                   ) AS allowed_bank_ids,
                   k.created_at::text, k.expires_at::text, k.revoked_at::text,
                   k.principal_id::text, k.key_prefix, k.last_used_at::text, k.description
            FROM {fq("api_keys")} k
            JOIN {fq("principals")} p ON p.id = k.principal_id
            JOIN {fq("org_memberships")} m ON m.principal_id = p.id
            JOIN {fq("orgs")} o ON o.id = m.org_id
            JOIN {fq("roles")} r ON r.id = m.role_id
            ORDER BY k.created_at DESC
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
        include_in_schema=False,
        summary="Create API key",
        description=(
            "Creates a new API key and returns the raw key **once**. Store it securely — it cannot be retrieved again."
        ),
        operation_id="admin_create_api_key",
    )
    async def admin_create_api_key(
        body: ApiKeyCreateRequest,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> ApiKeyResponse:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "legacy_api_key_mutation_removed",
                "message": "Create keys through an organization service account.",
                "replacement": "/v1/orgs/{org_id}/service-accounts/{principal_id}/keys",
            },
        )

    @router.patch(
        "/api-keys/{key_id}",
        response_model=ApiKeyResponse,
        include_in_schema=False,
        summary="Update API key",
        description="Update name, role, or allowed_bank_ids for an existing key.",
        operation_id="admin_update_api_key",
    )
    async def admin_update_api_key(
        key_id: str,
        body: ApiKeyUpdateRequest,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> ApiKeyResponse:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "legacy_api_key_mutation_removed",
                "message": "Update the service account role or bank scope instead.",
                "replacement": "/v1/orgs/{org_id}/service-accounts/{principal_id}",
            },
        )

    @router.delete(
        "/api-keys/{key_id}",
        include_in_schema=False,
        summary="Revoke API key",
        description="Soft-deletes an API key by setting revoked_at. The key is immediately inactive.",
        operation_id="admin_revoke_api_key",
    )
    async def admin_revoke_api_key(
        key_id: str,
        tenant_ctx: TenantContext = Depends(require_superuser),
    ) -> dict[str, str]:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "legacy_api_key_mutation_removed",
                "message": "Revoke keys through the owning organization service account.",
                "replacement": "/v1/orgs/{org_id}/service-accounts/{principal_id}/keys/{key_id}",
            },
        )

    return router
