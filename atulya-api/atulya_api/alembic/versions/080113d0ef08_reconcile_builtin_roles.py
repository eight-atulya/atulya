"""Reconcile canonical built-in roles for existing organizations.

Revision ID: 080113d0ef08
Revises: 080112c9de07
Create Date: 2026-07-20
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import context, op

revision: str = "080113d0ef08"
down_revision: str | Sequence[str] | None = "080112c9de07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORG_ACTIONS = (
    "admin.audit",
    "admin.grants",
    "admin.keys",
    "admin.users",
    "bank.config",
    "bank.delete",
    "bank.read",
    "bank.write",
    "brain.read",
    "brain.write",
    "forge.export",
    "forge.read",
    "forge.run",
    "memory.delete",
    "memory.recall",
    "memory.retain",
    "reflect.run",
    "webhook.manage",
)
OPERATOR_ACTIONS = (
    "bank.config",
    "bank.read",
    "bank.write",
    "brain.read",
    "brain.write",
    "forge.export",
    "forge.read",
    "forge.run",
    "memory.delete",
    "memory.recall",
    "memory.retain",
    "reflect.run",
    "webhook.manage",
)
VIEWER_ACTIONS = ("bank.read", "brain.read", "forge.read", "memory.recall", "reflect.run")
ROLE_ACTIONS = {
    "owner": ORG_ACTIONS,
    "admin": ORG_ACTIONS,
    "operator": OPERATOR_ACTIONS,
    "viewer": VIEWER_ACTIONS,
    "service": (),
}


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else ""


def _is_auth_schema() -> bool:
    target = context.config.get_main_option("target_schema") or "public"
    return target == os.getenv("ATULYA_API_AUTH_SCHEMA", "public")


def upgrade() -> None:
    if not _is_auth_schema():
        return
    schema = _schema_prefix()
    for role_name, actions in ROLE_ACTIONS.items():
        description = f"Built-in {role_name} role"
        op.execute(
            f"""
            INSERT INTO {schema}roles (org_id, name, description, is_builtin)
            SELECT id, '{role_name}', '{description}', TRUE FROM {schema}orgs
            ON CONFLICT (org_id, name) DO UPDATE
            SET description = EXCLUDED.description, is_builtin = TRUE, updated_at = NOW()
            """
        )
        op.execute(
            f"""
            DELETE FROM {schema}role_actions ra
            USING {schema}roles r
            WHERE ra.role_id = r.id AND r.name = '{role_name}' AND r.is_builtin
            """
        )
        if actions:
            values = ", ".join(f"('{action}')" for action in actions)
            op.execute(
                f"""
                INSERT INTO {schema}role_actions (role_id, action)
                SELECT r.id, v.action
                FROM {schema}roles r
                CROSS JOIN (VALUES {values}) AS v(action)
                WHERE r.name = '{role_name}' AND r.is_builtin
                ON CONFLICT DO NOTHING
                """
            )


def downgrade() -> None:
    # Built-in role reconciliation is intentionally retained on downgrade.
    pass
