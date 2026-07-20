"""Add org RBAC/ABAC auth tables.

Revision ID: 08010ff6bc04
Revises: 08010ef5ab03
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import context, op

revision: str = "08010ff6bc04"
down_revision: str | Sequence[str] | None = "08010ef5ab03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _get_schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else ""


def upgrade() -> None:
    schema = _get_schema_prefix()

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {schema}orgs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            schema_name TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'disabled')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {schema}principals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES {schema}orgs(id) ON DELETE CASCADE,
            email TEXT,
            display_name TEXT NOT NULL,
            principal_type TEXT NOT NULL DEFAULT 'user'
                CHECK (principal_type IN ('user', 'service')),
            role TEXT NOT NULL DEFAULT 'viewer'
                CHECK (role IN ('owner', 'admin', 'operator', 'viewer', 'service', 'superuser', 'user')),
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'disabled')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS ux_principals_org_email ON {schema}principals (org_id, lower(email)) WHERE email IS NOT NULL"
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {schema}principal_credentials (
            principal_id UUID PRIMARY KEY REFERENCES {schema}principals(id) ON DELETE CASCADE,
            password_hash TEXT NOT NULL,
            password_changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {schema}principal_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            principal_id UUID NOT NULL REFERENCES {schema}principals(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            token_prefix TEXT NOT NULL,
            hash_version INTEGER NOT NULL DEFAULT 2,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            last_used_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {schema}access_grants (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES {schema}orgs(id) ON DELETE CASCADE,
            subject_type TEXT NOT NULL CHECK (subject_type IN ('principal', 'role')),
            subject_id TEXT NOT NULL,
            action TEXT NOT NULL,
            scope_type TEXT NOT NULL CHECK (scope_type IN ('org', 'bank', 'system')),
            scope_id TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (org_id, subject_type, subject_id, action, scope_type, scope_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {schema}audit_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID REFERENCES {schema}orgs(id) ON DELETE SET NULL,
            actor_principal_id UUID REFERENCES {schema}principals(id) ON DELETE SET NULL,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id TEXT,
            result TEXT NOT NULL DEFAULT 'success',
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(f"ALTER TABLE {schema}api_keys ADD COLUMN IF NOT EXISTS principal_id UUID")
    op.execute(f"ALTER TABLE {schema}api_keys ADD COLUMN IF NOT EXISTS key_prefix TEXT")
    op.execute(f"ALTER TABLE {schema}api_keys ADD COLUMN IF NOT EXISTS hash_version INTEGER NOT NULL DEFAULT 1")
    op.execute(f"ALTER TABLE {schema}api_keys ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ")
    op.execute(f"ALTER TABLE {schema}api_keys ADD COLUMN IF NOT EXISTS created_by UUID")
    op.execute(f"ALTER TABLE {schema}api_keys ADD COLUMN IF NOT EXISTS description TEXT")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_api_keys_principal ON {schema}api_keys (principal_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_principal_sessions_hash ON {schema}principal_sessions (token_hash)")
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_access_grants_subject ON {schema}access_grants (org_id, subject_type, subject_id)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_audit_events_org_created ON {schema}audit_events (org_id, created_at DESC)"
    )


def downgrade() -> None:
    schema = _get_schema_prefix()
    op.execute(f"DROP TABLE IF EXISTS {schema}audit_events")
    op.execute(f"DROP TABLE IF EXISTS {schema}access_grants")
    op.execute(f"DROP TABLE IF EXISTS {schema}principal_sessions")
    op.execute(f"DROP TABLE IF EXISTS {schema}principal_credentials")
    op.execute(f"DROP TABLE IF EXISTS {schema}principals")
    op.execute(f"DROP TABLE IF EXISTS {schema}orgs")
    op.execute(f"ALTER TABLE {schema}api_keys DROP COLUMN IF EXISTS description")
    op.execute(f"ALTER TABLE {schema}api_keys DROP COLUMN IF EXISTS created_by")
    op.execute(f"ALTER TABLE {schema}api_keys DROP COLUMN IF EXISTS last_used_at")
    op.execute(f"ALTER TABLE {schema}api_keys DROP COLUMN IF EXISTS hash_version")
    op.execute(f"ALTER TABLE {schema}api_keys DROP COLUMN IF EXISTS key_prefix")
    op.execute(f"ALTER TABLE {schema}api_keys DROP COLUMN IF EXISTS principal_id")
