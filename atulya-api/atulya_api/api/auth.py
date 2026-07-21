"""Global identity, workspace membership, and opaque-session API."""

from __future__ import annotations

import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from atulya_api.auth import (
    fq,
    hash_password,
    hash_session_token,
    normalize_org_slug,
    password_needs_rehash,
    verify_password,
)
from atulya_api.auth_email import send_auth_email, verification_required
from atulya_api.auth_service import (
    ResolvedIdentity,
    check_rate_limit,
    clear_rate_limit,
    enforce_rate_limit,
    issue_session,
    provision_workspace,
    resolve_identity,
    write_audit,
)
from atulya_api.engine.jsonb_compat import decode_jsonb


class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    org_slug: str = Field(min_length=2, max_length=64)
    org_name: str = Field(min_length=2, max_length=160)
    owner_email: str
    owner_name: str = Field(min_length=1, max_length=160)
    owner_password: str = Field(min_length=12)


class SignupStateResponse(BaseModel):
    mode: str
    available: bool
    org_count: int
    verification_required: bool


class PendingAuthResponse(BaseModel):
    status: str
    verification_required: bool = False


class LoginResponse(BaseModel):
    token: str
    expires_at: str
    principal: ResolvedIdentity


class TokenRequest(BaseModel):
    token: str


class PasswordResetRequest(BaseModel):
    token: str
    password: str = Field(min_length=12)


class EmailRequest(BaseModel):
    email: str


class WorkspaceSwitchRequest(BaseModel):
    org_id: str


class SessionResponse(BaseModel):
    id: str
    token_prefix: str
    created_at: str
    expires_at: str
    last_used_at: str | None
    current: bool
    ip_address: str | None
    user_agent: str | None


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    return authorization[7:].strip() if authorization.lower().startswith("bearer ") else authorization.strip()


def _client_ip(request: Request) -> str:
    if os.getenv("ATULYA_TRUST_PROXY_HEADERS", "false").lower() in {"true", "1", "yes"}:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _signup_mode() -> str:
    mode = os.getenv("ATULYA_SIGNUP_MODE", "public").strip().lower()
    return mode if mode in {"disabled", "bootstrap", "public"} else "disabled"


def _public_url() -> str:
    return os.getenv("ATULYA_AUTH_PUBLIC_URL", "http://localhost:9999").rstrip("/")


async def _challenge(
    pool: Any,
    *,
    challenge_type: str,
    email: str,
    principal_id: str | None,
    payload: dict[str, Any],
    ttl_minutes: int,
) -> str:
    raw = f"atulya_{challenge_type}_{secrets.token_urlsafe(32)}"
    await pool.execute(
        f"""
        UPDATE {fq("auth_challenges")} SET consumed_at = NOW()
        WHERE challenge_type = $1 AND lower(email) = lower($2)
          AND consumed_at IS NULL
        """,
        challenge_type,
        email,
    )
    await pool.execute(
        f"""
        INSERT INTO {fq("auth_challenges")}
            (principal_id, email, challenge_type, token_hash, payload, expires_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        uuid.UUID(principal_id) if principal_id else None,
        email,
        challenge_type,
        hash_session_token(raw),
        json.dumps(payload),
        datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
    )
    return raw


async def _consume_challenge(pool: Any, token: str, challenge_type: str) -> Any:
    row = await pool.fetchrow(
        f"""
        UPDATE {fq("auth_challenges")}
        SET consumed_at = NOW()
        WHERE token_hash = $1 AND challenge_type = $2
          AND consumed_at IS NULL AND expires_at > NOW()
        RETURNING id::text, principal_id::text, email, payload
        """,
        hash_session_token(token),
        challenge_type,
    )
    if not row:
        raise HTTPException(status_code=400, detail={"code": "invalid_or_expired_token"})
    return row


async def _login_response(
    pool: Any,
    principal_id: str,
    *,
    active_org_id: str | None,
    request: Request,
) -> LoginResponse:
    platform = bool(
        await pool.fetchval(
            f"""
            SELECT 1 FROM {fq("access_grants")}
            WHERE org_id IS NULL AND subject_type = 'principal' AND subject_id = $1
              AND action = 'system.admin' AND scope_type = 'system' AND scope_id = '*'
            """,
            principal_id,
        )
    )
    token, expires_at = await issue_session(
        pool,
        principal_id,
        active_org_id=active_org_id,
        is_platform_admin=platform,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    identity = await resolve_identity(pool, token)
    if identity is None:
        raise HTTPException(status_code=500, detail={"code": "session_creation_failed"})
    return LoginResponse(token=token, expires_at=expires_at.isoformat(), principal=identity)


def create_auth_router(memory: Any) -> APIRouter:
    router = APIRouter()

    async def current(authorization: str | None) -> tuple[Any, str, ResolvedIdentity]:
        token = _bearer(authorization)
        if not token:
            raise HTTPException(status_code=401, detail={"code": "session_required"})
        pool = await memory._get_pool()
        identity = await resolve_identity(pool, token)
        if identity is None:
            raise HTTPException(status_code=401, detail={"code": "invalid_or_expired_session"})
        return pool, token, identity

    @router.get("/signup-state", response_model=SignupStateResponse, operation_id="auth_signup_state")
    async def signup_state() -> SignupStateResponse:
        pool = await memory._get_pool()
        count = int(await pool.fetchval(f"SELECT COUNT(*) FROM {fq('orgs')}") or 0)
        mode = _signup_mode()
        return SignupStateResponse(
            mode=mode,
            available=mode == "public" or (mode == "bootstrap" and count == 0),
            org_count=count,
            verification_required=verification_required(),
        )

    @router.post("/signup", status_code=status.HTTP_202_ACCEPTED, operation_id="auth_signup")
    async def signup(body: SignupRequest, request: Request) -> PendingAuthResponse | LoginResponse:
        pool = await memory._get_pool()
        mode = _signup_mode()
        org_count = int(await pool.fetchval(f"SELECT COUNT(*) FROM {fq('orgs')}") or 0)
        if mode == "disabled" or (mode == "bootstrap" and org_count > 0):
            raise HTTPException(status_code=403, detail={"code": "signup_unavailable"})
        email = body.owner_email.strip().lower()
        await enforce_rate_limit(pool, f"signup:ip:{_client_ip(request)}", limit=3, window_seconds=3600)
        if await pool.fetchval(f"SELECT 1 FROM {fq('principals')} WHERE lower(email) = $1", email):
            raise HTTPException(status_code=409, detail={"code": "account_exists"})
        normalize_org_slug(body.org_slug)
        if await pool.fetchval(f"SELECT 1 FROM {fq('orgs')} WHERE slug = $1", body.org_slug):
            raise HTTPException(status_code=409, detail={"code": "workspace_exists"})
        principal_id = str(uuid.uuid4())
        verified_at = None if verification_required() else datetime.now(timezone.utc)
        payload = {"org_slug": body.org_slug, "org_name": body.org_name}
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute(
                f"""
                INSERT INTO {fq("principals")}
                    (id, email, display_name, principal_type, email_verified_at)
                VALUES ($1, $2, $3, 'user', $4)
                """,
                uuid.UUID(principal_id),
                email,
                body.owner_name.strip(),
                verified_at,
            )
            await connection.execute(
                f"INSERT INTO {fq('principal_credentials')} (principal_id, password_hash) VALUES ($1, $2)",
                uuid.UUID(principal_id),
                hash_password(body.owner_password),
            )
        if verification_required():
            token = await _challenge(
                pool,
                challenge_type="verify_email",
                email=email,
                principal_id=principal_id,
                payload=payload,
                ttl_minutes=30,
            )
            await send_auth_email(
                recipient=email,
                subject="Verify your Atulya account",
                text=f"Verify your account: {_public_url()}/verify?token={token}\nThis link expires in 30 minutes.",
            )
            await write_audit(pool, None, "auth.signup.pending", target_type="principal", target_id=principal_id)
            return PendingAuthResponse(status="verification_pending", verification_required=True)
        try:
            org_id = await provision_workspace(
                memory,
                pool,
                principal_id,
                slug=str(payload["org_slug"]),
                name=str(payload["org_name"]),
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(status_code=409, detail={"code": "workspace_exists"}) from exc
        return await _login_response(pool, principal_id, active_org_id=org_id, request=request)

    @router.post("/verify", response_model=LoginResponse, operation_id="auth_verify_email")
    async def verify_email(body: TokenRequest, request: Request) -> LoginResponse:
        pool = await memory._get_pool()
        async with pool.acquire() as connection, connection.transaction():
            challenge = await connection.fetchrow(
                f"""
                SELECT id, principal_id::text, payload
                FROM {fq("auth_challenges")}
                WHERE token_hash = $1 AND challenge_type = 'verify_email'
                  AND consumed_at IS NULL AND expires_at > NOW()
                FOR UPDATE
                """,
                hash_session_token(body.token),
            )
            if not challenge:
                raise HTTPException(status_code=400, detail={"code": "invalid_or_expired_token"})
            principal_id = challenge["principal_id"]
            payload = decode_jsonb(challenge["payload"], {})
            org_id = await provision_workspace(
                memory,
                pool,
                principal_id,
                slug=str(payload["org_slug"]),
                name=str(payload["org_name"]),
            )
            await connection.execute(
                f"UPDATE {fq('principals')} SET email_verified_at = NOW() WHERE id = $1",
                uuid.UUID(principal_id),
            )
            await connection.execute(
                f"UPDATE {fq('auth_challenges')} SET consumed_at = NOW() WHERE id = $1",
                challenge["id"],
            )
            response = await _login_response(
                connection,
                principal_id,
                active_org_id=org_id,
                request=request,
            )
            await write_audit(connection, response.principal, "auth.email_verified", org_id=org_id)
        return response

    @router.post("/resend-verification", status_code=202, operation_id="auth_resend_verification")
    async def resend_verification(body: EmailRequest, request: Request) -> PendingAuthResponse:
        pool = await memory._get_pool()
        email = body.email.strip().lower()
        await enforce_rate_limit(pool, f"verify:{email}", limit=3, window_seconds=3600)
        row = await pool.fetchrow(
            f"SELECT id::text FROM {fq('principals')} WHERE lower(email) = $1 AND email_verified_at IS NULL",
            email,
        )
        if row:
            prior = await pool.fetchrow(
                f"""
                SELECT payload FROM {fq("auth_challenges")}
                WHERE principal_id = $1 AND challenge_type = 'verify_email'
                ORDER BY created_at DESC LIMIT 1
                """,
                uuid.UUID(row["id"]),
            )
            if prior:
                token = await _challenge(
                    pool,
                    challenge_type="verify_email",
                    email=email,
                    principal_id=row["id"],
                    payload=decode_jsonb(prior["payload"], {}),
                    ttl_minutes=30,
                )
                await send_auth_email(
                    recipient=email,
                    subject="Verify your Atulya account",
                    text=f"Verify your account: {_public_url()}/verify?token={token}",
                )
        return PendingAuthResponse(status="accepted", verification_required=True)

    @router.post("/login", response_model=LoginResponse, operation_id="auth_login")
    async def login(body: LoginRequest, request: Request) -> LoginResponse:
        pool = await memory._get_pool()
        email = body.email.strip().lower()
        rate_bucket = f"login:{email}:{_client_ip(request)}"
        await check_rate_limit(pool, rate_bucket, limit=5, window_seconds=900)
        row = await pool.fetchrow(
            f"""
            SELECT p.id::text, p.email_verified_at, p.last_active_org_id::text, c.password_hash
            FROM {fq("principals")} p
            JOIN {fq("principal_credentials")} c ON c.principal_id = p.id
            WHERE lower(p.email) = $1 AND p.status = 'active' AND p.principal_type = 'user'
            """,
            email,
        )
        if not row or not verify_password(body.password, row["password_hash"]):
            await enforce_rate_limit(pool, rate_bucket, limit=5, window_seconds=900)
            await write_audit(pool, None, "auth.login", result="denied", metadata={"email": email})
            raise HTTPException(status_code=401, detail={"code": "invalid_login"})
        await clear_rate_limit(pool, rate_bucket)
        if password_needs_rehash(row["password_hash"]):
            await pool.execute(
                f"UPDATE {fq('principal_credentials')} SET password_hash = $2 WHERE principal_id = $1",
                uuid.UUID(row["id"]),
                hash_password(body.password),
            )
        if verification_required() and row["email_verified_at"] is None:
            raise HTTPException(status_code=403, detail={"code": "email_verification_required"})
        response = await _login_response(
            pool,
            row["id"],
            active_org_id=row["last_active_org_id"],
            request=request,
        )
        await write_audit(pool, response.principal, "auth.login", org_id=response.principal.active_org_id)
        return response

    @router.post("/logout", operation_id="auth_logout")
    async def logout(authorization: str | None = Header(default=None)) -> dict[str, bool]:
        token = _bearer(authorization)
        if token:
            pool = await memory._get_pool()
            identity = await resolve_identity(pool, token)
            await pool.execute(
                f"""
                UPDATE {fq("principal_sessions")}
                SET revoked_at = NOW(), revocation_reason = 'logout'
                WHERE token_hash = $1 AND revoked_at IS NULL
                """,
                hash_session_token(token),
            )
            if identity:
                await write_audit(
                    pool,
                    identity,
                    "auth.logout",
                    org_id=identity.active_org_id,
                    target_type="session",
                    target_id=identity.session_id,
                )
        return {"ok": True}

    @router.get("/me", response_model=ResolvedIdentity, operation_id="auth_me")
    async def me(authorization: str | None = Header(default=None)) -> ResolvedIdentity:
        _, _, identity = await current(authorization)
        return identity

    @router.post("/switch-workspace", response_model=LoginResponse, operation_id="auth_switch_workspace")
    async def switch_workspace(
        body: WorkspaceSwitchRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> LoginResponse:
        pool, token, identity = await current(authorization)
        if identity.session_id is None or not any(item.org_id == body.org_id for item in identity.memberships):
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied"})
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute(
                f"""
                UPDATE {fq("principal_sessions")} SET revoked_at = NOW(), revocation_reason = 'workspace_switch'
                WHERE token_hash = $1
                """,
                hash_session_token(token),
            )
            await connection.execute(
                f"UPDATE {fq('principals')} SET last_active_org_id = $2 WHERE id = $1",
                uuid.UUID(identity.principal_id),
                uuid.UUID(body.org_id),
            )
            response = await _login_response(
                connection,
                identity.principal_id,
                active_org_id=body.org_id,
                request=request,
            )
            await write_audit(
                connection,
                response.principal,
                "auth.workspace_switch",
                org_id=body.org_id,
                target_type="org",
                target_id=body.org_id,
            )
            return response

    @router.get("/sessions", response_model=list[SessionResponse], operation_id="auth_list_sessions")
    async def sessions(authorization: str | None = Header(default=None)) -> list[SessionResponse]:
        pool, _, identity = await current(authorization)
        rows = await pool.fetch(
            f"""
            SELECT id::text, token_prefix, created_at::text, expires_at::text,
                   last_used_at::text, ip_address::text, user_agent
            FROM {fq("principal_sessions")}
            WHERE principal_id = $1 AND revoked_at IS NULL AND expires_at > NOW()
              AND COALESCE(idle_expires_at, expires_at) > NOW()
            ORDER BY created_at DESC
            """,
            uuid.UUID(identity.principal_id),
        )
        return [SessionResponse(**dict(row), current=row["id"] == identity.session_id) for row in rows]

    @router.delete("/sessions/{session_id}", operation_id="auth_revoke_session")
    async def revoke_session(
        session_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, bool]:
        pool, _, identity = await current(authorization)
        result = await pool.execute(
            f"""
            UPDATE {fq("principal_sessions")}
            SET revoked_at = NOW(), revocation_reason = 'user_revoked'
            WHERE id = $1 AND principal_id = $2 AND revoked_at IS NULL
            """,
            uuid.UUID(session_id),
            uuid.UUID(identity.principal_id),
        )
        if result.endswith("1"):
            await write_audit(
                pool,
                identity,
                "auth.session_revoke",
                org_id=identity.active_org_id,
                target_type="session",
                target_id=session_id,
            )
        return {"ok": result.endswith("1")}

    @router.post("/forgot-password", status_code=202, operation_id="auth_forgot_password")
    async def forgot_password(body: EmailRequest) -> PendingAuthResponse:
        pool = await memory._get_pool()
        email = body.email.strip().lower()
        await enforce_rate_limit(pool, f"reset:{email}", limit=3, window_seconds=3600)
        row = await pool.fetchrow(f"SELECT id::text FROM {fq('principals')} WHERE lower(email) = $1", email)
        if row:
            token = await _challenge(
                pool,
                challenge_type="reset_password",
                email=email,
                principal_id=row["id"],
                payload={},
                ttl_minutes=30,
            )
            await send_auth_email(
                recipient=email,
                subject="Reset your Atulya password",
                text=f"Reset your password: {_public_url()}/reset-password?token={token}",
            )
        return PendingAuthResponse(status="accepted")

    @router.post("/reset-password", operation_id="auth_reset_password")
    async def reset_password(body: PasswordResetRequest) -> dict[str, bool]:
        pool = await memory._get_pool()
        async with pool.acquire() as connection, connection.transaction():
            challenge = await _consume_challenge(connection, body.token, "reset_password")
            principal_id = challenge["principal_id"]
            await connection.execute(
                f"""
                UPDATE {fq("principal_credentials")}
                SET password_hash = $2, password_changed_at = NOW()
                WHERE principal_id = $1
                """,
                uuid.UUID(principal_id),
                hash_password(body.password),
            )
            await connection.execute(
                f"""
                UPDATE {fq("principal_sessions")}
                SET revoked_at = NOW(), revocation_reason = 'password_reset'
                WHERE principal_id = $1 AND revoked_at IS NULL
                """,
                uuid.UUID(principal_id),
            )
            await write_audit(
                connection,
                None,
                "auth.password_reset",
                target_type="principal",
                target_id=principal_id,
            )
        return {"ok": True}

    return router
