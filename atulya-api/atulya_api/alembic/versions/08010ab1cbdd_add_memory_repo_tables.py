"""Add memory repo versioning tables.

Revision ID: 08010ab1cbdd
Revises: 080109b0cbdc
Create Date: 2026-05-06
"""

from __future__ import annotations

from typing import Sequence

from alembic import context, op

revision: str = "08010ab1cbdd"
down_revision: str | Sequence[str] | None = "080109b0cbdc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else "public."


def upgrade() -> None:
    prefix = _schema_prefix()

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}memory_repos (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            root_bank_id text NOT NULL UNIQUE,
            name text NOT NULL,
            active_branch text NOT NULL DEFAULT 'main',
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}memory_objects (
            object_hash text PRIMARY KEY,
            object_kind text NOT NULL,
            payload jsonb NOT NULL,
            size_bytes integer NOT NULL DEFAULT 0,
            created_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}memory_commits (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            repo_id uuid NOT NULL REFERENCES {prefix}memory_repos(id) ON DELETE CASCADE,
            parent_commit_id uuid REFERENCES {prefix}memory_commits(id) ON DELETE SET NULL,
            branch_name text NOT NULL,
            message text NOT NULL,
            actor text,
            root_manifest_hash text NOT NULL REFERENCES {prefix}memory_objects(object_hash) ON DELETE RESTRICT,
            stats jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            created_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}memory_refs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            repo_id uuid NOT NULL REFERENCES {prefix}memory_repos(id) ON DELETE CASCADE,
            ref_type text NOT NULL DEFAULT 'branch',
            ref_name text NOT NULL,
            head_commit_id uuid REFERENCES {prefix}memory_commits(id) ON DELETE SET NULL,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now(),
            UNIQUE (repo_id, ref_type, ref_name)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {prefix}memory_workspaces (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            repo_id uuid NOT NULL REFERENCES {prefix}memory_repos(id) ON DELETE CASCADE,
            branch_name text NOT NULL,
            workspace_bank_id text NOT NULL,
            head_commit_id uuid REFERENCES {prefix}memory_commits(id) ON DELETE SET NULL,
            is_active boolean NOT NULL DEFAULT false,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now(),
            UNIQUE (repo_id, branch_name)
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_memory_commits_repo_branch_created
        ON {prefix}memory_commits (repo_id, branch_name, created_at DESC)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_memory_refs_repo_type
        ON {prefix}memory_refs (repo_id, ref_type)
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_workspaces_repo_active
        ON {prefix}memory_workspaces (repo_id)
        WHERE is_active = true
        """
    )


def downgrade() -> None:
    prefix = _schema_prefix()
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_memory_workspaces_repo_active")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_memory_refs_repo_type")
    op.execute(f"DROP INDEX IF EXISTS {prefix}idx_memory_commits_repo_branch_created")
    op.execute(f"DROP TABLE IF EXISTS {prefix}memory_workspaces")
    op.execute(f"DROP TABLE IF EXISTS {prefix}memory_refs")
    op.execute(f"DROP TABLE IF EXISTS {prefix}memory_commits")
    op.execute(f"DROP TABLE IF EXISTS {prefix}memory_objects")
    op.execute(f"DROP TABLE IF EXISTS {prefix}memory_repos")
