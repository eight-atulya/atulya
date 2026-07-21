"""Tenant Extension for multi-tenancy and API key authentication."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from atulya_api.extensions.base import Extension
from atulya_api.models import RequestContext

# ---------------------------------------------------------------------------
# Role vocabulary — single source of truth for all auth checks.
# Extend here if new roles are needed; consumers use TenantContext.is_superuser
# or TenantContext.role directly — no scattered string comparisons.
# ---------------------------------------------------------------------------
Role = Literal["superuser", "owner", "admin", "operator", "viewer", "service", "user"]

ROLES_ORDERED: list[Role] = ["superuser", "owner", "admin", "operator", "viewer", "service", "user"]


class AuthenticationError(Exception):
    """Raised when authentication fails."""

    def __init__(self, reason: str, headers: dict[str, str] | None = None):
        self.reason = reason
        self.headers = headers or {}
        super().__init__(f"Authentication failed: {reason}")


@dataclass
class TenantContext:
    """
    Tenant context returned by authentication.

    Contains the PostgreSQL schema name for tenant isolation and the resolved
    role/permission envelope for RBAC + ABAC enforcement.

    All database queries use fully-qualified table names with schema_name
    (e.g., schema_name.memory_units).

    Fields
    ------
    schema_name:
        PostgreSQL schema for this tenant.  Required.
    role:
        Resolved role string: "superuser" | "admin" | "user".
        Default is "user" — safe for all existing callers that only set schema_name.
    allowed_bank_ids:
        None  → unrestricted (can access every bank in schema).
        list  → ABAC allowlist; access denied for any bank_id not in the list.
    is_superuser:
        Derived from role == "superuser".  Set automatically in __post_init__.
        Never set this field directly — set role instead.
    """

    schema_name: str
    role: Role = "user"
    allowed_bank_ids: list[str] | None = None
    org_id: str | None = None
    membership_id: str | None = None
    principal_id: str | None = None
    principal_type: str | None = None
    display_name: str | None = None
    email: str | None = None
    allowed_actions: list[str] | None = None
    action_scopes: dict[str, list[str]] | None = None
    # Derived field — never pass in constructor; always computed from role.
    is_superuser: bool = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "is_superuser", self.role == "superuser")

    def has_role(self, minimum_role: Role) -> bool:
        """Return True if this context's role is at least as privileged as minimum_role."""
        required_idx = ROLES_ORDERED.index(minimum_role)
        actual_idx = ROLES_ORDERED.index(self.role) if self.role in ROLES_ORDERED else len(ROLES_ORDERED)
        return actual_idx <= required_idx

    def can_access_bank(self, bank_id: str) -> bool:
        """
        ABAC check: can this context access the given bank_id?

        Superusers bypass the allowlist entirely.
        All other roles respect allowed_bank_ids (None = unrestricted).
        """
        if self.is_superuser:
            return True
        if self.allowed_bank_ids is None:
            return True
        return bank_id in self.allowed_bank_ids

    def apply_to_request_context(self, request_context: RequestContext) -> None:
        """Copy resolved auth identity onto the mutable request context."""

        request_context.schema_name = self.schema_name
        request_context.role = self.role
        request_context.allowed_bank_ids = self.allowed_bank_ids
        request_context.org_id = self.org_id
        request_context.membership_id = self.membership_id
        request_context.principal_id = self.principal_id
        request_context.principal_type = self.principal_type
        request_context.display_name = self.display_name
        request_context.email = self.email
        request_context.allowed_actions = self.allowed_actions
        request_context.action_scopes = self.action_scopes


@dataclass
class Tenant:
    """
    Represents a tenant for worker discovery.

    Used by list_tenants() to return tenant information including
    the PostgreSQL schema name for database operations.
    """

    schema: str


class TenantExtension(Extension, ABC):
    """
    Extension for multi-tenancy and API key authentication.

    This extension validates incoming requests and returns the tenant context
    including the PostgreSQL schema to use for database operations.

    Built-in implementation:
        atulya_api.extensions.builtin.tenant.ApiKeyTenantExtension

    Enable via environment variable:
        ATULYA_API_TENANT_EXTENSION=atulya_api.extensions.builtin.tenant:ApiKeyTenantExtension
        ATULYA_API_TENANT_API_KEY=your-secret-key

    The returned schema_name is used for fully-qualified table names in queries,
    enabling tenant isolation at the database level.
    """

    @abstractmethod
    async def authenticate(self, context: RequestContext) -> TenantContext:
        """
        Authenticate the action context and return tenant context.

        Args:
            context: The action context containing API key and other auth data.

        Returns:
            TenantContext with the schema_name for database operations.

        Raises:
            AuthenticationError: If authentication fails.
        """
        ...

    @abstractmethod
    async def list_tenants(self) -> list[Tenant]:
        """
        List all tenants that should be processed by workers.

        This method is used by the worker to discover all tenants that need
        task polling. Workers will poll for pending tasks in each tenant's schema.

        Returns:
            List of Tenant objects containing schema information.
            For single-tenant setups, return [Tenant(schema="public")].
        """
        ...

    async def get_tenant_config(self, context: RequestContext) -> dict[str, Any]:
        """
        Get tenant-specific configuration overrides.

        This method is called during hierarchical configuration resolution to get
        tenant-level config overrides. The returned dict should contain Python field
        names (lowercase snake_case) as keys, not environment variable names.

        Example:
            {"llm_model": "gpt-4", "retain_extraction_mode": "verbose"}

        The default implementation returns an empty dict (no tenant-specific config).
        Override this method in custom extensions to provide tenant-specific configuration.

        Args:
            context: The request context containing tenant information.

        Returns:
            Dict of config field names to values (only configurable fields).
            Empty dict if no tenant-specific config.
        """
        return {}

    async def get_allowed_config_fields(self, context: RequestContext, bank_id: str) -> set[str] | None:
        """
        Get set of config fields that this tenant/bank is allowed to modify.

        This method controls which configurable fields can be modified via the bank config API.
        It enables fine-grained permission control per tenant or per bank.

        Examples:
            - Return None: Allow all configurable fields (default)
            - Return {"retain_chunk_size", "retain_custom_instructions"}: Allow only these fields
            - Return set(): Allow no modifications (read-only)

        The default implementation returns None (all configurable fields allowed).
        Override this method in custom extensions to implement custom permission logic.

        Args:
            context: The request context containing tenant information.
            bank_id: The bank identifier for per-bank permissions.

        Returns:
            Set of allowed field names, or None to allow all configurable fields.
            Returned fields must be a subset of AtulyaConfig.get_configurable_fields().
        """
        return None

    async def authenticate_mcp(self, context: RequestContext) -> TenantContext:
        """
        Authenticate MCP requests.

        By default, this calls authenticate(). Override this method to provide
        different authentication behavior for MCP endpoints (e.g., to disable
        auth for backwards compatibility with existing MCP servers).

        Args:
            context: The action context containing API key and other auth data.

        Returns:
            TenantContext with the schema_name for database operations.

        Raises:
            AuthenticationError: If authentication fails.
        """
        return await self.authenticate(context)
