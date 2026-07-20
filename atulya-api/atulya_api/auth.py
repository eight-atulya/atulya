"""Canonical auth helpers for Atulya RBAC/ABAC."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

AUTH_SCHEMA_ENV = "ATULYA_API_AUTH_SCHEMA"
KEY_PEPPER_ENV = "ATULYA_API_KEY_HASH_PEPPER"
SESSION_TTL_HOURS_ENV = "ATULYA_API_SESSION_TTL_HOURS"

SESSION_PREFIX = "atulya_sess_"
API_KEY_PREFIX = "atulya_"

ALL_ACTIONS: frozenset[str] = frozenset(
    {
        "bank.read",
        "bank.write",
        "bank.delete",
        "bank.config",
        "memory.retain",
        "memory.recall",
        "memory.delete",
        "reflect.run",
        "forge.read",
        "forge.run",
        "forge.export",
        "brain.read",
        "brain.write",
        "webhook.manage",
        "admin.users",
        "admin.keys",
        "admin.grants",
        "admin.audit",
        "system.admin",
    }
)

ORG_ACTIONS = frozenset(action for action in ALL_ACTIONS if action != "system.admin")

ROLE_ACTIONS: dict[str, frozenset[str]] = {
    "owner": ORG_ACTIONS,
    "admin": ORG_ACTIONS,
    "operator": frozenset(
        {
            "bank.read",
            "bank.write",
            "bank.config",
            "memory.retain",
            "memory.recall",
            "memory.delete",
            "reflect.run",
            "forge.read",
            "forge.run",
            "forge.export",
            "brain.read",
            "brain.write",
            "webhook.manage",
        }
    ),
    "viewer": frozenset({"bank.read", "memory.recall", "reflect.run", "forge.read", "brain.read"}),
    "service": frozenset(),
    "superuser": ALL_ACTIONS,
    # Backwards-compatible role names used by the current api_keys table.
    "user": frozenset({"bank.read", "memory.recall", "reflect.run", "forge.read", "brain.read"}),
}

ROLE_ORDER: list[str] = ["superuser", "owner", "admin", "operator", "viewer", "service", "user"]

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

_password_hasher = PasswordHasher()


@dataclass(frozen=True)
class LoginSession:
    raw_token: str
    token_hash: str
    expires_at: datetime


def auth_schema() -> str:
    return os.getenv(AUTH_SCHEMA_ENV, "public")


def quote_ident(identifier: str) -> str:
    if not _IDENTIFIER_RE.match(identifier):
        raise ValueError(f"Invalid SQL identifier: {identifier!r}")
    return f'"{identifier}"'


def fq(table: str, schema: str | None = None) -> str:
    return f"{quote_ident(schema or auth_schema())}.{quote_ident(table)}"


def normalize_org_slug(value: str) -> str:
    slug = value.strip().lower().replace(" ", "-")
    if not _SLUG_RE.match(slug):
        raise ValueError("Org slug must be lowercase letters, numbers, dashes, or underscores")
    return slug


def schema_for_org(slug: str) -> str:
    normalized = normalize_org_slug(slug).replace("-", "_")
    return f"org_{normalized}"


def hash_secret(raw: str, *, version: int = 2) -> str:
    """Hash API keys and session tokens.

    Version 1 is the legacy plain SHA-256 hash. Version 2 uses an env pepper.
    """

    if version <= 1:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
    pepper = os.getenv(KEY_PEPPER_ENV, "")
    if not pepper:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return hmac.new(pepper.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_secret(raw: str, stored_hash: str, *, version: int | None = None) -> bool:
    versions = [version] if version else [2, 1]
    for candidate_version in versions:
        if hmac.compare_digest(hash_secret(raw, version=candidate_version), stored_hash):
            return True
    return False


def generate_api_key() -> str:
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def generate_session() -> LoginSession:
    raw = f"{SESSION_PREFIX}{secrets.token_urlsafe(32)}"
    ttl_hours = int(os.getenv(SESSION_TTL_HOURS_ENV, "12"))
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    return LoginSession(raw_token=raw, token_hash=hash_secret(raw), expires_at=expires_at)


def key_prefix(raw: str) -> str:
    return raw[:18]


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def normalize_action_scopes(rows: list[Any]) -> dict[str, list[str]]:
    scopes: dict[str, set[str]] = {}
    for row in rows:
        action = row["action"] if not isinstance(row, dict) else row["action"]
        scope_type = row["scope_type"] if not isinstance(row, dict) else row["scope_type"]
        scope_id = row["scope_id"] if not isinstance(row, dict) else row["scope_id"]
        scopes.setdefault(action, set()).add(f"{scope_type}:{scope_id}")
    return {action: sorted(values) for action, values in scopes.items()}


def role_actions(role: str) -> frozenset[str]:
    return ROLE_ACTIONS.get(role, frozenset())


def action_allowed(ctx: Any, action: str) -> bool:
    if getattr(ctx, "is_superuser", False) or getattr(ctx, "role", "") == "superuser":
        return True
    explicit = set(getattr(ctx, "allowed_actions", None) or [])
    if action in explicit:
        return True
    return action in role_actions(getattr(ctx, "role", "user"))


def scope_allowed(ctx: Any, action: str, bank_id: str | None = None) -> bool:
    if getattr(ctx, "is_superuser", False) or getattr(ctx, "role", "") == "superuser":
        return True

    action_scopes = getattr(ctx, "action_scopes", None) or {}
    scopes = set(action_scopes.get(action, [])) | set(action_scopes.get("*", []))
    if "org:*" in scopes:
        return True
    if bank_id and f"bank:{bank_id}" in scopes:
        return True

    # Human/session principals get role-derived org scope only for org admins.
    if getattr(ctx, "principal_id", None):
        if getattr(ctx, "role", "") in {"owner", "admin"}:
            return True
        return False

    # Compatibility with the existing api_keys.allowed_bank_ids contract.
    allowed_bank_ids = getattr(ctx, "allowed_bank_ids", None)
    if allowed_bank_ids is None:
        return True
    return bool(bank_id and bank_id in allowed_bank_ids)


def can_perform(ctx: Any, action: str, bank_id: str | None = None) -> bool:
    return action_allowed(ctx, action) and scope_allowed(ctx, action, bank_id)
