"""
Pydantic model for bank-scoped reasoning directives.

Purpose
-------
Defines the ``Directive`` shape used when listing, creating, or injecting
hard rules into reflect prompts. Directives are explicit user-authored
constraints (unlike mental models, which are consolidated from memory).

Trigger path
------------
Loaded from PostgreSQL by ``MemoryEngine`` directive CRUD and reflect assembly.
Referenced in ``response_models.DirectiveRef`` when reflect reports which
directives were applied. HTTP routes in ``api/http.py`` and MCP tools in
``mcp_tools.py`` expose CRUD to clients.

Inputs
------
Database rows or create/update payloads: ``bank_id``, ``name``, ``content``,
``priority``, ``is_active``, ``tags``.

Outputs
------
Validated ``Directive`` instances sorted by priority during prompt injection.
Inactive directives are filtered out before reflect.

Side effects
------------
None at this layer — persistence is handled by ``MemoryEngine`` SQL.

Mutability
----------
Pydantic instances are immutable; updates go through engine methods that write
new row versions.

Impact radius
-------------
Changing ``content`` semantics or priority ordering affects every reflect call
for banks with directives. ``bank_presets`` seeds a codebase directive on bank
create — keep preset content aligned with this schema.

Failure modes
-------------
UUID/datetime parse failures on read indicate corrupt rows.

Maintenance notes
-----------------
Good: add optional metadata fields with defaults.

Bad: merge directives into mental-model tables — they have different lifecycle
and injection rules.
"""

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, Field


class Directive(BaseModel):
    """
    Hard rule injected into reflect prompts for a single bank.

    Higher ``priority`` values are injected first. Only rows with ``is_active=True``
    participate in reflect assembly. Stored in PostgreSQL outside ORM ``models.py``.
    """

    id: UUID = Field(description="Unique identifier")
    bank_id: str = Field(description="Bank this directive belongs to")
    name: str = Field(description="Human-readable name")
    content: str = Field(description="The directive text to inject into prompts")
    priority: int = Field(default=0, description="Higher priority directives are injected first")
    is_active: bool = Field(default=True, description="Whether this directive is currently active")
    tags: list[str] = Field(default_factory=list, description="Tags for filtering")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="When this directive was created"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="When this directive was last updated"
    )

    class Config:
        from_attributes = True
