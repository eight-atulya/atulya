"""Normalize identities, memberships, roles, and auth challenges.

Revision ID: 080110a7bc05
Revises: 08010ff6bc04
Create Date: 2026-07-20
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import context, op

ORG_ACTIONS = (
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
)
OPERATOR_ACTIONS = tuple(
    action for action in ORG_ACTIONS if not action.startswith("admin.") and action != "bank.delete"
)
VIEWER_ACTIONS = ("bank.read", "memory.recall", "reflect.run", "forge.read", "brain.read")

revision: str = "080110a7bc05"
down_revision: str | Sequence[str] | None = "08010ff6bc04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _get_schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else ""


def _is_auth_schema() -> bool:
    target = context.config.get_main_option("target_schema") or "public"
    return target == os.getenv("ATULYA_API_AUTH_SCHEMA", "public")


def upgrade() -> None:
    if not _is_auth_schema():
        return
    schema = _get_schema_prefix()

    op.execute(f"ALTER TABLE {schema}principals ALTER COLUMN org_id DROP NOT NULL")
    op.execute(f"ALTER TABLE {schema}principals ALTER COLUMN role DROP NOT NULL")
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS ux_principals_global_email "
        f"ON {schema}principals (lower(email)) WHERE email IS NOT NULL AND principal_type = 'user'"
    )
    op.execute(f"ALTER TABLE {schema}principals ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ")
    op.execute(f"ALTER TABLE {schema}principals ADD COLUMN IF NOT EXISTS last_active_org_id UUID")
    op.execute(
        f"ALTER TABLE {schema}principals ADD CONSTRAINT principals_last_active_org_fk "
        f"FOREIGN KEY (last_active_org_id) REFERENCES {schema}orgs(id) ON DELETE SET NULL"
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {schema}roles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID REFERENCES {schema}orgs(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            is_builtin BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (org_id, name),
            CHECK ((org_id IS NULL AND name = 'platform_admin') OR org_id IS NOT NULL)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {schema}role_actions (
            role_id UUID NOT NULL REFERENCES {schema}roles(id) ON DELETE CASCADE,
            action TEXT NOT NULL,
            PRIMARY KEY (role_id, action)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {schema}org_memberships (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES {schema}orgs(id) ON DELETE CASCADE,
            principal_id UUID NOT NULL REFERENCES {schema}principals(id) ON DELETE CASCADE,
            role_id UUID NOT NULL REFERENCES {schema}roles(id) ON DELETE RESTRICT,
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('invited', 'active', 'disabled')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (org_id, principal_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {schema}membership_scopes (
            membership_id UUID NOT NULL REFERENCES {schema}org_memberships(id) ON DELETE CASCADE,
            scope_type TEXT NOT NULL CHECK (scope_type IN ('org', 'bank')),
            scope_id TEXT NOT NULL,
            PRIMARY KEY (membership_id, scope_type, scope_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {schema}auth_challenges (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            principal_id UUID REFERENCES {schema}principals(id) ON DELETE CASCADE,
            email TEXT NOT NULL,
            challenge_type TEXT NOT NULL CHECK (challenge_type IN ('verify_email', 'reset_password', 'invite')),
            token_hash TEXT NOT NULL UNIQUE,
            payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {schema}auth_rate_limits (
            bucket TEXT PRIMARY KEY,
            attempts INTEGER NOT NULL DEFAULT 0,
            window_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            blocked_until TIMESTAMPTZ
        )
        """
    )

    op.execute(f"ALTER TABLE {schema}principal_sessions ADD COLUMN IF NOT EXISTS active_org_id UUID")
    op.execute(f"ALTER TABLE {schema}principal_sessions ADD COLUMN IF NOT EXISTS idle_expires_at TIMESTAMPTZ")
    op.execute(f"ALTER TABLE {schema}principal_sessions ADD COLUMN IF NOT EXISTS revocation_reason TEXT")
    op.execute(f"ALTER TABLE {schema}principal_sessions ADD COLUMN IF NOT EXISTS ip_address INET")
    op.execute(f"ALTER TABLE {schema}principal_sessions ADD COLUMN IF NOT EXISTS user_agent TEXT")
    op.execute(f"ALTER TABLE {schema}access_grants ALTER COLUMN org_id DROP NOT NULL")
    op.execute(f"ALTER TABLE {schema}api_keys ADD COLUMN IF NOT EXISTS rotated_from_id UUID")
    op.execute(
        f"ALTER TABLE {schema}principal_sessions ADD CONSTRAINT principal_sessions_active_org_fk "
        f"FOREIGN KEY (active_org_id) REFERENCES {schema}orgs(id) ON DELETE SET NULL"
    )
    op.execute(
        f"ALTER TABLE {schema}api_keys ADD CONSTRAINT api_keys_rotated_from_fk "
        f"FOREIGN KEY (rotated_from_id) REFERENCES {schema}api_keys(id) ON DELETE SET NULL"
    )
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS ux_access_grants_system_subject "
        f"ON {schema}access_grants (subject_type, subject_id, action, scope_type, scope_id) WHERE org_id IS NULL"
    )

    op.execute(f"ALTER TABLE {schema}orgs DROP CONSTRAINT IF EXISTS orgs_status_check")
    op.execute(
        f"ALTER TABLE {schema}orgs ADD CONSTRAINT orgs_status_check "
        "CHECK (status IN ('provisioning', 'active', 'failed', 'disabled'))"
    )

    # Backfill current development identities into the normalized model. The
    # guarded reset command may remove these rows before the production run.
    for role_name in ("owner", "admin", "operator", "viewer", "service"):
        op.execute(
            f"""
            INSERT INTO {schema}roles (org_id, name, is_builtin)
            SELECT id, '{role_name}', TRUE FROM {schema}orgs
            ON CONFLICT (org_id, name) DO NOTHING
            """
        )
    for role_name, actions in (
        ("owner", ORG_ACTIONS),
        ("admin", ORG_ACTIONS),
        ("operator", OPERATOR_ACTIONS),
        ("viewer", VIEWER_ACTIONS),
    ):
        values = ", ".join(f"('{role_name}', '{action}')" for action in actions)
        op.execute(
            f"""
            INSERT INTO {schema}role_actions (role_id, action)
            SELECT r.id, v.action
            FROM {schema}roles r
            JOIN (VALUES {values}) AS v(role_name, action) ON v.role_name = r.name
            WHERE r.name = '{role_name}'
            ON CONFLICT DO NOTHING
            """
        )
    op.execute(
        f"""
        INSERT INTO {schema}org_memberships (org_id, principal_id, role_id, status)
        SELECT p.org_id, p.id, r.id, p.status
        FROM {schema}principals p
        JOIN {schema}roles r ON r.org_id = p.org_id AND r.name = CASE
            WHEN p.role IN ('owner', 'admin', 'operator', 'viewer') THEN p.role
            ELSE 'viewer'
        END
        WHERE p.org_id IS NOT NULL
        ON CONFLICT (org_id, principal_id) DO NOTHING
        """
    )
    op.execute(
        f"""
        INSERT INTO {schema}membership_scopes (membership_id, scope_type, scope_id)
        SELECT m.id, 'org', '*'
        FROM {schema}org_memberships m
        JOIN {schema}roles r ON r.id = m.role_id
        WHERE r.name IN ('owner', 'admin')
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    if not _is_auth_schema():
        return
    schema = _get_schema_prefix()
    op.execute(f"DROP INDEX IF EXISTS {schema}ux_access_grants_system_subject")
    op.execute(f"ALTER TABLE {schema}api_keys DROP CONSTRAINT IF EXISTS api_keys_rotated_from_fk")
    op.execute(f"ALTER TABLE {schema}api_keys DROP COLUMN IF EXISTS rotated_from_id")
    op.execute(f"ALTER TABLE {schema}principal_sessions DROP CONSTRAINT IF EXISTS principal_sessions_active_org_fk")
    op.execute(f"ALTER TABLE {schema}principals DROP CONSTRAINT IF EXISTS principals_last_active_org_fk")
    op.execute(f"DROP TABLE IF EXISTS {schema}auth_rate_limits")
    op.execute(f"DROP TABLE IF EXISTS {schema}auth_challenges")
    op.execute(f"DROP TABLE IF EXISTS {schema}membership_scopes")
    op.execute(f"DROP TABLE IF EXISTS {schema}org_memberships")
    op.execute(f"DROP TABLE IF EXISTS {schema}role_actions")
    op.execute(f"DROP TABLE IF EXISTS {schema}roles")
    op.execute(f"DROP INDEX IF EXISTS {schema}ux_principals_global_email")
    op.execute(f"ALTER TABLE {schema}principal_sessions DROP COLUMN IF EXISTS user_agent")
    op.execute(f"ALTER TABLE {schema}principal_sessions DROP COLUMN IF EXISTS ip_address")
    op.execute(f"ALTER TABLE {schema}principal_sessions DROP COLUMN IF EXISTS revocation_reason")
    op.execute(f"ALTER TABLE {schema}principal_sessions DROP COLUMN IF EXISTS idle_expires_at")
    op.execute(f"ALTER TABLE {schema}principal_sessions DROP COLUMN IF EXISTS active_org_id")
    op.execute(f"ALTER TABLE {schema}principals DROP COLUMN IF EXISTS last_active_org_id")
    op.execute(f"ALTER TABLE {schema}principals DROP COLUMN IF EXISTS email_verified_at")
