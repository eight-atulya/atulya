"""Add api_keys table for DB-backed API key management (RBAC + ABAC).

Revision ID: 080109b0cbdc
Revises: 080108a9bacb
Create Date: 2026-04-28

Schema: public (Layer 0 — no FK dependencies on any other table).

Security notes:
  - key_hash stores SHA-256(raw_key) — raw key is NEVER persisted.
  - allowed_bank_ids = NULL means unrestricted (all banks).
  - revoked_at IS NOT NULL means the key is invalid immediately.
  - expires_at IS NOT NULL AND expires_at < NOW() means the key is expired.

"""

from __future__ import annotations

import os
from typing import Sequence

from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "080109b0cbdc"
down_revision: str | Sequence[str] | None = "080108a9bacb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_auth_schema() -> bool:
    target = context.config.get_main_option("target_schema") or "public"
    return target == os.getenv("ATULYA_API_AUTH_SCHEMA", "public")


def upgrade() -> None:
    if not _is_auth_schema():
        return
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            key_hash          TEXT        NOT NULL UNIQUE,
            name              TEXT        NOT NULL,
            role              TEXT        NOT NULL DEFAULT 'user'
                              CHECK (role IN ('superuser', 'admin', 'user')),
            schema_name       TEXT        NOT NULL DEFAULT 'public',
            allowed_bank_ids  TEXT[]      DEFAULT NULL,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at        TIMESTAMPTZ DEFAULT NULL,
            revoked_at        TIMESTAMPTZ DEFAULT NULL
        )
        """
    )
    # Index for fast key lookup (hot path — every request with DbApiKeyTenantExtension)
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_keys_key_hash ON api_keys (key_hash)")
    # Index for listing active keys by schema (admin UI)
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_keys_schema_name ON api_keys (schema_name)")


def downgrade() -> None:
    if not _is_auth_schema():
        return
    op.execute("DROP TABLE IF EXISTS api_keys")
