"""Login/session API for first-party control-plane authentication."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from atulya_api.auth import (
    fq,
    generate_session,
    hash_password,
    hash_secret,
    key_prefix,
    normalize_org_slug,
    role_actions,
    schema_for_org,
    verify_password,
)
from atulya_api.extensions.tenant import AuthenticationError
from atulya_api.models import RequestContext

logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    org: str | None = Field(
        default=None, description="Organization slug; required only when email belongs to many orgs"
    )
    email: str
    password: str


class SignupStateResponse(BaseModel):
    mode: str
    available: bool
    org_count: int


class SignupRequest(BaseModel):
    org_slug: str = Field(min_length=2, max_length=64)
    org_name: str = Field(min_length=2, max_length=160)
    owner_email: str
    owner_name: str | None = None
    owner_password: str = Field(min_length=12)


class PrincipalInfo(BaseModel):
    org_id: str | None
    org_slug: str | None = None
    schema_name: str
    principal_id: str | None
    email: str | None
    display_name: str | None
    principal_type: str | None
    role: str
    allowed_actions: list[str] | None
    action_scopes: dict[str, list[str]] | None
    is_superuser: bool = False


class LoginResponse(BaseModel):
    token: str
    expires_at: str
    principal: PrincipalInfo


def _extract_api_key(authorization: str | None) -> str | None:
    if not authorization:
        return None
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return authorization.strip()


def create_auth_router(memory: Any) -> APIRouter:
    router = APIRouter()

    def _signup_mode() -> str:
        mode = os.getenv("ATULYA_SIGNUP_MODE", "bootstrap").strip().lower()
        return mode if mode in {"disabled", "bootstrap", "public"} else "disabled"

    def get_request_context(authorization: str | None = Header(default=None)) -> RequestContext:
        return RequestContext(api_key=_extract_api_key(authorization))

    async def _org_count(pool: Any) -> int:
        return int(await pool.fetchval(f"SELECT COUNT(*) FROM {fq('orgs')}") or 0)

    async def _run_schema_migration(schema_name: str) -> None:
        from atulya_api.migrations import run_migrations

        db_url = getattr(memory, "db_url", None)
        if not db_url:
            raise HTTPException(status_code=503, detail="Database URL unavailable for schema migration")
        await asyncio.to_thread(run_migrations, db_url, schema=schema_name)

    async def _audit(
        pool: Any,
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
            logger.debug("Failed to write audit event", exc_info=True)

    async def _principal_info(ctx: RequestContext, pool: Any | None = None) -> PrincipalInfo:
        org_slug = None
        if ctx.org_id and pool is not None:
            try:
                org_slug = await pool.fetchval(f"SELECT slug FROM {fq('orgs')} WHERE id = $1", uuid.UUID(ctx.org_id))
            except Exception:
                org_slug = None
        return PrincipalInfo(
            org_id=ctx.org_id,
            org_slug=org_slug,
            schema_name=ctx.schema_name or "public",
            principal_id=ctx.principal_id,
            email=ctx.email,
            display_name=ctx.display_name,
            principal_type=ctx.principal_type,
            role=ctx.role,
            allowed_actions=ctx.allowed_actions,
            action_scopes=ctx.action_scopes,
            is_superuser=ctx.role == "superuser",
        )

    def _role_scopes(role: str) -> dict[str, list[str]]:
        actions = role_actions(role)
        if role in {"owner", "admin", "superuser"}:
            return {action: ["org:*"] for action in sorted(actions)}
        return {}

    async def _create_session(pool: Any, row: Any) -> LoginResponse:
        session = generate_session()
        await pool.execute(
            f"""
            INSERT INTO {fq("principal_sessions")}
                (principal_id, token_hash, token_prefix, hash_version, expires_at)
            VALUES ($1, $2, $3, 2, $4)
            """,
            uuid.UUID(row["principal_id"]),
            session.token_hash,
            key_prefix(session.raw_token),
            session.expires_at,
        )
        ctx = RequestContext(
            org_id=row["org_id"],
            tenant_id=row["org_id"],
            principal_id=row["principal_id"],
            principal_type=row["principal_type"],
            display_name=row["display_name"],
            email=row["email"],
            role=row["role"],
            schema_name=row["schema_name"],
            allowed_actions=role_actions(row["role"]),
            action_scopes=_role_scopes(row["role"]),
        )
        return LoginResponse(
            token=session.raw_token,
            expires_at=session.expires_at.isoformat(),
            principal=await _principal_info(ctx, pool),
        )

    @router.get("/signup-state", response_model=SignupStateResponse, tags=["Auth"], operation_id="auth_signup_state")
    async def signup_state() -> SignupStateResponse:
        pool = await memory._get_pool()
        mode = _signup_mode()
        count = await _org_count(pool)
        available = mode == "public" or (mode == "bootstrap" and count == 0)
        return SignupStateResponse(mode=mode, available=available, org_count=count)

    @router.post("/signup", response_model=LoginResponse, tags=["Auth"], operation_id="auth_signup")
    async def signup(body: SignupRequest) -> LoginResponse:
        pool = await memory._get_pool()
        mode = _signup_mode()
        count = await _org_count(pool)
        if mode == "disabled" or (mode == "bootstrap" and count > 0):
            raise HTTPException(status_code=403, detail="Signup is not available")

        try:
            slug = normalize_org_slug(body.org_slug)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        schema_name = schema_for_org(slug)
        owner_email = body.owner_email.strip().lower()
        existing = await pool.fetchval(
            f"SELECT 1 FROM {fq('orgs')} WHERE slug = $1 OR schema_name = $2",
            slug,
            schema_name,
        )
        if existing:
            raise HTTPException(status_code=409, detail="Organization already exists")

        await _run_schema_migration(schema_name)
        async with pool.acquire() as conn:
            async with conn.transaction():
                org = await conn.fetchrow(
                    f"""
                    INSERT INTO {fq("orgs")} (slug, name, schema_name)
                    VALUES ($1, $2, $3)
                    RETURNING id::text AS org_id, slug AS org_slug, schema_name
                    """,
                    slug,
                    body.org_name,
                    schema_name,
                )
                principal = await conn.fetchrow(
                    f"""
                    INSERT INTO {fq("principals")} (org_id, email, display_name, principal_type, role)
                    VALUES ($1, $2, $3, 'user', 'owner')
                    RETURNING
                        id::text AS principal_id,
                        email,
                        display_name,
                        principal_type,
                        role
                    """,
                    uuid.UUID(org["org_id"]),
                    owner_email,
                    body.owner_name or owner_email,
                )
                await conn.execute(
                    f"""
                    INSERT INTO {fq("principal_credentials")} (principal_id, password_hash)
                    VALUES ($1, $2)
                    """,
                    uuid.UUID(principal["principal_id"]),
                    hash_password(body.owner_password),
                )
                row = {
                    "org_id": org["org_id"],
                    "org_slug": org["org_slug"],
                    "schema_name": org["schema_name"],
                    "principal_id": principal["principal_id"],
                    "email": principal["email"],
                    "display_name": principal["display_name"],
                    "principal_type": principal["principal_type"],
                    "role": principal["role"],
                }
                response = await _create_session(conn, row)
                await _audit(
                    conn,
                    org_id=org["org_id"],
                    actor_principal_id=principal["principal_id"],
                    action="auth.signup",
                    target_type="org",
                    target_id=org["org_id"],
                    metadata={"slug": slug, "mode": mode},
                )
                return response

    @router.post("/login", response_model=LoginResponse, tags=["Auth"], operation_id="auth_login")
    async def login(body: LoginRequest) -> LoginResponse:
        pool = await memory._get_pool()
        email = body.email.strip().lower()
        org_slug = body.org.strip().lower() if body.org else None
        rows = await pool.fetch(
            f"""
            SELECT
                o.id::text AS org_id,
                o.slug AS org_slug,
                o.schema_name,
                o.status AS org_status,
                p.id::text AS principal_id,
                p.email,
                p.display_name,
                p.principal_type,
                p.role,
                p.status AS principal_status,
                c.password_hash
            FROM {fq("orgs")} o
            JOIN {fq("principals")} p ON p.org_id = o.id
            JOIN {fq("principal_credentials")} c ON c.principal_id = p.id
            WHERE lower(p.email) = $1 AND ($2::text IS NULL OR o.slug = $2)
            ORDER BY p.created_at DESC
            """,
            email,
            org_slug,
        )
        active_rows = [r for r in rows if r["org_status"] == "active" and r["principal_status"] == "active"]
        if org_slug is None and len(active_rows) > 1:
            raise HTTPException(status_code=409, detail="Multiple organizations match this email")
        row = active_rows[0] if active_rows else None
        if row is None or row["org_status"] != "active" or row["principal_status"] != "active":
            await _audit(pool, org_id=None, actor_principal_id=None, action="auth.login", result="denied")
            raise HTTPException(status_code=401, detail="Invalid login")
        if not verify_password(body.password, row["password_hash"]):
            await _audit(
                pool,
                org_id=row["org_id"],
                actor_principal_id=row["principal_id"],
                action="auth.login",
                result="denied",
            )
            raise HTTPException(status_code=401, detail="Invalid login")

        await _audit(
            pool,
            org_id=row["org_id"],
            actor_principal_id=row["principal_id"],
            action="auth.login",
            target_type="principal",
            target_id=row["principal_id"],
        )
        return await _create_session(pool, row)

    @router.post("/logout", tags=["Auth"], operation_id="auth_logout")
    async def logout(request_context: RequestContext = Depends(get_request_context)) -> dict[str, bool]:
        if not request_context.api_key:
            return {"ok": True}
        pool = await memory._get_pool()
        from atulya_api.auth import hash_secret

        await pool.execute(
            f"UPDATE {fq('principal_sessions')} SET revoked_at = NOW() WHERE token_hash = $1 AND revoked_at IS NULL",
            hash_secret(request_context.api_key),
        )
        return {"ok": True}

    @router.get("/me", response_model=PrincipalInfo, tags=["Auth"], operation_id="auth_me")
    async def me(request_context: RequestContext = Depends(get_request_context)) -> PrincipalInfo:
        pool = await memory._get_pool()
        if not request_context.api_key:
            raise HTTPException(status_code=401, detail="Session required")
        session_row = await pool.fetchrow(
            f"""
            SELECT
                o.id::text AS org_id,
                o.slug AS org_slug,
                o.schema_name,
                p.id::text AS principal_id,
                p.email,
                p.display_name,
                p.principal_type,
                p.role
            FROM {fq("principal_sessions")} s
            JOIN {fq("principals")} p ON p.id = s.principal_id
            JOIN {fq("orgs")} o ON o.id = p.org_id
            WHERE s.token_hash = $1
              AND s.revoked_at IS NULL
              AND s.expires_at > NOW()
              AND p.status = 'active'
              AND o.status = 'active'
            """,
            hash_secret(request_context.api_key),
        )
        if session_row:
            ctx = RequestContext(
                org_id=session_row["org_id"],
                tenant_id=session_row["org_id"],
                principal_id=session_row["principal_id"],
                principal_type=session_row["principal_type"],
                display_name=session_row["display_name"],
                email=session_row["email"],
                role=session_row["role"],
                schema_name=session_row["schema_name"],
                allowed_actions=role_actions(session_row["role"]),
                action_scopes=_role_scopes(session_row["role"]),
            )
            return await _principal_info(ctx, pool)

        try:
            tenant_ctx = await memory.tenant_extension.authenticate(request_context)
            tenant_ctx.apply_to_request_context(request_context)
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail=exc.reason)
        return await _principal_info(request_context, pool)

    return router
