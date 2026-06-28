"""
Hierarchical configuration resolution: global → tenant → bank.

Purpose:
    Merge environment defaults, tenant extension overrides, and per-bank JSONB
    config so every request sees consistent LLM/retain/recall settings without
    caching stale values across API replicas.

Trigger path:
    - ``MemoryEngine.get_resolved_config`` / operation handlers per request.
    - HTTP bank config GET/PATCH routes via ``ConfigResolver`` methods.
    - Internal engine paths call ``resolve_full_config`` (includes credentials).

Inputs:
    - ``bank_id``, optional ``RequestContext`` for tenant extension.
    - ``banks.config`` JSONB column (bank overrides).
    - ``TenantExtension.get_tenant_config`` / ``get_allowed_config_fields``.

Outputs:
    - ``resolve_full_config``: complete ``AtulyaConfig`` dataclass (internal).
    - ``get_bank_config``: filtered dict safe for API responses (no credentials).
    - ``update_bank_config`` / ``reset_bank_config``: mutates ``banks.config``.

Side effects:
    - PostgreSQL read on every resolve; write on config updates.
    - Logs applied override keys at debug level.

Mutability:
    - ``banks.config`` merged with ``||`` on update; reset clears to ``{}``.
    - Global env config is read once at resolver init (``_global_config`` snapshot).

Impact radius:
    - Every LLM call, embedding dimension, retain mode, and feature flag.
    - Mis-filtering credentials in ``get_bank_config`` is a security regression.

Core logic:
    Layer overrides in order; normalize env-style keys; strip non-configurable and
    credential fields for external API; enforce tenant permission allowlists.

Failure modes:
    - Tenant extension errors: logged, resolution continues without tenant layer.
    - Invalid update fields: ``ValueError`` before DB write.
    - Permission check errors on update: fail-open (backward compatibility).

Maintenance notes:
    Good: add a field to ``_HIERARCHICAL_FIELDS`` in ``config.py`` and document it.
    Bad: cache ``resolve_full_config`` per bank — breaks multi-server consistency.
    Bad: expose credential fields via ``get_bank_config``.
"""

import json
import logging
from dataclasses import asdict
from typing import Any

import asyncpg

from atulya_api.config import AtulyaConfig, _get_raw_config, normalize_config_dict
from atulya_api.engine.memory_engine import fq_table
from atulya_api.extensions.tenant import TenantExtension
from atulya_api.models import RequestContext

logger = logging.getLogger(__name__)


class ConfigResolver:
    """
    Per-request bank configuration merger with security filtering.

    Purpose:
        Single entry point for hierarchical config reads/writes on ``banks.config``.

    Trigger path:
        Owned by ``MemoryEngine``; passed into retain/recall/reflect subsystems.

    Maintenance notes:
        Use ``resolve_full_config`` inside the engine; never return it from HTTP.
        Use ``get_config()`` static proxy only for non-hierarchical fields.
    """

    def __init__(self, pool: asyncpg.Pool, tenant_extension: TenantExtension | None = None):
        """
        Initialize config resolver.

        Args:
            pool: Database connection pool
            tenant_extension: Optional tenant extension for tenant-level config and permissions
        """
        self.pool = pool
        self.tenant_extension = tenant_extension
        self._global_config = _get_raw_config()
        self._configurable_fields = AtulyaConfig.get_configurable_fields()
        self._credential_fields = AtulyaConfig.get_credential_fields()

    async def resolve_full_config(self, bank_id: str, context: RequestContext | None = None) -> AtulyaConfig:
        """
        Resolve full AtulyaConfig for a bank with hierarchical overrides applied.

        This is for INTERNAL USE ONLY. Returns the complete config object with all fields
        including credentials and static fields. Use get_bank_config() for API responses.

        Resolution order:
        1. Global config (from environment variables)
        2. Tenant config overrides (from TenantExtension.get_tenant_config())
        3. Bank config overrides (from banks.config JSONB)

        Args:
            bank_id: Bank identifier
            context: Request context for tenant config resolution

        Returns:
            Complete AtulyaConfig with hierarchical overrides applied
        """
        # Start with global config (all fields)
        config_dict = asdict(self._global_config)

        # Load tenant config overrides (if tenant extension available)
        if self.tenant_extension and context:
            try:
                tenant_overrides = await self.tenant_extension.get_tenant_config(context)
                if tenant_overrides:
                    # Normalize keys and filter to configurable fields only
                    normalized_tenant = normalize_config_dict(tenant_overrides)
                    configurable_tenant = {k: v for k, v in normalized_tenant.items() if k in self._configurable_fields}
                    config_dict.update(configurable_tenant)
                    logger.debug(
                        f"Applied tenant config overrides for bank {bank_id}: {list(configurable_tenant.keys())}"
                    )
            except Exception as e:
                logger.warning(f"Failed to load tenant config for bank {bank_id}: {e}")

        # Load bank config overrides
        bank_overrides = await self._load_bank_config(bank_id)
        if bank_overrides:
            config_dict.update(bank_overrides)
            logger.debug(f"Applied bank config overrides for bank {bank_id}: {list(bank_overrides.keys())}")

        # Return full config object (dataclass doesn't have __init__ that accepts kwargs, so we update the object)
        # Create a new config instance by copying the global config and updating fields
        resolved_config = AtulyaConfig(**config_dict)
        return resolved_config

    async def get_bank_config(self, bank_id: str, context: RequestContext | None = None) -> dict[str, Any]:
        """
        Get fully resolved config for a bank (filtered by permissions).

        Resolution order:
        1. Global config (from environment variables)
        2. Tenant config overrides (from TenantExtension.get_tenant_config())
        3. Bank config overrides (from banks.config JSONB)

        Note: Config is resolved on every call (not cached) to ensure consistency
        across multiple API servers.

        SECURITY:
        - Only returns configurable fields (excludes static/infrastructure fields)
        - Filters out ALL credential fields (API keys, base URLs, etc.)
        - Further filtered by tenant/bank permissions if extension provides them

        Args:
            bank_id: Bank identifier
            context: Request context for tenant config resolution and permissions

        Returns:
            Dict of allowed configurable fields only (never includes credentials or static fields)
        """
        # Resolve full config with all hierarchical overrides
        resolved_config = await self.resolve_full_config(bank_id, context)
        config_dict = asdict(resolved_config)

        # SECURITY: Filter to only configurable fields (exclude static/infrastructure)
        filtered = {k: v for k, v in config_dict.items() if k in self._configurable_fields}

        # SECURITY: Remove ALL credential fields (API keys, base URLs, etc.)
        filtered = {k: v for k, v in filtered.items() if k not in self._credential_fields}

        # PERMISSIONS: Further filter based on tenant/bank permissions
        if self.tenant_extension and context:
            try:
                allowed_fields = await self.tenant_extension.get_allowed_config_fields(context, bank_id)
                if allowed_fields is not None:  # None means "allow all"
                    filtered = {k: v for k, v in filtered.items() if k in allowed_fields}
                    logger.debug(
                        f"Applied permission filter for bank {bank_id}: allowed={len(allowed_fields)} fields, "
                        f"returned={len(filtered)} fields"
                    )
            except Exception as e:
                logger.warning(f"Failed to load permissions for bank {bank_id}: {e}")

        return filtered

    async def _load_bank_config(self, bank_id: str) -> dict[str, Any]:
        """
        Load bank config overrides from banks.config JSONB column.

        Args:
            bank_id: Bank identifier

        Returns:
            Dict of config overrides (only configurable fields, normalized keys)
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"""
                    SELECT config FROM {fq_table("banks")} WHERE bank_id = $1
                    """,
                    bank_id,
                )

                if row and row["config"]:
                    config_data = row["config"]

                    # Handle case where JSONB is returned as JSON string
                    if isinstance(config_data, str):
                        config_data = json.loads(config_data)

                    # Normalize keys (handle both env var format and Python field format)
                    normalized = normalize_config_dict(config_data)

                    # Only return overrides for configurable fields
                    return {k: v for k, v in normalized.items() if k in self._configurable_fields}
        except Exception as e:
            logger.error(f"Failed to load bank config for {bank_id}: {e}")

        return {}

    async def update_bank_config(
        self, bank_id: str, updates: dict[str, Any], context: RequestContext | None = None
    ) -> None:
        """
        Update bank configuration overrides (with permission checking).

        Args:
            bank_id: Bank identifier
            updates: Dict of config field names to new values.
                    Keys can be in env var format (ATULYA_API_LLM_PROVIDER)
                    or Python field format (llm_provider).
                    Only configurable fields are allowed.
            context: Request context for permission checking

        Raises:
            ValueError: If attempting to override invalid/disallowed fields
        """
        # Normalize keys
        normalized_updates = normalize_config_dict(updates)

        # SECURITY: Reject credential fields explicitly
        credential_attempts = set(normalized_updates.keys()) & self._credential_fields
        if credential_attempts:
            raise ValueError(
                f"Cannot set credential fields via API: {sorted(credential_attempts)}. "
                f"Credentials (API keys, base URLs) must be set at server level only."
            )

        # Validate all fields are configurable
        invalid_fields = set(normalized_updates.keys()) - self._configurable_fields
        if invalid_fields:
            static_fields = AtulyaConfig.get_static_fields()
            invalid_static = invalid_fields & static_fields
            if invalid_static:
                raise ValueError(
                    f"Cannot override static (server-level) fields: {sorted(invalid_static)}. "
                    f"Only configurable fields can be overridden per-bank. "
                    f"Configurable fields include: {sorted(list(self._configurable_fields)[:10])}... "
                    f"(total: {len(self._configurable_fields)} fields)"
                )
            else:
                raise ValueError(
                    f"Unknown configuration fields: {sorted(invalid_fields)}. "
                    f"Valid configurable fields: {sorted(list(self._configurable_fields)[:10])}..."
                )

        # PERMISSIONS: Check tenant/bank permissions
        if self.tenant_extension and context:
            try:
                allowed_fields = await self.tenant_extension.get_allowed_config_fields(context, bank_id)
                if allowed_fields is not None:  # None means "allow all"
                    disallowed = set(normalized_updates.keys()) - allowed_fields
                    if disallowed:
                        raise ValueError(
                            f"Not allowed to modify fields: {sorted(disallowed)}. "
                            f"Your permissions allow: {sorted(list(allowed_fields)[:10])}..."
                            if allowed_fields
                            else "Not allowed to modify fields: {sorted(disallowed)}. "
                            "Your permissions do not allow any config modifications."
                        )
            except ValueError:
                raise  # Re-raise permission errors
            except Exception as e:
                logger.warning(f"Failed to check permissions for bank {bank_id}: {e}")
                # Continue without permission check (fail open for backward compatibility)

        # Merge with existing config (JSONB || operator)
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"""
                UPDATE {fq_table("banks")}
                SET config = config || $1::jsonb,
                    updated_at = now()
                WHERE bank_id = $2
                """,
                json.dumps(normalized_updates),
                bank_id,
            )

        logger.info(f"Updated bank config for {bank_id}: {list(normalized_updates.keys())}")

    async def reset_bank_config(self, bank_id: str) -> None:
        """
        Reset bank configuration to defaults (remove all overrides).

        Args:
            bank_id: Bank identifier
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"""
                UPDATE {fq_table("banks")}
                SET config = '{{}}'::jsonb,
                    updated_at = now()
                WHERE bank_id = $1
                """,
                bank_id,
            )

        logger.info(f"Reset bank config for {bank_id} to defaults")
