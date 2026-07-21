"""Canonical database identity resolution and RBAC/ABAC policy evaluation."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from atulya_api.auth import (
    ALL_ACTIONS,
    ORG_ACTIONS,
    fq,
    generate_session,
    hash_secret,
    hash_session_token,
    key_prefix,
    normalize_org_slug,
    role_actions,
    schema_for_org,
)


class MembershipInfo(BaseModel):
    id: str
    org_id: str
    org_slug: str
    org_name: str
    schema_name: str
    role_id: str
    role: str
    status: str


class ResolvedIdentity(BaseModel):
    principal_id: str
    principal_type: str
    email: str | None
    display_name: str
    email_verified: bool
    session_id: str | None = None
    api_key_id: str | None = None
    active_org_id: str | None = None
    # Compatibility alias for one release while clients move to active_org_id.
    org_id: str | None = None
    org_slug: str | None = None
    org_name: str | None = None
    schema_name: str = "public"
    membership_id: str | None = None
    role_id: str | None = None
    role: str = "user"
    memberships: list[MembershipInfo] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    action_scopes: dict[str, list[str]] = Field(default_factory=dict)
    is_superuser: bool = False

    def can(self, action: str, *, org_id: str | None = None, bank_id: str | None = None) -> bool:
        if action not in self.allowed_actions:
            return False
        scopes = set(self.action_scopes.get(action, []))
        if action == "system.admin":
            return "system:*" in scopes
        if org_id and org_id != self.active_org_id:
            return False
        if "org:*" in scopes:
            return True
        return bool(bank_id and f"bank:{bank_id}" in scopes)


BUILTIN_ROLE_ACTIONS: dict[str, frozenset[str]] = {
    "owner": ORG_ACTIONS,
    "admin": ORG_ACTIONS,
    "operator": role_actions("operator"),
    "viewer": role_actions("viewer"),
    "service": frozenset(),
}


async def seed_builtin_roles(pool: Any, org_id: str) -> None:
    for role_name, actions in BUILTIN_ROLE_ACTIONS.items():
        role_id = await pool.fetchval(
            f"""
            INSERT INTO {fq("roles")} (org_id, name, description, is_builtin)
            VALUES ($1, $2, $3, TRUE)
            ON CONFLICT (org_id, name) DO UPDATE SET is_builtin = TRUE
            RETURNING id
            """,
            uuid.UUID(org_id),
            role_name,
            f"Built-in {role_name} role",
        )
        await pool.executemany(
            f"""
            INSERT INTO {fq("role_actions")} (role_id, action)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
            """,
            [(role_id, action) for action in sorted(actions)],
        )


async def provision_workspace(memory: Any, pool: Any, principal_id: str, *, slug: str, name: str) -> str:
    normalized_slug = normalize_org_slug(slug)
    schema_name = schema_for_org(normalized_slug)
    async with pool.acquire() as connection, connection.transaction():
        org = await connection.fetchrow(
            f"""
            INSERT INTO {fq("orgs")} (slug, name, schema_name, status)
            VALUES ($1, $2, $3, 'provisioning')
            RETURNING id::text
            """,
            normalized_slug,
            name.strip(),
            schema_name,
        )
        org_id = org["id"]
        await seed_builtin_roles(connection, org_id)
        owner_role_id = await connection.fetchval(
            f"SELECT id FROM {fq('roles')} WHERE org_id = $1 AND name = 'owner'",
            uuid.UUID(org_id),
        )
        membership_id = await connection.fetchval(
            f"""
            INSERT INTO {fq("org_memberships")} (org_id, principal_id, role_id, status)
            VALUES ($1, $2, $3, 'active') RETURNING id
            """,
            uuid.UUID(org_id),
            uuid.UUID(principal_id),
            owner_role_id,
        )
        await connection.execute(
            f"INSERT INTO {fq('membership_scopes')} (membership_id, scope_type, scope_id) VALUES ($1, 'org', '*')",
            membership_id,
        )
    try:
        from atulya_api.migrations import run_migrations

        if not getattr(memory, "db_url", None):
            raise RuntimeError("Database URL unavailable for workspace provisioning")
        await asyncio.to_thread(run_migrations, memory.db_url, schema=schema_name)
        await pool.execute(
            f"UPDATE {fq('orgs')} SET status = 'active', updated_at = NOW() WHERE id = $1",
            uuid.UUID(org_id),
        )
        await pool.execute(
            f"UPDATE {fq('principals')} SET last_active_org_id = $2 WHERE id = $1",
            uuid.UUID(principal_id),
            uuid.UUID(org_id),
        )
        return org_id
    except Exception:
        await pool.execute(
            f"UPDATE {fq('orgs')} SET status = 'failed', updated_at = NOW() WHERE id = $1",
            uuid.UUID(org_id),
        )
        raise


async def _memberships(pool: Any, principal_id: str) -> list[MembershipInfo]:
    rows = await pool.fetch(
        f"""
        SELECT
            m.id::text, m.org_id::text, o.slug AS org_slug, o.name AS org_name,
            o.schema_name, m.role_id::text, r.name AS role, m.status
        FROM {fq("org_memberships")} m
        JOIN {fq("orgs")} o ON o.id = m.org_id
        JOIN {fq("roles")} r ON r.id = m.role_id
        WHERE m.principal_id = $1 AND m.status = 'active' AND o.status = 'active'
        ORDER BY o.name, o.slug
        """,
        uuid.UUID(principal_id),
    )
    return [MembershipInfo(**dict(row)) for row in rows]


async def _effective_policy(
    pool: Any,
    principal_id: str,
    membership: MembershipInfo | None,
) -> tuple[list[str], dict[str, list[str]]]:
    actions: set[str] = set()
    scopes: dict[str, set[str]] = {}

    if membership:
        role_rows = await pool.fetch(
            f"SELECT action FROM {fq('role_actions')} WHERE role_id = $1",
            uuid.UUID(membership.role_id),
        )
        scope_rows = await pool.fetch(
            f"SELECT scope_type, scope_id FROM {fq('membership_scopes')} WHERE membership_id = $1",
            uuid.UUID(membership.id),
        )
        membership_scopes = {f"{row['scope_type']}:{row['scope_id']}" for row in scope_rows}
        for row in role_rows:
            action = row["action"]
            actions.add(action)
            scopes.setdefault(action, set()).update(membership_scopes)

    grant_rows = await pool.fetch(
        f"""
        SELECT action, scope_type, scope_id
        FROM {fq("access_grants")}
        WHERE subject_type = 'principal' AND subject_id = $1
          AND (org_id = $2 OR (org_id IS NULL AND scope_type = 'system'))
        """,
        principal_id,
        uuid.UUID(membership.org_id) if membership else None,
    )
    for row in grant_rows:
        action = row["action"]
        actions.add(action)
        scopes.setdefault(action, set()).add(f"{row['scope_type']}:{row['scope_id']}")

    return sorted(actions), {action: sorted(values) for action, values in scopes.items()}


async def _identity_for_principal(
    pool: Any,
    principal_row: Any,
    *,
    session_id: str | None = None,
    api_key_id: str | None = None,
    requested_org_id: str | None = None,
) -> ResolvedIdentity:
    principal_id = principal_row["principal_id"]
    memberships = await _memberships(pool, principal_id)
    preferred_org_id = requested_org_id or principal_row.get("active_org_id") or principal_row.get("last_active_org_id")
    membership = next((item for item in memberships if item.org_id == preferred_org_id), None)
    if membership is None and len(memberships) == 1:
        membership = memberships[0]

    actions, scopes = await _effective_policy(pool, principal_id, membership)
    is_superuser = "system.admin" in actions and "system:*" in scopes.get("system.admin", [])
    return ResolvedIdentity(
        principal_id=principal_id,
        principal_type=principal_row["principal_type"],
        email=principal_row["email"],
        display_name=principal_row["display_name"],
        email_verified=principal_row["email_verified_at"] is not None,
        session_id=session_id,
        api_key_id=api_key_id,
        active_org_id=membership.org_id if membership else None,
        org_id=membership.org_id if membership else None,
        org_slug=membership.org_slug if membership else None,
        org_name=membership.org_name if membership else None,
        schema_name=membership.schema_name if membership else "public",
        membership_id=membership.id if membership else None,
        role_id=membership.role_id if membership else None,
        role=membership.role if membership else ("platform_admin" if is_superuser else "user"),
        memberships=memberships,
        allowed_actions=actions,
        action_scopes=scopes,
        is_superuser=is_superuser,
    )


async def resolve_identity(pool: Any, raw_token: str) -> ResolvedIdentity | None:
    if raw_token.startswith("atulya_sess_"):
        row = await pool.fetchrow(
            f"""
            SELECT
                p.id::text AS principal_id, p.email, p.display_name, p.principal_type,
                p.email_verified_at, p.last_active_org_id::text,
                s.id::text AS session_id, s.active_org_id::text, s.last_used_at
            FROM {fq("principal_sessions")} s
            JOIN {fq("principals")} p ON p.id = s.principal_id
            WHERE s.token_hash = $1 AND s.revoked_at IS NULL
              AND s.expires_at > NOW()
              AND COALESCE(s.idle_expires_at, s.expires_at) > NOW()
              AND p.status = 'active'
            """,
            hash_session_token(raw_token),
        )
        if not row:
            return None
        identity = await _identity_for_principal(
            pool,
            row,
            session_id=row["session_id"],
            requested_org_id=row["active_org_id"],
        )
        idle_minutes = 30 if identity.is_superuser else 60
        await pool.execute(
            f"""
            UPDATE {fq("principal_sessions")}
            SET last_used_at = NOW(), idle_expires_at = NOW() + ($2 * INTERVAL '1 minute')
            WHERE id = $1
            """,
            uuid.UUID(row["session_id"]),
            idle_minutes,
        )
        return identity

    key_hash = hash_secret(raw_token, version=2)
    row = await pool.fetchrow(
        f"""
        SELECT
            p.id::text AS principal_id, p.email, p.display_name, p.principal_type,
            p.email_verified_at, p.last_active_org_id::text,
            k.id::text AS api_key_id, m.org_id::text AS active_org_id
        FROM {fq("api_keys")} k
        JOIN {fq("principals")} p ON p.id = k.principal_id
        JOIN (
            SELECT principal_id, MIN(org_id) AS org_id
            FROM {fq("org_memberships")}
            WHERE status = 'active'
            GROUP BY principal_id
            HAVING COUNT(*) = 1
        ) m ON m.principal_id = p.id
        WHERE (k.key_hash = $1 OR k.key_hash = $2)
          AND k.revoked_at IS NULL AND (k.expires_at IS NULL OR k.expires_at > NOW())
          AND p.status = 'active' AND p.principal_type = 'service'
        """,
        key_hash,
        hash_secret(raw_token, version=1),
    )
    if not row:
        return None
    await pool.execute(f"UPDATE {fq('api_keys')} SET last_used_at = NOW() WHERE id = $1", uuid.UUID(row["api_key_id"]))
    return await _identity_for_principal(
        pool,
        row,
        api_key_id=row["api_key_id"],
        requested_org_id=row["active_org_id"],
    )


async def issue_session(
    pool: Any,
    principal_id: str,
    *,
    active_org_id: str | None,
    is_platform_admin: bool = False,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, datetime]:
    session = generate_session()
    absolute_hours = 4 if is_platform_admin else 12
    expires_at = datetime.now(timezone.utc) + timedelta(hours=absolute_hours)
    idle_minutes = 30 if is_platform_admin else 60
    await pool.execute(
        f"""
        INSERT INTO {fq("principal_sessions")}
            (principal_id, token_hash, token_prefix, hash_version, expires_at,
             idle_expires_at, active_org_id, ip_address, user_agent)
        VALUES ($1, $2, $3, 2, $4, NOW() + ($5 * INTERVAL '1 minute'), $6, $7, $8)
        """,
        uuid.UUID(principal_id),
        session.token_hash,
        key_prefix(session.raw_token),
        expires_at,
        idle_minutes,
        uuid.UUID(active_org_id) if active_org_id else None,
        ip_address,
        user_agent,
    )
    return session.raw_token, expires_at


def permission_error(identity: ResolvedIdentity, action: str, scope: str) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "code": "permission_denied",
            "missing_action": action,
            "required_scope": scope,
            "identity": {
                "principal_id": identity.principal_id,
                "active_org_id": identity.active_org_id,
                "role": identity.role,
            },
        },
    )


def require_permission(
    identity: ResolvedIdentity,
    action: str,
    *,
    org_id: str | None = None,
    bank_id: str | None = None,
) -> None:
    scope = "system:*" if action == "system.admin" else (f"bank:{bank_id}" if bank_id else "org:*")
    if not identity.can(action, org_id=org_id, bank_id=bank_id):
        raise permission_error(identity, action, scope)


async def write_audit(
    pool: Any,
    identity: ResolvedIdentity | None,
    action: str,
    *,
    org_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    result: str = "success",
    metadata: dict[str, Any] | None = None,
) -> None:
    await pool.execute(
        f"""
        INSERT INTO {fq("audit_events")}
            (org_id, actor_principal_id, action, target_type, target_id, result, metadata)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        uuid.UUID(org_id) if org_id else None,
        uuid.UUID(identity.principal_id) if identity else None,
        action,
        target_type,
        target_id,
        result,
        json.dumps(metadata or {}),
    )


async def enforce_rate_limit(
    pool: Any,
    bucket: str,
    *,
    limit: int,
    window_seconds: int,
) -> None:
    row = await pool.fetchrow(
        f"""
        INSERT INTO {fq("auth_rate_limits")} (bucket, attempts, window_started_at)
        VALUES ($1, 1, NOW())
        ON CONFLICT (bucket) DO UPDATE SET
            attempts = CASE
                WHEN {fq("auth_rate_limits")}.window_started_at < NOW() - ($2 * INTERVAL '1 second') THEN 1
                ELSE {fq("auth_rate_limits")}.attempts + 1
            END,
            window_started_at = CASE
                WHEN {fq("auth_rate_limits")}.window_started_at < NOW() - ($2 * INTERVAL '1 second') THEN NOW()
                ELSE {fq("auth_rate_limits")}.window_started_at
            END
        RETURNING attempts, window_started_at
        """,
        bucket,
        window_seconds,
    )
    if row and row["attempts"] > limit:
        raise HTTPException(
            status_code=429,
            detail={"code": "rate_limited", "retry_after_seconds": window_seconds},
            headers={"Retry-After": str(window_seconds)},
        )


async def check_rate_limit(
    pool: Any,
    bucket: str,
    *,
    limit: int,
    window_seconds: int,
) -> None:
    attempts = await pool.fetchval(
        f"""
        SELECT attempts FROM {fq("auth_rate_limits")}
        WHERE bucket = $1 AND window_started_at >= NOW() - ($2 * INTERVAL '1 second')
        """,
        bucket,
        window_seconds,
    )
    if attempts is not None and int(attempts) >= limit:
        raise HTTPException(
            status_code=429,
            detail={"code": "rate_limited", "retry_after_seconds": window_seconds},
            headers={"Retry-After": str(window_seconds)},
        )


async def clear_rate_limit(pool: Any, bucket: str) -> None:
    await pool.execute(f"DELETE FROM {fq('auth_rate_limits')} WHERE bucket = $1", bucket)


def auth_mode() -> str:
    return os.getenv("ATULYA_API_AUTH_MODE", "disabled").strip().lower()


def load_auth_extensions() -> tuple[Any | None, Any | None]:
    """Load the canonical database auth stack or configured legacy extensions."""

    from atulya_api.extensions import OperationValidatorExtension, TenantExtension, load_extension

    mode = auth_mode()
    if mode not in {"disabled", "database"}:
        raise RuntimeError("ATULYA_API_AUTH_MODE must be 'disabled' or 'database'")
    if mode == "disabled" and os.getenv("ATULYA_ENVIRONMENT", "development").strip().lower() == "production":
        raise RuntimeError(
            "Production requires ATULYA_API_AUTH_MODE=database; refusing to start with authentication disabled"
        )
    if mode == "database":
        from atulya_api.auth_email import validate_email_settings

        validate_email_settings()
        if os.getenv("ATULYA_ENVIRONMENT", "development").strip().lower() == "production":
            missing = [
                name for name in ("ATULYA_API_KEY_HASH_PEPPER", "ATULYA_API_SESSION_HASH_PEPPER") if not os.getenv(name)
            ]
            if missing:
                raise RuntimeError("Production database auth requires stable secret peppers: " + ", ".join(missing))
        conflicting = [
            name
            for name in ("ATULYA_API_TENANT_EXTENSION", "ATULYA_API_OPERATION_VALIDATOR_EXTENSION")
            if os.getenv(name)
        ]
        if conflicting:
            raise RuntimeError(
                "ATULYA_API_AUTH_MODE=database installs the canonical auth extensions; "
                f"remove conflicting settings: {', '.join(conflicting)}"
            )
        from atulya_api.extensions.builtin.tenant import DbApiKeyTenantExtension
        from atulya_api.extensions.operation_validator import AccessControlOperationValidator

        return AccessControlOperationValidator(config={}), DbApiKeyTenantExtension(
            config={"schema": os.getenv("ATULYA_API_AUTH_SCHEMA", "public")}
        )
    return (
        load_extension("OPERATION_VALIDATOR", OperationValidatorExtension),
        load_extension("TENANT", TenantExtension),
    )


def validate_action(action: str, *, allow_system: bool = False) -> None:
    if action not in ALL_ACTIONS or (action == "system.admin" and not allow_system):
        raise HTTPException(status_code=400, detail={"code": "invalid_action", "action": action})


def org_schema(slug: str) -> str:
    return schema_for_org(slug)
