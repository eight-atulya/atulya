"""Built-in tenant extension implementations."""

from atulya_api.auth import fq, hash_secret, normalize_action_scopes
from atulya_api.config import get_config
from atulya_api.extensions.tenant import AuthenticationError, Tenant, TenantContext, TenantExtension
from atulya_api.models import RequestContext


class DefaultTenantExtension(TenantExtension):
    """
    Default single-tenant extension with no authentication.

    This is the default extension used when no tenant extension is configured.
    It provides single-tenant behavior using the configured schema from
    ATULYA_API_DATABASE_SCHEMA (defaults to 'public').

    Features:
    - No authentication required (passes all requests)
    - Uses configured schema from environment
    - Perfect for single-tenant deployments without auth

    Configuration:
        ATULYA_API_DATABASE_SCHEMA=your-schema (optional, defaults to 'public')

    This is automatically enabled by default. To use custom authentication,
    configure a different tenant extension:
        ATULYA_API_TENANT_EXTENSION=atulya_api.extensions.builtin.tenant:ApiKeyTenantExtension
    """

    def __init__(self, config: dict[str, str]):
        super().__init__(config)
        # Cache the schema at initialization for consistency
        # Support explicit schema override via config, otherwise use environment
        self._schema = config.get("schema", get_config().database_schema)

    async def authenticate(self, context: RequestContext) -> TenantContext:
        """Return configured schema without any authentication."""
        return TenantContext(schema_name=self._schema)

    async def list_tenants(self) -> list[Tenant]:
        """Return configured schema for single-tenant setup."""
        return [Tenant(schema=self._schema)]


class ApiKeyTenantExtension(TenantExtension):
    """
    Built-in tenant extension that validates API key against an environment variable.

    This is a simple implementation that:
    1. Validates the API key matches ATULYA_API_TENANT_API_KEY
    2. Returns the configured schema (ATULYA_API_DATABASE_SCHEMA, default 'public')
       for all authenticated requests

    Configuration:
        ATULYA_API_TENANT_EXTENSION=atulya_api.extensions.builtin.tenant:ApiKeyTenantExtension
        ATULYA_API_TENANT_API_KEY=your-secret-key
        ATULYA_API_DATABASE_SCHEMA=your-schema (optional, defaults to 'public')
        ATULYA_API_TENANT_MCP_AUTH_DISABLED=true (optional, disable auth for MCP endpoints)

    For multi-tenant setups with separate schemas per tenant, implement a custom
    TenantExtension that looks up the schema based on the API key or token claims.
    """

    def __init__(self, config: dict[str, str]):
        super().__init__(config)
        self.expected_api_key = config.get("api_key")
        if not self.expected_api_key:
            raise ValueError("ATULYA_API_TENANT_API_KEY is required when using ApiKeyTenantExtension")
        # Allow disabling MCP auth for backwards compatibility
        self.mcp_auth_disabled = config.get("mcp_auth_disabled", "").lower() in ("true", "1", "yes")

    async def authenticate(self, context: RequestContext) -> TenantContext:
        """Validate API key and return configured schema context."""
        if context.api_key != self.expected_api_key:
            raise AuthenticationError("Invalid API key")
        return TenantContext(schema_name=get_config().database_schema)

    async def list_tenants(self) -> list[Tenant]:
        """Return configured schema for single-tenant setup."""
        return [Tenant(schema=get_config().database_schema)]

    async def authenticate_mcp(self, context: RequestContext) -> TenantContext:
        """
        Authenticate MCP requests.

        If mcp_auth_disabled is set, skip authentication for backwards compatibility.
        Otherwise, delegate to authenticate().
        """
        if self.mcp_auth_disabled:
            return TenantContext(schema_name=get_config().database_schema)
        return await self.authenticate(context)


# ---------------------------------------------------------------------------
# SuperuserTenantExtension
# ---------------------------------------------------------------------------
# Decorator pattern — wraps any TenantExtension to layer superuser detection
# on top without modifying existing extensions.
#
# Auth flow:
#   1. Incoming api_key == superuser_key  →  TenantContext(role="superuser")
#   2. Otherwise                          →  delegate.authenticate(context)
#
# Configuration (ENV vars, resolved via get_config()):
#   ATULYA_API_SUPERUSER_KEY=<secret>     required; no insecure fallback
#   ATULYA_API_SUPERUSER_SCHEMA=public    optional; which schema superuser uses
#
# Usage (in your env / extension config):
#   ATULYA_API_TENANT_EXTENSION=atulya_api.extensions.builtin.tenant:SuperuserTenantExtension
#   ATULYA_API_TENANT_API_KEY=<regular-key>     (passed to ApiKeyTenantExtension delegate)
#   ATULYA_API_SUPERUSER_KEY=<superuser-key>
# ---------------------------------------------------------------------------

import hmac
import uuid


class SuperuserTenantExtension(TenantExtension):
    """
    Decorates any TenantExtension to add superuser key detection.

    Superuser keys bypass the delegate entirely and return a TenantContext
    with role="superuser", which grants is_superuser=True and unrestricted
    bank access across all admin endpoints.

    All other keys are forwarded to the delegate unchanged — zero behaviour
    change for existing regular-auth flows.
    """

    def __init__(self, config: dict[str, str]):
        super().__init__(config)

        cfg = get_config()

        # Superuser key — required when this extension is active.
        # Resolved from config dict first (test injection), then environment.
        self._superuser_key: str | None = config.get("superuser_key") or cfg.superuser_key
        if not self._superuser_key:
            raise ValueError(
                "ATULYA_API_SUPERUSER_KEY is required when using SuperuserTenantExtension. "
                "Set it to a long random secret (min 32 chars recommended)."
            )

        self._superuser_schema: str = config.get("superuser_schema") or cfg.superuser_schema

        # Build the delegate from config.  Default: ApiKeyTenantExtension.
        # Callers can inject a pre-built delegate via config["_delegate"] for testing.
        _injected: TenantExtension | None = config.get("_delegate")  # type: ignore[assignment]
        if _injected is not None:
            self._delegate: TenantExtension = _injected
        else:
            # Delegate extension class resolved from config key "delegate_extension"
            # or falls back to ApiKeyTenantExtension (same requirement: api_key must be set).
            delegate_cls_path: str = config.get(
                "delegate_extension",
                "atulya_api.extensions.builtin.tenant:ApiKeyTenantExtension",
            )
            if ":" in delegate_cls_path:
                module_path, cls_name = delegate_cls_path.rsplit(":", 1)
            else:
                raise ValueError(f"Invalid delegate_extension format: {delegate_cls_path!r}. Use 'module:ClassName'.")
            import importlib

            module = importlib.import_module(module_path)
            delegate_cls = getattr(module, cls_name)
            self._delegate = delegate_cls(config)

    # ------------------------------------------------------------------
    # HMAC-safe comparison — prevents timing-based side-channel attacks
    # even though the key is compared to an env var (not a DB secret).
    # ------------------------------------------------------------------
    def _key_matches(self, incoming: str | None) -> bool:
        if not incoming:
            return False
        return hmac.compare_digest(
            incoming.encode("utf-8"),
            self._superuser_key.encode("utf-8"),  # type: ignore[union-attr]
        )

    async def authenticate(self, context: RequestContext) -> TenantContext:
        """
        Authenticate the request.

        Superuser key → immediate TenantContext(role="superuser", unrestricted).
        All other keys → forwarded to delegate.authenticate().
        """
        if self._key_matches(context.api_key):
            return TenantContext(
                schema_name=getattr(self, "_superuser_schema", get_config().superuser_schema),
                role="superuser",
                allowed_bank_ids=None,  # unrestricted
            )
        return await self._delegate.authenticate(context)

    async def list_tenants(self) -> list[Tenant]:
        """Delegate to the underlying extension for worker tenant discovery."""
        return await self._delegate.list_tenants()

    async def get_tenant_config(self, context: RequestContext) -> dict:
        """Superusers have no tenant-level config overrides by design."""
        if self._key_matches(context.api_key):
            return {}
        return await self._delegate.get_tenant_config(context)

    async def on_startup(self) -> None:
        await self._delegate.on_startup()

    async def on_shutdown(self) -> None:
        await self._delegate.on_shutdown()


# ---------------------------------------------------------------------------
# DbApiKeyTenantExtension
# ---------------------------------------------------------------------------
# Production-grade DB-backed key store.  Replaces the static env-var key with
# keys stored in the api_keys table (created by migration 080109b0cbdc).
#
# Auth flow:
#   1. SHA-256(incoming_key) → lookup in api_keys
#   2. Check revoked_at IS NULL and expires_at > NOW()
#   3. Return TenantContext(role=row.role, schema_name=row.schema_name,
#                          allowed_bank_ids=row.allowed_bank_ids)
#
# Hot-path cache:
#   - asyncio.Lock-protected in-memory dict: key_hash → (TenantContext, expiry_ts)
#   - TTL = 60 s (configurable via config dict "cache_ttl_seconds")
#   - Cache is invalidated automatically after TTL; explicit invalidation on revoke
#     is not needed because revoked keys have revoked_at set in DB — any cached
#     context for a revoked key will expire within TTL.
#   - Cache is per-process; horizontally scaled deployments tolerate up to TTL
#     delay on revocation (acceptable for API key security model).
#
# Configuration:
#   ATULYA_API_TENANT_EXTENSION=atulya_api.extensions.builtin.tenant:DbApiKeyTenantExtension
#   (No additional env vars needed — uses the DB pool from the configured database_url)
# ---------------------------------------------------------------------------


class DbApiKeyTenantExtension(TenantExtension):
    """
    DB-backed tenant extension using the api_keys table.

    Provides full RBAC (role column) + ABAC (allowed_bank_ids column) via
    DB-stored keys.  Includes a 60-second TTL cache to avoid a DB round-trip
    on every request.

    Requires migration 080109b0cbdc (api_keys table) to be applied.
    """

    _CACHE_TTL_DEFAULT = 60  # seconds

    def __init__(self, config: dict[str, str]):
        super().__init__(config)
        self._cache_ttl: int = int(config.get("cache_ttl_seconds", self._CACHE_TTL_DEFAULT))
        # {key_hash: (TenantContext, expires_monotonic)}
        self._cache: dict[str, tuple[TenantContext, float]] = {}
        self._cache_lock: "asyncio.Lock | None" = None  # lazy init (event loop may not exist yet)
        # DB pool injected via on_startup or provided in config["_pool"] for testing.
        self._pool: "asyncpg.Pool | None" = config.get("_pool")  # type: ignore[assignment]
        self._schema: str = config.get("schema", get_config().database_schema)

    def _get_lock(self) -> "asyncio.Lock":
        import asyncio as _asyncio

        if self._cache_lock is None:
            self._cache_lock = _asyncio.Lock()
        return self._cache_lock

    def _hash_key(self, raw_key: str) -> str:
        return hash_secret(raw_key, version=2)

    async def _load_action_scopes(
        self,
        pool: "asyncpg.Pool",
        *,
        org_id: str | None,
        principal_id: str | None,
        role: str,
    ) -> dict[str, list[str]]:
        if not org_id:
            return {}
        rows = await pool.fetch(
            f"""
            SELECT action, scope_type, scope_id
            FROM {fq("access_grants", self._schema)}
            WHERE org_id = $1
              AND (
                (subject_type = 'principal' AND subject_id = $2)
                OR (subject_type = 'role' AND subject_id = $3)
              )
            """,
            org_id,
            principal_id or "",
            role,
        )
        return normalize_action_scopes(list(rows))

    async def _get_db_pool(self) -> "asyncpg.Pool":
        if self._pool is not None:
            return self._pool
        raise RuntimeError(
            "DbApiKeyTenantExtension: DB pool not available. "
            "Ensure the MemoryEngine is initialized before the first request."
        )

    async def authenticate(self, context: RequestContext) -> TenantContext:
        import asyncio as _asyncio
        import time

        if not context.api_key:
            raise AuthenticationError("API key is required")

        key_hash = self._hash_key(context.api_key)

        # Fast path: check cache under lock
        lock = self._get_lock()
        async with lock:
            if key_hash in self._cache:
                tenant_ctx, cache_expires = self._cache[key_hash]
                if time.monotonic() < cache_expires:
                    return tenant_ctx
                # Expired — evict
                del self._cache[key_hash]

        # Slow path: DB lookup. Session tokens and service API keys resolve into
        # the same TenantContext envelope.
        pool = await self._get_db_pool()
        if context.api_key.startswith("atulya_sess_"):
            row = await pool.fetchrow(
                f"""
                SELECT
                    s.id::text AS session_id,
                    s.expires_at,
                    s.revoked_at,
                    p.id::text AS principal_id,
                    p.email,
                    p.display_name,
                    p.principal_type,
                    p.role,
                    p.status AS principal_status,
                    o.id::text AS org_id,
                    o.schema_name,
                    o.status AS org_status
                FROM {fq("principal_sessions", self._schema)} s
                JOIN {fq("principals", self._schema)} p ON p.id = s.principal_id
                JOIN {fq("orgs", self._schema)} o ON o.id = p.org_id
                WHERE s.token_hash = $1
                """,
                key_hash,
            )
            if row is None:
                raise AuthenticationError("Invalid session")
            if row["revoked_at"] is not None:
                raise AuthenticationError("Session has been revoked")
            if row["principal_status"] != "active":
                raise AuthenticationError("Principal is disabled")
            if row["org_status"] != "active":
                raise AuthenticationError("Organization is disabled")
            if row["expires_at"] is not None:
                from datetime import datetime, timezone

                if datetime.now(timezone.utc) > row["expires_at"].replace(tzinfo=timezone.utc):
                    raise AuthenticationError("Session has expired")
            await pool.execute(
                f"UPDATE {fq('principal_sessions', self._schema)} SET last_used_at = NOW() WHERE id = $1",
                uuid.UUID(row["session_id"]),
            )
            action_scopes = await self._load_action_scopes(
                pool,
                org_id=row["org_id"],
                principal_id=row["principal_id"],
                role=row["role"],
            )
            tenant_ctx = TenantContext(
                schema_name=row["schema_name"],
                role=row["role"],
                allowed_bank_ids=None,
                org_id=row["org_id"],
                principal_id=row["principal_id"],
                principal_type=row["principal_type"],
                display_name=row["display_name"],
                email=row["email"],
                action_scopes=action_scopes,
            )
            context.tenant_id = row["org_id"]
        else:
            row = await pool.fetchrow(
                f"""
                SELECT
                    k.id::text AS api_key_id,
                    k.role,
                    k.schema_name,
                    k.allowed_bank_ids,
                    k.expires_at,
                    k.revoked_at,
                    k.principal_id::text AS principal_id,
                    p.email,
                    p.display_name,
                    p.principal_type,
                    p.status AS principal_status,
                    o.id::text AS org_id,
                    o.status AS org_status
                FROM {fq("api_keys", self._schema)} k
                LEFT JOIN {fq("principals", self._schema)} p ON p.id = k.principal_id
                LEFT JOIN {fq("orgs", self._schema)} o ON o.id = p.org_id
                WHERE k.key_hash = $1 OR k.key_hash = $2
                """,
                key_hash,
                hash_secret(context.api_key, version=1),
            )

            if row is None:
                raise AuthenticationError("Invalid API key")

            if row["revoked_at"] is not None:
                raise AuthenticationError("API key has been revoked")

            if row["principal_status"] is not None and row["principal_status"] != "active":
                raise AuthenticationError("Principal is disabled")
            if row["org_status"] is not None and row["org_status"] != "active":
                raise AuthenticationError("Organization is disabled")

            if row["expires_at"] is not None:
                from datetime import datetime, timezone

                if datetime.now(timezone.utc) > row["expires_at"].replace(tzinfo=timezone.utc):
                    raise AuthenticationError("API key has expired")
            await pool.execute(
                f"UPDATE {fq('api_keys', self._schema)} SET last_used_at = NOW() WHERE id = $1",
                uuid.UUID(row["api_key_id"]),
            )
            action_scopes = await self._load_action_scopes(
                pool,
                org_id=row["org_id"],
                principal_id=row["principal_id"],
                role=row["role"],
            )
            tenant_ctx = TenantContext(
                schema_name=row["schema_name"],
                role=row["role"],
                allowed_bank_ids=list(row["allowed_bank_ids"]) if row["allowed_bank_ids"] else None,
                org_id=row["org_id"],
                principal_id=row["principal_id"],
                principal_type=row["principal_type"],
                display_name=row["display_name"],
                email=row["email"],
                action_scopes=action_scopes,
            )
            context.api_key_id = row["api_key_id"]
            context.tenant_id = row["org_id"]

        # Populate cache
        async with lock:
            import time as _time

            self._cache[key_hash] = (tenant_ctx, _time.monotonic() + self._cache_ttl)

        return tenant_ctx

    async def list_tenants(self) -> list[Tenant]:
        """Return active org schemas, falling back to the auth schema before migration."""
        try:
            pool = await self._get_db_pool()
            rows = await pool.fetch(
                f"SELECT schema_name FROM {fq('orgs', self._schema)} WHERE status = 'active' ORDER BY schema_name"
            )
            return [Tenant(schema=r["schema_name"]) for r in rows] or [Tenant(schema=self._schema)]
        except Exception:
            return [Tenant(schema=self._schema)]

    async def on_startup(self) -> None:
        """Prime DB pool reference at startup rather than waiting for first request."""
        try:
            await self._get_db_pool()
        except RuntimeError:
            pass  # Pool not ready yet — will retry on first request
