"""Organization administration API with backend-enforced RBAC and ABAC."""

from __future__ import annotations

import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from atulya_api.auth import (
    ALL_ACTIONS,
    fq,
    generate_api_key,
    hash_password,
    hash_secret,
    hash_session_token,
    key_prefix,
    quote_ident,
)
from atulya_api.auth_email import send_auth_email
from atulya_api.auth_service import (
    ResolvedIdentity,
    enforce_rate_limit,
    provision_workspace,
    require_permission,
    resolve_identity,
    validate_action,
    write_audit,
)
from atulya_api.engine.jsonb_compat import decode_jsonb


class WorkspaceCreateRequest(BaseModel):
    slug: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=160)


class RoleCreateRequest(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,62}$")
    description: str | None = Field(default=None, max_length=500)
    actions: list[str]


class RoleUpdateRequest(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    actions: list[str]


class MembershipUpdateRequest(BaseModel):
    role_id: str | None = None
    status: str | None = None
    bank_ids: list[str] | None = None


class InvitationCreateRequest(BaseModel):
    email: str
    role_id: str
    bank_ids: list[str] = Field(default_factory=list)


class InvitationAcceptRequest(BaseModel):
    token: str
    display_name: str | None = None
    password: str | None = Field(default=None, min_length=12)


class ServiceAccountCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    role_id: str
    bank_ids: list[str] = Field(default_factory=list)


class ServiceAccountUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    role_id: str | None = None
    status: str | None = None
    bank_ids: list[str] | None = None


class KeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    expires_days: int = Field(default=90, ge=1, le=365)
    description: str | None = Field(default=None, max_length=500)


class KeySecretResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    raw_key: str
    expires_at: str


class DirectGrantRequest(BaseModel):
    principal_id: str
    action: str
    scope_type: str
    scope_id: str


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    return authorization[7:].strip() if authorization.lower().startswith("bearer ") else authorization.strip()


async def _org(pool: Any, org_id: str) -> Any:
    row = await pool.fetchrow(
        f"SELECT id::text, slug, name, schema_name, status, created_at::text FROM {fq('orgs')} WHERE id = $1",
        uuid.UUID(org_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail={"code": "organization_not_found"})
    return row


async def _role_actions(pool: Any, role_id: str, org_id: str) -> set[str]:
    rows = await pool.fetch(
        f"""
        SELECT ra.action
        FROM {fq("roles")} r JOIN {fq("role_actions")} ra ON ra.role_id = r.id
        WHERE r.id = $1 AND r.org_id = $2
        """,
        uuid.UUID(role_id),
        uuid.UUID(org_id),
    )
    if not rows:
        exists = await pool.fetchval(
            f"SELECT 1 FROM {fq('roles')} WHERE id = $1 AND org_id = $2",
            uuid.UUID(role_id),
            uuid.UUID(org_id),
        )
        if not exists:
            raise HTTPException(status_code=404, detail={"code": "role_not_found"})
    return {row["action"] for row in rows}


async def _validated_role(pool: Any, role_id: str, org_id: str) -> tuple[str, set[str]]:
    row = await pool.fetchrow(
        f"SELECT name FROM {fq('roles')} WHERE id = $1 AND org_id = $2",
        uuid.UUID(role_id),
        uuid.UUID(org_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail={"code": "role_not_found"})
    return row["name"], await _role_actions(pool, role_id, org_id)


async def _validate_bank_ids(pool: Any, schema_name: str, bank_ids: list[str]) -> list[str]:
    normalized = sorted(set(bank_ids))
    if not normalized:
        return []
    rows = await pool.fetch(
        f"SELECT bank_id FROM {quote_ident(schema_name)}.banks WHERE bank_id = ANY($1::text[])",
        normalized,
    )
    found = {row["bank_id"] for row in rows}
    missing = [bank_id for bank_id in normalized if bank_id not in found]
    if missing:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_bank_scope", "bank_ids": missing},
        )
    return normalized


async def _replace_membership_scopes(
    connection: Any,
    membership_id: uuid.UUID,
    role_name: str,
    bank_ids: list[str],
) -> None:
    await connection.execute(
        f"DELETE FROM {fq('membership_scopes')} WHERE membership_id = $1",
        membership_id,
    )
    if role_name in {"owner", "admin"}:
        await connection.execute(
            f"INSERT INTO {fq('membership_scopes')} (membership_id, scope_type, scope_id) VALUES ($1, 'org', '*')",
            membership_id,
        )
    elif bank_ids:
        await connection.executemany(
            f"INSERT INTO {fq('membership_scopes')} (membership_id, scope_type, scope_id) VALUES ($1, 'bank', $2)",
            [(membership_id, bank_id) for bank_id in bank_ids],
        )


async def _effective_permissions(pool: Any, org_id: str, principal_id: str) -> dict[str, Any]:
    membership = await pool.fetchrow(
        f"""
        SELECT m.id, r.name AS role
        FROM {fq("org_memberships")} m JOIN {fq("roles")} r ON r.id = m.role_id
        WHERE m.org_id = $1 AND m.principal_id = $2 AND m.status = 'active'
        """,
        uuid.UUID(org_id),
        uuid.UUID(principal_id),
    )
    if not membership:
        raise HTTPException(status_code=404, detail={"code": "principal_not_in_organization"})
    rows = await pool.fetch(
        f"""
        SELECT ra.action, ms.scope_type, ms.scope_id, 'role' AS source
        FROM {fq("org_memberships")} m
        JOIN {fq("role_actions")} ra ON ra.role_id = m.role_id
        JOIN {fq("membership_scopes")} ms ON ms.membership_id = m.id
        WHERE m.org_id = $1 AND m.principal_id = $2 AND m.status = 'active'
        UNION ALL
        SELECT g.action, g.scope_type, g.scope_id, 'direct' AS source
        FROM {fq("access_grants")} g
        WHERE g.org_id = $1 AND g.subject_type = 'principal' AND g.subject_id = $3
        ORDER BY action, scope_type, scope_id
        """,
        uuid.UUID(org_id),
        uuid.UUID(principal_id),
        principal_id,
    )
    scopes: dict[str, set[str]] = {}
    sources: dict[str, set[str]] = {}
    for row in rows:
        scopes.setdefault(row["action"], set()).add(f"{row['scope_type']}:{row['scope_id']}")
        sources.setdefault(row["action"], set()).add(row["source"])
    return {
        "principal_id": principal_id,
        "role": membership["role"],
        "allowed_actions": sorted(scopes),
        "action_scopes": {action: sorted(values) for action, values in scopes.items()},
        "sources": {action: sorted(values) for action, values in sources.items()},
    }


def create_organization_router(memory: Any) -> APIRouter:
    router = APIRouter()

    async def current(authorization: str | None) -> tuple[Any, ResolvedIdentity]:
        token = _bearer(authorization)
        if not token:
            raise HTTPException(status_code=401, detail={"code": "session_required"})
        pool = await memory._get_pool()
        identity = await resolve_identity(pool, token)
        if identity is None:
            raise HTTPException(status_code=401, detail={"code": "invalid_or_expired_credential"})
        return pool, identity

    async def authorized(
        authorization: str | None,
        org_id: str,
        action: str,
    ) -> tuple[Any, ResolvedIdentity, Any]:
        pool, identity = await current(authorization)
        try:
            require_permission(identity, action, org_id=org_id)
        except HTTPException:
            await write_audit(
                pool,
                identity,
                "access.denied",
                org_id=identity.active_org_id,
                target_type="organization_route",
                target_id=org_id,
                result="denied",
                metadata={"missing_action": action, "required_scope": "org:*"},
            )
            raise
        return pool, identity, await _org(pool, org_id)

    @router.get("", operation_id="org_list_memberships")
    async def list_workspaces(authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
        _, identity = await current(authorization)
        return [membership.model_dump() for membership in identity.memberships]

    @router.post("", status_code=201, operation_id="org_create_workspace")
    async def create_workspace(
        body: WorkspaceCreateRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        pool, identity = await current(authorization)
        if identity.principal_type != "user" or not identity.email_verified:
            raise HTTPException(status_code=403, detail={"code": "verified_user_required"})
        await enforce_rate_limit(
            pool,
            f"workspace-create:{identity.principal_id}",
            limit=3,
            window_seconds=86400,
        )
        try:
            org_id = await provision_workspace(
                memory,
                pool,
                identity.principal_id,
                slug=body.slug,
                name=body.name,
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(status_code=409, detail={"code": "workspace_exists"}) from exc
        await write_audit(pool, identity, "org.create", org_id=org_id, target_type="org", target_id=org_id)
        return {"id": org_id, "status": "active"}

    @router.get("/{org_id}", operation_id="org_get_overview")
    async def overview(
        org_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        pool, identity, org = await authorized(authorization, org_id, "bank.read")
        counts = await pool.fetchrow(
            f"""
            SELECT
              (SELECT COUNT(*) FROM {fq("org_memberships")} WHERE org_id = $1 AND status = 'active') AS members,
              (SELECT COUNT(*) FROM {fq("principals")} p JOIN {fq("org_memberships")} m ON m.principal_id = p.id
               WHERE m.org_id = $1 AND p.principal_type = 'service' AND m.status = 'active') AS services,
              (SELECT COUNT(*) FROM {fq("roles")} WHERE org_id = $1) AS roles
            """,
            uuid.UUID(org_id),
        )
        schema = quote_ident(org["schema_name"])
        bank_count = int(await pool.fetchval(f"SELECT COUNT(*) FROM {schema}.banks") or 0)
        await write_audit(pool, identity, "org.read", org_id=org_id, target_type="org", target_id=org_id)
        return {**dict(org), **dict(counts), "banks": bank_count}

    @router.get("/{org_id}/members", operation_id="org_list_members")
    async def list_members(
        org_id: str,
        authorization: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        pool, _, _ = await authorized(authorization, org_id, "admin.users")
        rows = await pool.fetch(
            f"""
            SELECT m.id::text, m.principal_id::text, p.email, p.display_name, p.principal_type,
                   p.email_verified_at::text, m.role_id::text, r.name AS role, m.status,
                   COALESCE(array_agg(ms.scope_id) FILTER (WHERE ms.scope_type = 'bank'), ARRAY[]::text[]) AS bank_ids,
                   bool_or(ms.scope_type = 'org' AND ms.scope_id = '*') AS org_wide
            FROM {fq("org_memberships")} m
            JOIN {fq("principals")} p ON p.id = m.principal_id
            JOIN {fq("roles")} r ON r.id = m.role_id
            LEFT JOIN {fq("membership_scopes")} ms ON ms.membership_id = m.id
            WHERE m.org_id = $1 AND p.principal_type = 'user'
            GROUP BY m.id, p.id, r.id ORDER BY p.display_name
            """,
            uuid.UUID(org_id),
        )
        return [dict(row) for row in rows]

    @router.patch("/{org_id}/members/{membership_id}", operation_id="org_update_member")
    async def update_member(
        org_id: str,
        membership_id: str,
        body: MembershipUpdateRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, bool]:
        pool, identity, org = await authorized(authorization, org_id, "admin.users")
        if body.status and body.status not in {"active", "disabled"}:
            raise HTTPException(status_code=400, detail={"code": "invalid_membership_status"})
        bank_ids = await _validate_bank_ids(pool, org["schema_name"], body.bank_ids or [])

        async with pool.acquire() as connection, connection.transaction():
            # Serializes owner changes for this organization.
            await connection.fetchval(
                f"SELECT id FROM {fq('orgs')} WHERE id = $1 FOR UPDATE",
                uuid.UUID(org_id),
            )
            target = await connection.fetchrow(
                f"""
                SELECT m.id, m.principal_id, m.role_id::text, m.status, r.name AS role,
                       COALESCE(array_agg(ms.scope_id) FILTER (WHERE ms.scope_type = 'bank'), ARRAY[]::text[]) AS bank_ids
                FROM {fq("org_memberships")} m
                JOIN {fq("roles")} r ON r.id = m.role_id
                LEFT JOIN {fq("membership_scopes")} ms ON ms.membership_id = m.id
                WHERE m.id = $1 AND m.org_id = $2
                GROUP BY m.id, r.id
                """,
                uuid.UUID(membership_id),
                uuid.UUID(org_id),
            )
            if not target:
                raise HTTPException(status_code=404, detail={"code": "membership_not_found"})

            next_role = target["role"]
            next_role_id = body.role_id or target["role_id"]
            if body.role_id:
                next_role, actions = await _validated_role(connection, body.role_id, org_id)
                if not actions.issubset(set(identity.allowed_actions)):
                    raise HTTPException(status_code=403, detail={"code": "role_delegation_exceeds_actor"})
                if next_role == "owner" and identity.role != "owner":
                    raise HTTPException(status_code=403, detail={"code": "owner_role_required"})

            next_status = body.status or target["status"]
            demotes_owner = target["role"] == "owner" and (next_role != "owner" or next_status == "disabled")
            if demotes_owner:
                owner_count = int(
                    await connection.fetchval(
                        f"""
                        SELECT COUNT(*) FROM {fq("org_memberships")} m
                        JOIN {fq("roles")} r ON r.id = m.role_id
                        WHERE m.org_id = $1 AND m.status = 'active' AND r.name = 'owner'
                        """,
                        uuid.UUID(org_id),
                    )
                    or 0
                )
                if owner_count <= 1:
                    raise HTTPException(status_code=409, detail={"code": "last_owner_protected"})

            next_bank_ids = bank_ids if body.bank_ids is not None else list(target["bank_ids"])
            if next_role in {"operator", "viewer"} and not next_bank_ids:
                raise HTTPException(status_code=400, detail={"code": "bank_scope_required"})

            await connection.execute(
                f"""
                UPDATE {fq("org_memberships")}
                SET role_id = $3, status = $4, updated_at = NOW()
                WHERE id = $1 AND org_id = $2
                """,
                uuid.UUID(membership_id),
                uuid.UUID(org_id),
                uuid.UUID(next_role_id),
                next_status,
            )
            if body.bank_ids is not None or body.role_id is not None:
                await _replace_membership_scopes(
                    connection,
                    uuid.UUID(membership_id),
                    next_role,
                    next_bank_ids,
                )
            if next_status == "disabled":
                await connection.execute(
                    f"""
                    UPDATE {fq("principal_sessions")}
                    SET revoked_at = NOW(), revocation_reason = 'membership_disabled'
                    WHERE principal_id = $1 AND active_org_id = $2 AND revoked_at IS NULL
                    """,
                    target["principal_id"],
                    uuid.UUID(org_id),
                )
            await write_audit(
                connection,
                identity,
                "admin.users.update",
                org_id=org_id,
                target_type="membership",
                target_id=membership_id,
                metadata=body.model_dump(exclude_none=True),
            )
        return {"ok": True}

    @router.post("/{org_id}/invitations", status_code=201, operation_id="org_create_invitation")
    async def create_invitation(
        org_id: str,
        body: InvitationCreateRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        pool, identity, org = await authorized(authorization, org_id, "admin.users")
        role_name, actions = await _validated_role(pool, body.role_id, org_id)
        if not actions.issubset(set(identity.allowed_actions)):
            raise HTTPException(status_code=403, detail={"code": "role_delegation_exceeds_actor"})
        if role_name == "owner" and identity.role != "owner":
            raise HTTPException(status_code=403, detail={"code": "owner_role_required"})
        bank_ids = await _validate_bank_ids(pool, org["schema_name"], body.bank_ids)
        if role_name in {"operator", "viewer"} and not bank_ids:
            raise HTTPException(status_code=400, detail={"code": "bank_scope_required"})
        raw = f"atulya_invite_{secrets.token_urlsafe(32)}"
        email = body.email.strip().lower()
        existing_member = await pool.fetchval(
            f"""
            SELECT 1 FROM {fq("principals")} p
            JOIN {fq("org_memberships")} m ON m.principal_id = p.id
            WHERE lower(p.email) = $1 AND m.org_id = $2
            """,
            email,
            uuid.UUID(org_id),
        )
        if existing_member:
            raise HTTPException(status_code=409, detail={"code": "already_a_member"})
        await pool.execute(
            f"""
            UPDATE {fq("auth_challenges")} SET consumed_at = NOW()
            WHERE challenge_type = 'invite' AND lower(email) = $1
              AND consumed_at IS NULL AND payload->>'org_id' = $2
            """,
            email,
            org_id,
        )
        await pool.execute(
            f"""
            INSERT INTO {fq("auth_challenges")}
                (email, challenge_type, token_hash, payload, expires_at)
            VALUES ($1, 'invite', $2, $3, NOW() + INTERVAL '72 hours')
            """,
            email,
            hash_session_token(raw),
            json.dumps(
                {
                    "org_id": org_id,
                    "role_id": body.role_id,
                    "bank_ids": bank_ids,
                    "invited_by": identity.principal_id,
                }
            ),
        )
        public_url = os.getenv("ATULYA_AUTH_PUBLIC_URL", "http://localhost:9999").rstrip("/")
        await send_auth_email(
            recipient=email,
            subject=f"Join {org['name']} on Atulya",
            text=f"Accept your invitation: {public_url}/invite?token={raw}",
        )
        await write_audit(pool, identity, "admin.users.invite", org_id=org_id, metadata={"email": email})
        return {"status": "sent"}

    @router.get("/{org_id}/invitations", operation_id="org_list_invitations")
    async def list_invitations(
        org_id: str,
        authorization: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        pool, _, _ = await authorized(authorization, org_id, "admin.users")
        rows = await pool.fetch(
            f"""
            SELECT c.id::text, c.email, c.payload->>'role_id' AS role_id,
                   r.name AS role, c.created_at::text, c.expires_at::text,
                   CASE
                     WHEN c.consumed_at IS NOT NULL THEN 'closed'
                     WHEN c.expires_at <= NOW() THEN 'expired'
                     ELSE 'pending'
                   END AS status
            FROM {fq("auth_challenges")} c
            LEFT JOIN {fq("roles")} r ON r.id = (c.payload->>'role_id')::uuid
            WHERE c.challenge_type = 'invite' AND c.payload->>'org_id' = $1
            ORDER BY c.created_at DESC
            """,
            org_id,
        )
        return [dict(row) for row in rows]

    @router.delete("/{org_id}/invitations/{invitation_id}", operation_id="org_revoke_invitation")
    async def revoke_invitation(
        org_id: str,
        invitation_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, bool]:
        pool, identity, _ = await authorized(authorization, org_id, "admin.users")
        result = await pool.execute(
            f"""
            UPDATE {fq("auth_challenges")} SET consumed_at = NOW()
            WHERE id = $1 AND challenge_type = 'invite' AND payload->>'org_id' = $2
              AND consumed_at IS NULL
            """,
            uuid.UUID(invitation_id),
            org_id,
        )
        await write_audit(
            pool,
            identity,
            "admin.users.invitation_revoke",
            org_id=org_id,
            target_type="invitation",
            target_id=invitation_id,
        )
        return {"ok": result.endswith("1")}

    @router.post("/invitations/accept", operation_id="org_accept_invitation")
    async def accept_invitation(body: InvitationAcceptRequest) -> dict[str, bool]:
        pool = await memory._get_pool()
        candidate = await pool.fetchrow(
            f"""
            SELECT email, payload FROM {fq("auth_challenges")}
            WHERE token_hash = $1 AND challenge_type = 'invite'
              AND consumed_at IS NULL AND expires_at > NOW()
            """,
            hash_session_token(body.token),
        )
        if not candidate:
            raise HTTPException(status_code=400, detail={"code": "invalid_or_expired_invitation"})
        email = candidate["email"]
        principal_id = await pool.fetchval(
            f"SELECT id::text FROM {fq('principals')} WHERE lower(email) = $1",
            email,
        )
        if not principal_id and (not body.password or not body.display_name):
            raise HTTPException(status_code=422, detail={"code": "account_details_required"})

        async with pool.acquire() as connection, connection.transaction():
            challenge = await connection.fetchrow(
                f"""
                UPDATE {fq("auth_challenges")} SET consumed_at = NOW()
                WHERE token_hash = $1 AND challenge_type = 'invite'
                  AND consumed_at IS NULL AND expires_at > NOW()
                RETURNING email, payload
                """,
                hash_session_token(body.token),
            )
            if not challenge:
                raise HTTPException(status_code=400, detail={"code": "invitation_already_used"})
            payload = decode_jsonb(challenge["payload"], {})
            role_name = await connection.fetchval(
                f"SELECT name FROM {fq('roles')} WHERE id = $1 AND org_id = $2",
                uuid.UUID(payload["role_id"]),
                uuid.UUID(payload["org_id"]),
            )
            if not role_name:
                raise HTTPException(status_code=409, detail={"code": "invitation_role_unavailable"})
            if not principal_id:
                principal_id = str(uuid.uuid4())
                await connection.execute(
                    f"""
                    INSERT INTO {fq("principals")}
                        (id, email, display_name, principal_type, status, email_verified_at)
                    VALUES ($1, $2, $3, 'user', 'active', NOW())
                    """,
                    uuid.UUID(principal_id),
                    email,
                    body.display_name,
                )
                await connection.execute(
                    f"INSERT INTO {fq('principal_credentials')} (principal_id, password_hash) VALUES ($1, $2)",
                    uuid.UUID(principal_id),
                    hash_password(body.password or ""),
                )
            elif await connection.fetchval(
                f"SELECT 1 FROM {fq('org_memberships')} WHERE org_id = $1 AND principal_id = $2",
                uuid.UUID(payload["org_id"]),
                uuid.UUID(principal_id),
            ):
                raise HTTPException(status_code=409, detail={"code": "already_a_member"})
            membership_id = await connection.fetchval(
                f"""
                INSERT INTO {fq("org_memberships")} (org_id, principal_id, role_id, status)
                VALUES ($1, $2, $3, 'active')
                RETURNING id
                """,
                uuid.UUID(payload["org_id"]),
                uuid.UUID(principal_id),
                uuid.UUID(payload["role_id"]),
            )
            await connection.execute(
                f"DELETE FROM {fq('membership_scopes')} WHERE membership_id = $1",
                membership_id,
            )
            if role_name in {"owner", "admin"}:
                await connection.execute(
                    f"INSERT INTO {fq('membership_scopes')} (membership_id, scope_type, scope_id) VALUES ($1, 'org', '*')",
                    membership_id,
                )
            elif payload.get("bank_ids"):
                await connection.executemany(
                    f"INSERT INTO {fq('membership_scopes')} (membership_id, scope_type, scope_id) VALUES ($1, 'bank', $2)",
                    [(membership_id, bank_id) for bank_id in payload["bank_ids"]],
                )
            await connection.execute(
                f"""
                INSERT INTO {fq("audit_events")}
                    (org_id, actor_principal_id, action, target_type, target_id, metadata)
                VALUES ($1, $2, 'auth.invitation_accept', 'membership', $3, $4)
                """,
                uuid.UUID(payload["org_id"]),
                uuid.UUID(principal_id),
                str(membership_id),
                json.dumps({"invited_by": payload.get("invited_by")}),
            )
        return {"ok": True}

    @router.get("/{org_id}/roles", operation_id="org_list_roles")
    async def list_roles(
        org_id: str,
        authorization: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        pool, _, _ = await authorized(authorization, org_id, "admin.grants")
        rows = await pool.fetch(
            f"""
            SELECT r.id::text, r.name, r.description, r.is_builtin,
                   COALESCE(array_agg(ra.action ORDER BY ra.action) FILTER (WHERE ra.action IS NOT NULL), ARRAY[]::text[]) AS actions
            FROM {fq("roles")} r LEFT JOIN {fq("role_actions")} ra ON ra.role_id = r.id
            WHERE r.org_id = $1 GROUP BY r.id ORDER BY r.is_builtin DESC, r.name
            """,
            uuid.UUID(org_id),
        )
        return [dict(row) for row in rows]

    @router.post("/{org_id}/roles", status_code=201, operation_id="org_create_role")
    async def create_role(
        org_id: str,
        body: RoleCreateRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        pool, identity, _ = await authorized(authorization, org_id, "admin.grants")
        actions = set(body.actions)
        for action in actions:
            validate_action(action)
        if not actions.issubset(set(identity.allowed_actions)):
            raise HTTPException(status_code=403, detail={"code": "role_delegation_exceeds_actor"})
        async with pool.acquire() as connection, connection.transaction():
            role_id = await connection.fetchval(
                f"""
                INSERT INTO {fq("roles")} (org_id, name, description, is_builtin)
                VALUES ($1, $2, $3, FALSE) RETURNING id
                """,
                uuid.UUID(org_id),
                body.name,
                body.description,
            )
            if actions:
                await connection.executemany(
                    f"INSERT INTO {fq('role_actions')} (role_id, action) VALUES ($1, $2)",
                    [(role_id, action) for action in sorted(actions)],
                )
            await write_audit(
                connection,
                identity,
                "admin.roles.create",
                org_id=org_id,
                target_type="role",
                target_id=str(role_id),
            )
        return {"id": str(role_id)}

    @router.patch("/{org_id}/roles/{role_id}", operation_id="org_update_role")
    async def update_role(
        org_id: str,
        role_id: str,
        body: RoleUpdateRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, bool]:
        pool, identity, _ = await authorized(authorization, org_id, "admin.grants")
        actions = set(body.actions)
        for action in actions:
            validate_action(action)
        if not actions.issubset(set(identity.allowed_actions)):
            raise HTTPException(status_code=403, detail={"code": "role_delegation_exceeds_actor"})
        async with pool.acquire() as connection, connection.transaction():
            role = await connection.fetchrow(
                f"SELECT is_builtin FROM {fq('roles')} WHERE id = $1 AND org_id = $2 FOR UPDATE",
                uuid.UUID(role_id),
                uuid.UUID(org_id),
            )
            if not role:
                raise HTTPException(status_code=404, detail={"code": "role_not_found"})
            if role["is_builtin"]:
                raise HTTPException(status_code=409, detail={"code": "builtin_role_immutable"})
            await connection.execute(
                f"UPDATE {fq('roles')} SET description = $2, updated_at = NOW() WHERE id = $1",
                uuid.UUID(role_id),
                body.description,
            )
            await connection.execute(
                f"DELETE FROM {fq('role_actions')} WHERE role_id = $1",
                uuid.UUID(role_id),
            )
            if actions:
                await connection.executemany(
                    f"INSERT INTO {fq('role_actions')} (role_id, action) VALUES ($1, $2)",
                    [(uuid.UUID(role_id), action) for action in sorted(actions)],
                )
            await write_audit(
                connection,
                identity,
                "admin.roles.update",
                org_id=org_id,
                target_type="role",
                target_id=role_id,
                metadata={"actions": sorted(actions)},
            )
        return {"ok": True}

    @router.delete("/{org_id}/roles/{role_id}", operation_id="org_delete_role")
    async def delete_role(
        org_id: str,
        role_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, bool]:
        pool, identity, _ = await authorized(authorization, org_id, "admin.grants")
        role = await pool.fetchrow(
            f"""
            SELECT r.is_builtin, COUNT(m.id) AS membership_count
            FROM {fq("roles")} r
            LEFT JOIN {fq("org_memberships")} m ON m.role_id = r.id
            WHERE r.id = $1 AND r.org_id = $2
            GROUP BY r.id
            """,
            uuid.UUID(role_id),
            uuid.UUID(org_id),
        )
        if not role:
            raise HTTPException(status_code=404, detail={"code": "role_not_found"})
        if role["is_builtin"]:
            raise HTTPException(status_code=409, detail={"code": "builtin_role_immutable"})
        if int(role["membership_count"]):
            raise HTTPException(status_code=409, detail={"code": "role_in_use"})
        await pool.execute(f"DELETE FROM {fq('roles')} WHERE id = $1", uuid.UUID(role_id))
        await write_audit(
            pool,
            identity,
            "admin.roles.delete",
            org_id=org_id,
            target_type="role",
            target_id=role_id,
        )
        return {"ok": True}

    @router.get("/{org_id}/service-accounts", operation_id="org_list_service_accounts")
    async def list_service_accounts(
        org_id: str,
        authorization: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        pool, _, _ = await authorized(authorization, org_id, "admin.keys")
        rows = await pool.fetch(
            f"""
            SELECT p.id::text, p.display_name, p.status, m.id::text AS membership_id,
                   r.id::text AS role_id, r.name AS role,
                   COUNT(DISTINCT k.id) FILTER (
                       WHERE k.revoked_at IS NULL AND (k.expires_at IS NULL OR k.expires_at > NOW())
                   ) AS active_keys,
                   COALESCE(
                       array_agg(DISTINCT ms.scope_id) FILTER (WHERE ms.scope_type = 'bank'),
                       ARRAY[]::text[]
                   ) AS bank_ids,
                   COALESCE(bool_or(ms.scope_type = 'org' AND ms.scope_id = '*'), FALSE) AS org_wide
            FROM {fq("principals")} p
            JOIN {fq("org_memberships")} m ON m.principal_id = p.id
            JOIN {fq("roles")} r ON r.id = m.role_id
            LEFT JOIN {fq("api_keys")} k ON k.principal_id = p.id
            LEFT JOIN {fq("membership_scopes")} ms ON ms.membership_id = m.id
            WHERE m.org_id = $1 AND p.principal_type = 'service'
            GROUP BY p.id, m.id, r.id ORDER BY p.display_name
            """,
            uuid.UUID(org_id),
        )
        return [dict(row) for row in rows]

    @router.post("/{org_id}/service-accounts", status_code=201, operation_id="org_create_service_account")
    async def create_service_account(
        org_id: str,
        body: ServiceAccountCreateRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        pool, identity, org = await authorized(authorization, org_id, "admin.keys")
        role_name, actions = await _validated_role(pool, body.role_id, org_id)
        if not actions.issubset(set(identity.allowed_actions)):
            raise HTTPException(status_code=403, detail={"code": "role_delegation_exceeds_actor"})
        if role_name in {"owner", "admin", "operator", "viewer"}:
            raise HTTPException(status_code=400, detail={"code": "service_role_or_custom_role_required"})
        bank_ids = await _validate_bank_ids(pool, org["schema_name"], body.bank_ids)
        principal_id = str(uuid.uuid4())
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute(
                f"""
                INSERT INTO {fq("principals")} (id, display_name, principal_type, status)
                VALUES ($1, $2, 'service', 'active')
                """,
                uuid.UUID(principal_id),
                body.name,
            )
            membership_id = await connection.fetchval(
                f"""
                INSERT INTO {fq("org_memberships")} (org_id, principal_id, role_id, status)
                VALUES ($1, $2, $3, 'active') RETURNING id
                """,
                uuid.UUID(org_id),
                uuid.UUID(principal_id),
                uuid.UUID(body.role_id),
            )
            await _replace_membership_scopes(connection, membership_id, role_name, bank_ids)
            await write_audit(
                connection,
                identity,
                "admin.service_accounts.create",
                org_id=org_id,
                target_type="principal",
                target_id=principal_id,
            )
        return {"id": principal_id}

    @router.patch("/{org_id}/service-accounts/{principal_id}", operation_id="org_update_service_account")
    async def update_service_account(
        org_id: str,
        principal_id: str,
        body: ServiceAccountUpdateRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, bool]:
        pool, identity, org = await authorized(authorization, org_id, "admin.keys")
        if body.status and body.status not in {"active", "disabled"}:
            raise HTTPException(status_code=400, detail={"code": "invalid_principal_status"})
        bank_ids = await _validate_bank_ids(pool, org["schema_name"], body.bank_ids or [])
        async with pool.acquire() as connection, connection.transaction():
            target = await connection.fetchrow(
                f"""
                SELECT p.id, p.status, m.id AS membership_id, m.role_id::text,
                       r.name AS role,
                       COALESCE(array_agg(ms.scope_id) FILTER (WHERE ms.scope_type = 'bank'), ARRAY[]::text[]) AS bank_ids
                FROM {fq("principals")} p
                JOIN {fq("org_memberships")} m ON m.principal_id = p.id
                JOIN {fq("roles")} r ON r.id = m.role_id
                LEFT JOIN {fq("membership_scopes")} ms ON ms.membership_id = m.id
                WHERE p.id = $1 AND p.principal_type = 'service' AND m.org_id = $2
                GROUP BY p.id, m.id, r.id
                """,
                uuid.UUID(principal_id),
                uuid.UUID(org_id),
            )
            if not target:
                raise HTTPException(status_code=404, detail={"code": "service_account_not_found"})
            role_name = target["role"]
            role_id = body.role_id or target["role_id"]
            if body.role_id:
                role_name, actions = await _validated_role(connection, body.role_id, org_id)
                if role_name in {"owner", "admin", "operator", "viewer"}:
                    raise HTTPException(status_code=400, detail={"code": "service_role_or_custom_role_required"})
                if not actions.issubset(set(identity.allowed_actions)):
                    raise HTTPException(status_code=403, detail={"code": "role_delegation_exceeds_actor"})
            next_banks = bank_ids if body.bank_ids is not None else list(target["bank_ids"])
            await connection.execute(
                f"UPDATE {fq('principals')} SET display_name = COALESCE($2, display_name), status = COALESCE($3, status), updated_at = NOW() WHERE id = $1",
                uuid.UUID(principal_id),
                body.name,
                body.status,
            )
            await connection.execute(
                f"UPDATE {fq('org_memberships')} SET role_id = $2, status = COALESCE($3, status), updated_at = NOW() WHERE id = $1",
                target["membership_id"],
                uuid.UUID(role_id),
                body.status,
            )
            if body.bank_ids is not None or body.role_id is not None:
                await _replace_membership_scopes(connection, target["membership_id"], role_name, next_banks)
            if body.status == "disabled":
                await connection.execute(
                    f"UPDATE {fq('api_keys')} SET revoked_at = NOW() WHERE principal_id = $1 AND revoked_at IS NULL",
                    uuid.UUID(principal_id),
                )
            await write_audit(
                connection,
                identity,
                "admin.service_accounts.update",
                org_id=org_id,
                target_type="principal",
                target_id=principal_id,
                metadata=body.model_dump(exclude_none=True),
            )
        return {"ok": True}

    async def _create_key(
        pool: Any,
        identity: ResolvedIdentity,
        org: Any,
        principal_id: str,
        body: KeyCreateRequest,
        *,
        rotated_from_id: str | None = None,
    ) -> KeySecretResponse:
        service = await pool.fetchrow(
            f"""
            SELECT p.id FROM {fq("principals")} p JOIN {fq("org_memberships")} m ON m.principal_id = p.id
            WHERE p.id = $1 AND p.principal_type = 'service' AND m.org_id = $2 AND m.status = 'active'
            """,
            uuid.UUID(principal_id),
            uuid.UUID(org["id"]),
        )
        if not service:
            raise HTTPException(status_code=404, detail={"code": "service_account_not_found"})
        raw = generate_api_key()
        expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_days)
        key_id = str(uuid.uuid4())
        await pool.execute(
            f"""
            INSERT INTO {fq("api_keys")}
                (id, key_hash, name, created_at, expires_at,
                 principal_id, key_prefix, hash_version, created_by, description, rotated_from_id)
            VALUES ($1, $2, $3, NOW(), $4, $5, $6, 2, $7, $8, $9)
            """,
            uuid.UUID(key_id),
            hash_secret(raw),
            body.name,
            expires_at,
            uuid.UUID(principal_id),
            key_prefix(raw),
            uuid.UUID(identity.principal_id),
            body.description,
            uuid.UUID(rotated_from_id) if rotated_from_id else None,
        )
        await write_audit(
            pool, identity, "admin.keys.create", org_id=org["id"], target_type="api_key", target_id=key_id
        )
        return KeySecretResponse(
            id=key_id,
            name=body.name,
            key_prefix=key_prefix(raw),
            raw_key=raw,
            expires_at=expires_at.isoformat(),
        )

    @router.get("/{org_id}/service-accounts/{principal_id}/keys", operation_id="org_list_service_keys")
    async def list_service_keys(
        org_id: str,
        principal_id: str,
        authorization: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        pool, _, _ = await authorized(authorization, org_id, "admin.keys")
        exists = await pool.fetchval(
            f"""
            SELECT 1 FROM {fq("principals")} p
            JOIN {fq("org_memberships")} m ON m.principal_id = p.id
            WHERE p.id = $1 AND p.principal_type = 'service' AND m.org_id = $2
            """,
            uuid.UUID(principal_id),
            uuid.UUID(org_id),
        )
        if not exists:
            raise HTTPException(status_code=404, detail={"code": "service_account_not_found"})
        rows = await pool.fetch(
            f"""
            SELECT id::text, name, key_prefix, created_at::text, expires_at::text,
                   revoked_at::text, last_used_at::text, description
            FROM {fq("api_keys")} WHERE principal_id = $1 ORDER BY created_at DESC
            """,
            uuid.UUID(principal_id),
        )
        return [dict(row) for row in rows]

    @router.post(
        "/{org_id}/service-accounts/{principal_id}/keys",
        response_model=KeySecretResponse,
        status_code=201,
        operation_id="org_create_service_key",
    )
    async def create_service_key(
        org_id: str,
        principal_id: str,
        body: KeyCreateRequest,
        authorization: str | None = Header(default=None),
    ) -> KeySecretResponse:
        pool, identity, org = await authorized(authorization, org_id, "admin.keys")
        return await _create_key(pool, identity, org, principal_id, body)

    @router.post(
        "/{org_id}/service-accounts/{principal_id}/keys/{key_id}/rotate",
        response_model=KeySecretResponse,
        status_code=201,
        operation_id="org_rotate_service_key",
    )
    async def rotate_service_key(
        org_id: str,
        principal_id: str,
        key_id: str,
        body: KeyCreateRequest,
        overlap_hours: int = Query(default=24, ge=0, le=168),
        authorization: str | None = Header(default=None),
    ) -> KeySecretResponse:
        pool, identity, org = await authorized(authorization, org_id, "admin.keys")
        async with pool.acquire() as connection, connection.transaction():
            old = await connection.fetchrow(
                f"""
                SELECT k.id FROM {fq("api_keys")} k
                JOIN {fq("org_memberships")} m ON m.principal_id = k.principal_id
                WHERE k.id = $1 AND k.principal_id = $2 AND m.org_id = $3
                  AND k.revoked_at IS NULL
                FOR UPDATE OF k
                """,
                uuid.UUID(key_id),
                uuid.UUID(principal_id),
                uuid.UUID(org_id),
            )
            if not old:
                raise HTTPException(status_code=404, detail={"code": "api_key_not_found"})
            replacement = await _create_key(
                connection,
                identity,
                org,
                principal_id,
                body,
                rotated_from_id=key_id,
            )
            if overlap_hours == 0:
                await connection.execute(
                    f"UPDATE {fq('api_keys')} SET revoked_at = NOW() WHERE id = $1",
                    uuid.UUID(key_id),
                )
            else:
                await connection.execute(
                    f"""
                    UPDATE {fq("api_keys")}
                    SET expires_at = CASE
                        WHEN expires_at IS NULL THEN NOW() + ($2 * INTERVAL '1 hour')
                        ELSE LEAST(expires_at, NOW() + ($2 * INTERVAL '1 hour'))
                    END
                    WHERE id = $1
                    """,
                    uuid.UUID(key_id),
                    overlap_hours,
                )
            await write_audit(
                connection,
                identity,
                "admin.keys.rotate",
                org_id=org_id,
                target_type="api_key",
                target_id=key_id,
                metadata={"replacement_id": replacement.id, "overlap_hours": overlap_hours},
            )
        return replacement

    @router.delete("/{org_id}/service-accounts/{principal_id}/keys/{key_id}", operation_id="org_revoke_service_key")
    async def revoke_service_key(
        org_id: str,
        principal_id: str,
        key_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, bool]:
        pool, identity, _ = await authorized(authorization, org_id, "admin.keys")
        result = await pool.execute(
            f"""
            UPDATE {fq("api_keys")} k SET revoked_at = NOW()
            FROM {fq("org_memberships")} m
            WHERE k.id = $1 AND k.principal_id = $2 AND k.revoked_at IS NULL
              AND m.principal_id = k.principal_id AND m.org_id = $3
            """,
            uuid.UUID(key_id),
            uuid.UUID(principal_id),
            uuid.UUID(org_id),
        )
        await write_audit(pool, identity, "admin.keys.revoke", org_id=org_id, target_type="api_key", target_id=key_id)
        return {"ok": result.endswith("1")}

    @router.get("/{org_id}/access", operation_id="org_access_matrix")
    async def access_matrix(
        org_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        pool, _, org = await authorized(authorization, org_id, "admin.grants")
        members = await list_members(org_id, authorization)
        services = await list_service_accounts(org_id, authorization)
        roles = await list_roles(org_id, authorization)
        banks = await pool.fetch(
            f"SELECT bank_id, name FROM {quote_ident(org['schema_name'])}.banks ORDER BY name, bank_id"
        )
        grants = await pool.fetch(
            f"""
            SELECT id::text, subject_id, action, scope_type, scope_id
            FROM {fq("access_grants")} WHERE org_id = $1 ORDER BY subject_id, action, scope_type, scope_id
            """,
            uuid.UUID(org_id),
        )
        principals = [item["principal_id"] for item in members] + [item["id"] for item in services]
        effective = {
            principal_id: await _effective_permissions(pool, org_id, principal_id) for principal_id in principals
        }
        return {
            "actions": sorted(action for action in ALL_ACTIONS if action != "system.admin"),
            "banks": [dict(row) for row in banks],
            "members": members,
            "services": services,
            "roles": roles,
            "grants": [dict(row) for row in grants],
            "effective": effective,
        }

    @router.get(
        "/{org_id}/effective-permissions/{principal_id}",
        operation_id="org_get_effective_permissions",
    )
    async def effective_permissions(
        org_id: str,
        principal_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        pool, _, _ = await authorized(authorization, org_id, "admin.grants")
        return await _effective_permissions(pool, org_id, principal_id)

    @router.post("/{org_id}/grants", status_code=201, operation_id="org_create_direct_grant")
    async def create_direct_grant(
        org_id: str,
        body: DirectGrantRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        pool, identity, _ = await authorized(authorization, org_id, "admin.grants")
        validate_action(body.action)
        if body.action not in identity.allowed_actions:
            raise HTTPException(status_code=403, detail={"code": "grant_delegation_exceeds_actor"})
        if body.scope_type not in {"org", "bank"}:
            raise HTTPException(status_code=400, detail={"code": "invalid_scope"})
        if body.scope_type == "org" and body.scope_id != "*":
            raise HTTPException(status_code=400, detail={"code": "invalid_org_scope"})
        if body.scope_type == "bank":
            org = await _org(pool, org_id)
            await _validate_bank_ids(pool, org["schema_name"], [body.scope_id])
        actor_scopes = set(identity.action_scopes.get(body.action, []))
        requested_scope = f"{body.scope_type}:{body.scope_id}"
        if "org:*" not in actor_scopes and requested_scope not in actor_scopes:
            raise HTTPException(status_code=403, detail={"code": "scope_delegation_exceeds_actor"})
        target_exists = await pool.fetchval(
            f"SELECT 1 FROM {fq('org_memberships')} WHERE org_id = $1 AND principal_id = $2 AND status = 'active'",
            uuid.UUID(org_id),
            uuid.UUID(body.principal_id),
        )
        if not target_exists:
            raise HTTPException(status_code=404, detail={"code": "principal_not_in_organization"})
        grant_id = await pool.fetchval(
            f"""
            INSERT INTO {fq("access_grants")}
                (org_id, subject_type, subject_id, action, scope_type, scope_id)
            VALUES ($1, 'principal', $2, $3, $4, $5)
            ON CONFLICT (org_id, subject_type, subject_id, action, scope_type, scope_id)
            DO UPDATE SET action = EXCLUDED.action RETURNING id
            """,
            uuid.UUID(org_id),
            body.principal_id,
            body.action,
            body.scope_type,
            body.scope_id,
        )
        await write_audit(pool, identity, "admin.grants.create", org_id=org_id, target_id=str(grant_id))
        return {"id": str(grant_id)}

    @router.delete("/{org_id}/grants/{grant_id}", operation_id="org_delete_direct_grant")
    async def delete_direct_grant(
        org_id: str,
        grant_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, bool]:
        pool, identity, _ = await authorized(authorization, org_id, "admin.grants")
        grant = await pool.fetchrow(
            f"SELECT action, scope_type, scope_id FROM {fq('access_grants')} WHERE id = $1 AND org_id = $2",
            uuid.UUID(grant_id),
            uuid.UUID(org_id),
        )
        if not grant:
            raise HTTPException(status_code=404, detail={"code": "grant_not_found"})
        actor_scopes = set(identity.action_scopes.get(grant["action"], []))
        grant_scope = f"{grant['scope_type']}:{grant['scope_id']}"
        if grant["action"] not in identity.allowed_actions or (
            "org:*" not in actor_scopes and grant_scope not in actor_scopes
        ):
            raise HTTPException(status_code=403, detail={"code": "grant_delegation_exceeds_actor"})
        result = await pool.execute(
            f"DELETE FROM {fq('access_grants')} WHERE id = $1 AND org_id = $2",
            uuid.UUID(grant_id),
            uuid.UUID(org_id),
        )
        await write_audit(pool, identity, "admin.grants.delete", org_id=org_id, target_id=grant_id)
        return {"ok": result.endswith("1")}

    @router.get("/{org_id}/audit-events", operation_id="org_list_audit_events")
    async def audit_events(
        org_id: str,
        actor_id: str | None = Query(default=None),
        action: str | None = Query(default=None),
        result: str | None = Query(default=None),
        target: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        authorization: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        pool, _, _ = await authorized(authorization, org_id, "admin.audit")
        clauses = ["a.org_id = $1"]
        params: list[Any] = [uuid.UUID(org_id)]
        for column, value, transform in (
            ("a.actor_principal_id", actor_id, uuid.UUID),
            ("a.action", action, str),
            ("a.result", result, str),
            ("a.target_id", target, str),
        ):
            if value:
                params.append(transform(value))
                clauses.append(f"{column} = ${len(params)}")
        params.append(limit)
        rows = await pool.fetch(
            f"""
            SELECT a.id::text, a.actor_principal_id::text, p.display_name AS actor_name,
                   a.action, a.target_type, a.target_id, a.result, a.metadata, a.created_at::text
            FROM {fq("audit_events")} a
            LEFT JOIN {fq("principals")} p ON p.id = a.actor_principal_id
            WHERE {" AND ".join(clauses)} ORDER BY a.created_at DESC LIMIT ${len(params)}
            """,
            *params,
        )
        return [{**dict(row), "metadata": decode_jsonb(row["metadata"], {})} for row in rows]

    return router
