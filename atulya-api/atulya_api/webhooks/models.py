"""
Pydantic contracts for webhook configuration and outbound event payloads.

Purpose:
    Typed boundaries between HTTP admin routes, ``WebhookManager``, and delivery
    workers. Ensures consistent JSON shape for HMAC-signed POST bodies.

Trigger path:
    - ``WebhookConfig`` / ``WebhookHttpConfig``: loaded from DB rows or env.
    - ``WebhookEvent``: built in ``MemoryEngine`` when firing after operations.

Inputs:
    - DB columns: ``url``, ``secret``, ``event_types``, ``http_config`` JSONB.
    - Operation metadata: counts, errors, document IDs for event ``data``.

Outputs:
    - ``model_dump_json()`` used as the canonical delivery payload string.

Side effects:
    None — pure data models.

Impact radius:
    Changing field names or enum values breaks registered customer webhook
    parsers and OpenAPI/admin UI contracts.

Maintenance notes:
    Good: extend ``WebhookEventType`` and add a matching ``*EventData`` model.
    Bad: rename ``event`` or ``bank_id`` on ``WebhookEvent`` without versioning.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class WebhookEventType(StrEnum):
    CONSOLIDATION_COMPLETED = "consolidation.completed"
    RETAIN_COMPLETED = "retain.completed"


class ConsolidationEventData(BaseModel):
    observations_created: int | None = None
    observations_updated: int | None = None
    observations_deleted: int | None = None
    error_message: str | None = None


class RetainEventData(BaseModel):
    document_id: str | None = None
    tags: list[str] | None = None


class WebhookEvent(BaseModel):
    event: WebhookEventType
    bank_id: str
    operation_id: str
    status: str  # "completed" or "failed"
    timestamp: datetime
    data: ConsolidationEventData | RetainEventData


class WebhookHttpConfig(BaseModel):
    """HTTP delivery configuration for a webhook."""

    method: str = Field(default="POST", description="HTTP method: GET or POST")
    timeout_seconds: int = Field(default=30, description="HTTP request timeout in seconds")
    headers: dict[str, str] = Field(default_factory=dict, description="Custom HTTP headers")
    params: dict[str, str] = Field(default_factory=dict, description="Custom HTTP query parameters")


class WebhookConfig(BaseModel):
    id: str
    bank_id: str | None
    url: str
    secret: str | None
    event_types: list[str]
    enabled: bool
    http_config: WebhookHttpConfig = Field(default_factory=WebhookHttpConfig)
