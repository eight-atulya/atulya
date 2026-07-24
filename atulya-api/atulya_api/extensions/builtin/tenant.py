"""
Built-in ``TenantExtension`` implementations for single-tenant deployments.

Purpose
-------
Provides default auth strategies shipped with Atulya: no-auth single schema
(``DefaultTenantExtension``), shared API-key gate (``ApiKeyTenantExtension``),
and superuser key layering (``SuperuserTenantExtension``).

Trigger path
------------
Selected via ``ATULYA_API_TENANT_EXTENSION`` (see each class docstring).
``DefaultTenantExtension`` is the implicit fallback when no extension is
configured. ``SuperuserTenantExtension`` wraps a delegate (usually
``ApiKeyTenantExtension``) for admin bypass keys.

Inputs
------
- ``ATULYA_API_DATABASE_SCHEMA``, ``ATULYA_API_TENANT_API_KEY``,
  ``ATULYA_API_SUPERUSER_KEY``, ``ATULYA_API_TENANT_MCP_AUTH_DISABLED``.
- ``RequestContext.api_key`` per request.

Outputs
------
``TenantContext`` with schema and optional ``role="superuser"``.

Side effects
------------
None beyond auth decisions. ``mcp_auth_disabled`` allows unauthenticated MCP
when explicitly enabled (back-compat only).

Mutability
----------
Extensions cache schema at ``__init__``; env changes require process restart.

Impact radius
-------------
Wrong extension class or leaked API keys expose entire schema. Superuser key
comparison uses ``hmac.compare_digest`` — preserve timing-safe checks.

Failure modes
-------------
``ValueError`` at startup if required keys missing. ``AuthenticationError`` on
bad API key at request time.

Maintenance notes
-----------------
Good: implement custom ``TenantExtension`` for per-key schema routing.

Bad: disable MCP auth in production without network-level protection.

Bad: add insecure superuser key fallbacks — startup must fail closed.
"""

from atulya_api.auth import fq
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
# Production-grade database identity resolver for sessions and service keys.
#
# Auth flow:
#   1. Resolve the opaque session or hashed service key.
#   2. Resolve its active organization membership and role.
#   3. Build one TenantContext from role actions and ABAC scopes.
#
# Credentials are resolved against the database on every request so session and
# key revocation is immediate across every API replica.
#
# Configuration:
#   ATULYA_API_TENANT_EXTENSION=atulya_api.extensions.builtin.tenant:DbApiKeyTenantExtension
#   (No additional env vars needed — uses the DB pool from the configured database_url)
# ---------------------------------------------------------------------------


class DbApiKeyTenantExtension(TenantExtension):
    """
    DB-backed tenant extension using the api_keys table.

    Resolves sessions and service keys through the same membership, role-action,
    and scope tables.

    Requires migration 080109b0cbdc (api_keys table) to be applied.
    """

    def __init__(self, config: dict[str, str]):
        super().__init__(config)
        # DB pool injected via on_startup or provided in config["_pool"] for testing.
        self._pool: "asyncpg.Pool | None" = config.get("_pool")  # type: ignore[assignment]
        self._schema: str = config.get("schema", get_config().database_schema)

    async def _get_db_pool(self) -> "asyncpg.Pool":
        if self._pool is not None:
            return self._pool
        raise RuntimeError(
            "DbApiKeyTenantExtension: DB pool not available. "
            "Ensure the MemoryEngine is initialized before the first request."
        )

    async def authenticate(self, context: RequestContext) -> TenantContext:
        from atulya_api.auth_service import resolve_identity

        if not context.api_key:
            raise AuthenticationError("API key is required")

        pool = await self._get_db_pool()
        identity = await resolve_identity(pool, context.api_key)
        if identity is None:
            raise AuthenticationError("Invalid or expired credential")
        if identity.active_org_id is None:
            raise AuthenticationError("Select an organization before accessing memory banks")
        tenant_ctx = TenantContext(
            schema_name=identity.schema_name,
            role=identity.role,  # type: ignore[arg-type]
            org_id=identity.active_org_id,
            membership_id=identity.membership_id,
            principal_id=identity.principal_id,
            principal_type=identity.principal_type,
            display_name=identity.display_name,
            email=identity.email,
            allowed_actions=identity.allowed_actions,
            action_scopes=identity.action_scopes,
        )
        context.api_key_id = identity.api_key_id
        context.tenant_id = identity.active_org_id

        return tenant_ctx

    async def list_tenants(self) -> list[Tenant]:
        """Return the auth schema and every active organization schema."""
        try:
            pool = await self._get_db_pool()
            rows = await pool.fetch(
                f"SELECT schema_name FROM {fq('orgs', self._schema)} WHERE status = 'active' ORDER BY schema_name"
            )
            schemas = [self._schema, *(row["schema_name"] for row in rows)]
            return [Tenant(schema=schema) for schema in dict.fromkeys(schemas)]
        except Exception:
            return [Tenant(schema=self._schema)]

    async def on_startup(self) -> None:
        """Prime DB pool reference at startup rather than waiting for first request."""
        try:
            await self._get_db_pool()
        except RuntimeError:
            pass  # Pool not ready yet — will retry on first request
