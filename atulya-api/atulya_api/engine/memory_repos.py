"""Git-like memory repo snapshotting and branch workspace orchestration."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .db_utils import acquire_with_retry

if TYPE_CHECKING:
    import asyncpg

    from atulya_api.models import RequestContext

    from .memory_engine import MemoryEngine

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RestoreIdMaps:
    """Identifier remap state for restoring one snapshot into another workspace bank."""

    remap_enabled: bool = False
    chunk_ids: dict[str, str] = field(default_factory=dict)
    entity_ids: dict[str, str] = field(default_factory=dict)
    unit_ids: dict[str, str] = field(default_factory=dict)
    entity_trajectory_ids: dict[str, str] = field(default_factory=dict)
    entity_intelligence_ids: dict[str, str] = field(default_factory=dict)
    directive_ids: dict[str, str] = field(default_factory=dict)
    webhook_ids: dict[str, str] = field(default_factory=dict)
    codebase_ids: dict[str, str] = field(default_factory=dict)
    codebase_snapshot_ids: dict[str, str] = field(default_factory=dict)
    codebase_file_ids: dict[str, str] = field(default_factory=dict)
    codebase_symbol_ids: dict[str, str] = field(default_factory=dict)
    codebase_edge_ids: dict[str, str] = field(default_factory=dict)
    codebase_chunk_ids: dict[str, str] = field(default_factory=dict)
    codebase_chunk_edge_ids: dict[str, str] = field(default_factory=dict)
    codebase_review_route_ids: dict[str, str] = field(default_factory=dict)
    codebase_intel_artifact_ids: dict[str, str] = field(default_factory=dict)
    codebase_auto_triage_override_ids: dict[str, str] = field(default_factory=dict)
    codebase_saved_intent_ids: dict[str, str] = field(default_factory=dict)


_ORIGIN_ID_MAP_FIELDS = (
    "chunk_ids",
    "entity_ids",
    "unit_ids",
    "entity_trajectory_ids",
    "entity_intelligence_ids",
    "directive_ids",
    "webhook_ids",
    "codebase_ids",
    "codebase_snapshot_ids",
    "codebase_file_ids",
    "codebase_symbol_ids",
    "codebase_edge_ids",
    "codebase_chunk_ids",
    "codebase_chunk_edge_ids",
    "codebase_review_route_ids",
    "codebase_intel_artifact_ids",
    "codebase_auto_triage_override_ids",
    "codebase_saved_intent_ids",
)

_COMPONENT_TABLES: dict[str, list[str]] = {
    "profile_config": ["banks"],
    "directives": ["directives"],
    "mental_models": ["mental_models"],
    "documents_memories_graph": [
        "documents",
        "chunks",
        "memory_units",
        "entities",
        "unit_entities",
        "entity_cooccurrences",
        "memory_links",
        "entity_trajectories",
        "entity_intelligence",
    ],
    "codebases": [
        "codebases",
        "codebase_snapshots",
        "codebase_files",
        "codebase_symbols",
        "codebase_edges",
        "codebase_chunks",
        "codebase_chunk_edges",
        "codebase_review_routes",
        "codebase_intel_artifacts",
        "codebase_auto_triage_overrides",
        "codebase_saved_intents",
    ],
    "webhooks": ["webhooks"],
}

_DIRECT_BANK_TABLES = {
    "banks",
    "documents",
    "chunks",
    "memory_units",
    "entities",
    "entity_trajectories",
    "entity_intelligence",
    "directives",
    "mental_models",
    "webhooks",
    "codebases",
    "codebase_snapshots",
    "codebase_files",
    "codebase_symbols",
    "codebase_edges",
    "codebase_chunks",
    "codebase_chunk_edges",
    "codebase_review_routes",
    "codebase_intel_artifacts",
    "codebase_auto_triage_overrides",
    "codebase_saved_intents",
}

_RESTORE_ORDER = [
    "banks",
    "documents",
    "chunks",
    "entities",
    "memory_units",
    "unit_entities",
    "entity_cooccurrences",
    "memory_links",
    "entity_trajectories",
    "entity_intelligence",
    "directives",
    "mental_models",
    "webhooks",
    "codebases",
    "codebase_snapshots",
    "codebase_files",
    "codebase_symbols",
    "codebase_edges",
    "codebase_chunks",
    "codebase_chunk_edges",
    "codebase_review_routes",
    "codebase_intel_artifacts",
    "codebase_auto_triage_overrides",
    "codebase_saved_intents",
]


def _fq_table(name: str) -> str:
    from .memory_engine import fq_table

    return fq_table(name)


class MemoryRepoService:
    """Encapsulates repo snapshot, branch, and commit behavior."""

    def __init__(self, engine: "MemoryEngine"):
        self._engine = engine
        self._column_cache: dict[tuple[str, str], list[dict[str, str]]] = {}

    async def list_repos(self) -> list[dict[str, Any]]:
        pool = await self._engine._get_pool()
        async with acquire_with_retry(pool) as conn:
            rows = await conn.fetch(
                f"""
                SELECT r.id, r.root_bank_id, r.name, r.active_branch, r.created_at, r.updated_at,
                       mr.head_commit_id,
                       mc.message AS head_message,
                       mc.created_at AS head_created_at
                FROM {_fq_table("memory_repos")} r
                LEFT JOIN {_fq_table("memory_refs")} mr
                  ON mr.repo_id = r.id AND mr.ref_type = 'branch' AND mr.ref_name = r.active_branch
                LEFT JOIN {_fq_table("memory_commits")} mc
                  ON mc.id = mr.head_commit_id
                ORDER BY r.updated_at DESC
                """
            )
            return [self._repo_row_to_dict(row) for row in rows]

    async def get_repo(self, repo_id: str) -> dict[str, Any]:
        pool = await self._engine._get_pool()
        async with acquire_with_retry(pool) as conn:
            repo = await self._get_repo_summary_row(conn, repo_id)
            return await self._repo_summary(conn, repo)

    async def get_repo_for_bank(self, bank_id: str) -> dict[str, Any] | None:
        pool = await self._engine._get_pool()
        async with acquire_with_retry(pool) as conn:
            repo = await self._get_repo_summary_row_by_root_bank(conn, bank_id)
            if not repo:
                return None
            return await self._repo_summary(conn, repo)

    async def create_repo(
        self,
        *,
        bank_id: str,
        repo_name: str | None,
        source_bank_id: str | None,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        source_bank = source_bank_id or bank_id
        await self._engine.get_bank_profile(bank_id, request_context=request_context)
        if source_bank != bank_id:
            snapshot = await self.capture_bank_snapshot(source_bank)
            await self.restore_snapshot_to_bank(
                bank_id,
                snapshot,
                internal_workspace=False,
                root_bank_id=bank_id,
                branch_name="main",
            )
        return await self.enable_repo(bank_id=bank_id, repo_name=repo_name, request_context=request_context)

    async def enable_repo(
        self,
        *,
        bank_id: str,
        repo_name: str | None,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        await self._engine.get_bank_profile(bank_id, request_context=request_context)
        snapshot = await self.capture_bank_snapshot(bank_id)
        pool = await self._engine._get_pool()
        async with acquire_with_retry(pool) as conn:
            existing = await conn.fetchrow(
                f"SELECT * FROM {_fq_table('memory_repos')} WHERE root_bank_id = $1",
                bank_id,
            )
            if existing:
                return await self._repo_summary(conn, existing)

            repo_id = uuid.uuid4()
            repo_name = repo_name or bank_id
            await conn.execute(
                f"""
                INSERT INTO {_fq_table("memory_repos")} (id, root_bank_id, name, active_branch)
                VALUES ($1, $2, $3, 'main')
                """,
                repo_id,
                bank_id,
                repo_name,
            )
            manifest_hash, stats = await self._persist_snapshot(conn, bank_id=bank_id, snapshot=snapshot)
            commit_id = uuid.uuid4()
            await conn.execute(
                f"""
                INSERT INTO {_fq_table("memory_commits")}
                    (id, repo_id, parent_commit_id, branch_name, message, actor, root_manifest_hash, stats)
                VALUES ($1, $2, NULL, 'main', $3, $4, $5, $6::jsonb)
                """,
                commit_id,
                repo_id,
                "Initial commit",
                "system",
                manifest_hash,
                json.dumps(stats),
            )
            await conn.execute(
                f"""
                INSERT INTO {_fq_table("memory_refs")} (repo_id, ref_type, ref_name, head_commit_id)
                VALUES ($1, 'branch', 'main', $2)
                """,
                repo_id,
                commit_id,
            )
            await conn.execute(
                f"""
                INSERT INTO {_fq_table("memory_workspaces")} (repo_id, branch_name, workspace_bank_id, head_commit_id, is_active)
                VALUES ($1, 'main', $2, $3, true)
                """,
                repo_id,
                bank_id,
                commit_id,
            )
            return await self._repo_summary(conn, await self._get_repo_row(conn, str(repo_id)))

    async def list_branches(self, repo_id: str) -> list[dict[str, Any]]:
        pool = await self._engine._get_pool()
        async with acquire_with_retry(pool) as conn:
            repo = await self._get_repo_row(conn, repo_id)
            rows = await conn.fetch(
                f"""
                SELECT w.branch_name, w.workspace_bank_id, w.is_active, w.head_commit_id,
                       c.message AS head_message, c.created_at AS head_created_at
                FROM {_fq_table("memory_workspaces")} w
                LEFT JOIN {_fq_table("memory_commits")} c ON c.id = w.head_commit_id
                WHERE w.repo_id = $1
                ORDER BY w.branch_name
                """,
                repo["id"],
            )
            items: list[dict[str, Any]] = []
            for row in rows:
                status = await self.get_status(str(repo["id"]), branch_name=row["branch_name"])
                items.append(
                    {
                        "branch_name": row["branch_name"],
                        "workspace_bank_id": row["workspace_bank_id"],
                        "is_active": row["is_active"],
                        "head_commit_id": str(row["head_commit_id"]) if row["head_commit_id"] else None,
                        "head_message": row["head_message"],
                        "head_created_at": row["head_created_at"].isoformat() if row["head_created_at"] else None,
                        "dirty": status["dirty"],
                    }
                )
            return items

    async def list_branches_for_bank(self, bank_id: str) -> list[dict[str, Any]]:
        repo = await self.get_repo_for_bank(bank_id)
        if not repo:
            return []
        return list(repo.get("branches") or [])

    async def resolve_workspace_bank_id_for_bank_branch(self, root_bank_id: str, branch_name: str) -> str:
        pool = await self._engine._get_pool()
        async with acquire_with_retry(pool) as conn:
            repo_row = await conn.fetchrow(
                f"SELECT id FROM {_fq_table('memory_repos')} WHERE root_bank_id = $1",
                root_bank_id,
            )
            if not repo_row:
                raise ValueError(f"Repo mode is not enabled for bank: {root_bank_id}")
            workspace_row = await conn.fetchrow(
                f"""
                SELECT workspace_bank_id
                FROM {_fq_table("memory_workspaces")}
                WHERE repo_id = $1 AND branch_name = $2
                """,
                repo_row["id"],
                branch_name,
            )
            if not workspace_row:
                raise ValueError(f"Branch not found for bank {root_bank_id}: {branch_name}")
            return str(workspace_row["workspace_bank_id"])

    async def create_branch(
        self,
        repo_id: str,
        *,
        branch_name: str,
        from_commit_id: str | None = None,
    ) -> dict[str, Any]:
        pool = await self._engine._get_pool()
        async with acquire_with_retry(pool) as conn:
            repo = await self._get_repo_row(conn, repo_id)
            await self._ensure_branch_absent(conn, repo["id"], branch_name)
            active_branch = repo["active_branch"]
            active_workspace = await self._get_workspace_row(conn, repo["id"], active_branch)
            active_ref = await self._get_ref_row(conn, repo["id"], active_branch)
            hidden_bank_id = self._hidden_workspace_bank_id(str(repo["id"]), branch_name)
            if from_commit_id:
                snapshot = await self._load_commit_snapshot(conn, from_commit_id)
                head_commit_id = uuid.UUID(from_commit_id)
            else:
                snapshot = await self.capture_bank_snapshot(active_workspace["workspace_bank_id"])
                head_commit_id = active_ref["head_commit_id"]

            await self._restore_snapshot_db_only(
                conn,
                target_bank_id=hidden_bank_id,
                snapshot=snapshot,
                internal_workspace=True,
                root_bank_id=repo["root_bank_id"],
                branch_name=branch_name,
            )
            await self._store_snapshot_files(snapshot)
            await conn.execute(
                f"""
                INSERT INTO {_fq_table("memory_refs")} (repo_id, ref_type, ref_name, head_commit_id)
                VALUES ($1, 'branch', $2, $3)
                """,
                repo["id"],
                branch_name,
                head_commit_id,
            )
            await conn.execute(
                f"""
                INSERT INTO {_fq_table("memory_workspaces")} (repo_id, branch_name, workspace_bank_id, head_commit_id, is_active)
                VALUES ($1, $2, $3, $4, false)
                """,
                repo["id"],
                branch_name,
                hidden_bank_id,
                head_commit_id,
            )
            return {
                "repo_id": str(repo["id"]),
                "branch_name": branch_name,
                "workspace_bank_id": hidden_bank_id,
                "head_commit_id": str(head_commit_id) if head_commit_id else None,
            }

    async def checkout(self, repo_id: str, *, branch_name: str) -> dict[str, Any]:
        pool = await self._engine._get_pool()
        async with acquire_with_retry(pool) as conn:
            repo = await self._get_repo_row(conn, repo_id)
            if repo["active_branch"] == branch_name:
                return await self._repo_summary(conn, repo)
            current_branch = repo["active_branch"]
            current_workspace = await self._get_workspace_row(conn, repo["id"], current_branch)
            target_workspace = await self._get_workspace_row(conn, repo["id"], branch_name)
            current_snapshot = await self.capture_bank_snapshot(repo["root_bank_id"])
            current_hidden_bank = self._hidden_workspace_bank_id(str(repo["id"]), current_branch)
            await self._restore_snapshot_db_only(
                conn,
                target_bank_id=current_hidden_bank,
                snapshot=current_snapshot,
                internal_workspace=True,
                root_bank_id=repo["root_bank_id"],
                branch_name=current_branch,
            )
            target_snapshot = await self.capture_bank_snapshot(target_workspace["workspace_bank_id"])
            await self._restore_snapshot_db_only(
                conn,
                target_bank_id=repo["root_bank_id"],
                snapshot=target_snapshot,
                internal_workspace=False,
                root_bank_id=repo["root_bank_id"],
                branch_name=branch_name,
            )
            await self._store_snapshot_files(current_snapshot)
            await self._store_snapshot_files(target_snapshot)
            await conn.execute(
                f"UPDATE {_fq_table('memory_workspaces')} SET is_active = false, updated_at = NOW() WHERE repo_id = $1",
                repo["id"],
            )
            await conn.execute(
                f"""
                UPDATE {_fq_table("memory_workspaces")}
                SET workspace_bank_id = $3, updated_at = NOW()
                WHERE repo_id = $1 AND branch_name = $2
                """,
                repo["id"],
                current_branch,
                current_hidden_bank,
            )
            await conn.execute(
                f"""
                UPDATE {_fq_table("memory_workspaces")}
                SET workspace_bank_id = $3, is_active = true, updated_at = NOW()
                WHERE repo_id = $1 AND branch_name = $2
                """,
                repo["id"],
                branch_name,
                repo["root_bank_id"],
            )
            await conn.execute(
                f"""
                UPDATE {_fq_table("memory_repos")}
                SET active_branch = $2, updated_at = NOW()
                WHERE id = $1
                """,
                repo["id"],
                branch_name,
            )
            return await self._repo_summary(conn, await self._get_repo_row(conn, repo_id))

    async def commit(self, repo_id: str, *, message: str, actor: str | None = None) -> dict[str, Any]:
        pool = await self._engine._get_pool()
        async with acquire_with_retry(pool) as conn:
            repo = await self._get_repo_row(conn, repo_id)
            ref = await self._get_ref_row(conn, repo["id"], repo["active_branch"])
            snapshot = await self.capture_bank_snapshot(repo["root_bank_id"])
            manifest_hash, stats = await self._persist_snapshot(conn, bank_id=repo["root_bank_id"], snapshot=snapshot)
            if ref["head_commit_id"]:
                head_snapshot = await self._load_commit_snapshot(conn, str(ref["head_commit_id"]))
                if self._snapshot_hash(snapshot) == self._snapshot_hash(head_snapshot):
                    commit_row = await conn.fetchrow(
                        f"SELECT * FROM {_fq_table('memory_commits')} WHERE id = $1",
                        ref["head_commit_id"],
                    )
                    return self._commit_row_to_dict(commit_row)
            commit_id = uuid.uuid4()
            await conn.execute(
                f"""
                INSERT INTO {_fq_table("memory_commits")}
                    (id, repo_id, parent_commit_id, branch_name, message, actor, root_manifest_hash, stats)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                """,
                commit_id,
                repo["id"],
                ref["head_commit_id"],
                repo["active_branch"],
                message,
                actor or "anonymous",
                manifest_hash,
                json.dumps(stats),
            )
            await conn.execute(
                f"""
                UPDATE {_fq_table("memory_refs")}
                SET head_commit_id = $3, updated_at = NOW()
                WHERE repo_id = $1 AND ref_type = 'branch' AND ref_name = $2
                """,
                repo["id"],
                repo["active_branch"],
                commit_id,
            )
            await conn.execute(
                f"""
                UPDATE {_fq_table("memory_workspaces")}
                SET head_commit_id = $3, updated_at = NOW()
                WHERE repo_id = $1 AND branch_name = $2
                """,
                repo["id"],
                repo["active_branch"],
                commit_id,
            )
            await conn.execute(
                f"UPDATE {_fq_table('memory_repos')} SET updated_at = NOW() WHERE id = $1",
                repo["id"],
            )
            row = await conn.fetchrow(f"SELECT * FROM {_fq_table('memory_commits')} WHERE id = $1", commit_id)
            return self._commit_row_to_dict(row)

    async def get_status(self, repo_id: str, *, branch_name: str | None = None) -> dict[str, Any]:
        pool = await self._engine._get_pool()
        async with acquire_with_retry(pool) as conn:
            repo = await self._get_repo_row(conn, repo_id)
            branch = branch_name or repo["active_branch"]
            ref = await self._get_ref_row(conn, repo["id"], branch)
            workspace = await self._get_workspace_row(conn, repo["id"], branch)
            snapshot = self._normalize_snapshot_for_diff(
                await self.capture_bank_snapshot(workspace["workspace_bank_id"])
            )
            head_snapshot = (
                await self._load_commit_snapshot(conn, str(ref["head_commit_id"])) if ref["head_commit_id"] else None
            )
            diff = self._diff_snapshots(head_snapshot, snapshot)
            return {
                "repo_id": str(repo["id"]),
                "branch_name": branch,
                "workspace_bank_id": workspace["workspace_bank_id"],
                "head_commit_id": str(ref["head_commit_id"]) if ref["head_commit_id"] else None,
                "dirty": diff["dirty"],
                "changed_components": diff["changed_components"],
                "table_deltas": diff["table_deltas"],
            }

    async def get_log(self, repo_id: str, *, branch_name: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        pool = await self._engine._get_pool()
        async with acquire_with_retry(pool) as conn:
            repo = await self._get_repo_row(conn, repo_id)
            ref = await self._get_ref_row(conn, repo["id"], branch_name or repo["active_branch"])
            items: list[dict[str, Any]] = []
            commit_id = ref["head_commit_id"]
            remaining = max(1, min(limit, 200))
            while commit_id and remaining > 0:
                row = await conn.fetchrow(f"SELECT * FROM {_fq_table('memory_commits')} WHERE id = $1", commit_id)
                if not row:
                    break
                items.append(self._commit_row_to_dict(row))
                commit_id = row["parent_commit_id"]
                remaining -= 1
            return items

    async def diff(
        self,
        repo_id: str,
        *,
        from_commit_id: str | None = None,
        to_commit_id: str | None = None,
        from_branch: str | None = None,
        to_branch: str | None = None,
        include_workspace: bool = False,
    ) -> dict[str, Any]:
        pool = await self._engine._get_pool()
        async with acquire_with_retry(pool) as conn:
            repo = await self._get_repo_row(conn, repo_id)
            left = await self._resolve_diff_snapshot(
                conn,
                repo_id=str(repo["id"]),
                active_branch=repo["active_branch"],
                commit_id=from_commit_id,
                branch_name=from_branch,
                include_workspace=include_workspace and not to_commit_id and not to_branch,
            )
            right = await self._resolve_diff_snapshot(
                conn,
                repo_id=str(repo["id"]),
                active_branch=repo["active_branch"],
                commit_id=to_commit_id,
                branch_name=to_branch,
                include_workspace=include_workspace and bool(to_commit_id or to_branch),
            )
            diff = self._diff_snapshots(left["snapshot"], right["snapshot"])
            return {
                "repo_id": str(repo["id"]),
                "from_ref": left["label"],
                "to_ref": right["label"],
                **diff,
            }

    async def reset_hard(self, repo_id: str, *, commit_id: str, force: bool = False) -> dict[str, Any]:
        status = await self.get_status(repo_id)
        if status["dirty"] and not force:
            raise ValueError("Workspace is dirty. Commit changes first or pass force=true.")
        pool = await self._engine._get_pool()
        async with acquire_with_retry(pool) as conn:
            repo = await self._get_repo_row(conn, repo_id)
            snapshot = await self._load_commit_snapshot(conn, commit_id)
            await self._restore_snapshot_db_only(
                conn,
                target_bank_id=repo["root_bank_id"],
                snapshot=snapshot,
                internal_workspace=False,
                root_bank_id=repo["root_bank_id"],
                branch_name=repo["active_branch"],
            )
            await self._store_snapshot_files(snapshot)
            await conn.execute(
                f"""
                UPDATE {_fq_table("memory_refs")}
                SET head_commit_id = $3, updated_at = NOW()
                WHERE repo_id = $1 AND ref_type = 'branch' AND ref_name = $2
                """,
                repo["id"],
                repo["active_branch"],
                uuid.UUID(commit_id),
            )
            await conn.execute(
                f"""
                UPDATE {_fq_table("memory_workspaces")}
                SET head_commit_id = $3, updated_at = NOW()
                WHERE repo_id = $1 AND branch_name = $2
                """,
                repo["id"],
                repo["active_branch"],
                uuid.UUID(commit_id),
            )
            return await self.get_status(repo_id)

    async def cleanup_repo_for_bank(self, conn: "asyncpg.Connection", bank_id: str) -> list[str]:
        repo = await conn.fetchrow(
            f"SELECT * FROM {_fq_table('memory_repos')} WHERE root_bank_id = $1",
            bank_id,
        )
        if not repo:
            return []
        workspace_rows = await conn.fetch(
            f"SELECT workspace_bank_id, branch_name FROM {_fq_table('memory_workspaces')} WHERE repo_id = $1",
            repo["id"],
        )
        hidden_banks = [row["workspace_bank_id"] for row in workspace_rows if row["workspace_bank_id"] != bank_id]
        await conn.execute(f"DELETE FROM {_fq_table('memory_repos')} WHERE id = $1", repo["id"])
        return hidden_banks

    async def capture_bank_snapshot(self, bank_id: str) -> dict[str, Any]:
        pool = await self._engine._get_pool()
        async with acquire_with_retry(pool) as conn:
            components: dict[str, Any] = {}
            stats: dict[str, int] = {}
            for component, tables in _COMPONENT_TABLES.items():
                table_payloads: dict[str, list[dict[str, Any]]] = {}
                for table in tables:
                    rows = await self._select_bank_rows(conn, table, bank_id)
                    table_payloads[table] = rows
                    stats[table] = len(rows)
                components[component] = {"tables": table_payloads}
            files = await self._capture_storage_files(conn, bank_id)
            components["stored_files"] = {"files": files}
            stats["stored_files"] = len(files)
            return {"source_bank_id": bank_id, "components": components, "stats": stats}

    async def restore_snapshot_to_bank(
        self,
        bank_id: str,
        snapshot: dict[str, Any],
        *,
        internal_workspace: bool,
        root_bank_id: str,
        branch_name: str,
    ) -> None:
        pool = await self._engine._get_pool()
        async with acquire_with_retry(pool) as conn:
            await self._restore_snapshot_db_only(
                conn,
                target_bank_id=bank_id,
                snapshot=snapshot,
                internal_workspace=internal_workspace,
                root_bank_id=root_bank_id,
                branch_name=branch_name,
            )
        await self._store_snapshot_files(snapshot)

    async def _persist_snapshot(
        self,
        conn: "asyncpg.Connection",
        *,
        bank_id: str,
        snapshot: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        component_hashes: dict[str, str] = {}
        for component_name, payload in snapshot["components"].items():
            object_hash = self._hash_payload(payload)
            component_hashes[component_name] = object_hash
            await conn.execute(
                f"""
                INSERT INTO {_fq_table("memory_objects")} (object_hash, object_kind, payload, size_bytes)
                VALUES ($1, $2, $3::jsonb, $4)
                ON CONFLICT (object_hash) DO NOTHING
                """,
                object_hash,
                component_name,
                json.dumps(payload, sort_keys=True),
                len(json.dumps(payload, sort_keys=True).encode("utf-8")),
            )
        manifest = {
            "source_bank_id": bank_id,
            "component_hashes": component_hashes,
            "stats": snapshot["stats"],
        }
        manifest_hash = self._hash_payload(manifest)
        await conn.execute(
            f"""
            INSERT INTO {_fq_table("memory_objects")} (object_hash, object_kind, payload, size_bytes)
            VALUES ($1, 'manifest', $2::jsonb, $3)
            ON CONFLICT (object_hash) DO NOTHING
            """,
            manifest_hash,
            json.dumps(manifest, sort_keys=True),
            len(json.dumps(manifest, sort_keys=True).encode("utf-8")),
        )
        return manifest_hash, snapshot["stats"]

    async def _resolve_diff_snapshot(
        self,
        conn: "asyncpg.Connection",
        *,
        repo_id: str,
        active_branch: str,
        commit_id: str | None,
        branch_name: str | None,
        include_workspace: bool,
    ) -> dict[str, Any]:
        if commit_id:
            return {"label": f"commit:{commit_id}", "snapshot": await self._load_commit_snapshot(conn, commit_id)}
        if branch_name:
            ref = await self._get_ref_row(conn, uuid.UUID(repo_id), branch_name)
            if include_workspace:
                workspace = await self._get_workspace_row(conn, uuid.UUID(repo_id), branch_name)
                return {
                    "label": f"workspace:{branch_name}",
                    "snapshot": self._normalize_snapshot_for_diff(
                        await self.capture_bank_snapshot(workspace["workspace_bank_id"])
                    ),
                }
            if not ref["head_commit_id"]:
                return {"label": f"branch:{branch_name}", "snapshot": None}
            return {
                "label": f"branch:{branch_name}",
                "snapshot": await self._load_commit_snapshot(conn, str(ref["head_commit_id"])),
            }
        if include_workspace:
            workspace = await self._get_workspace_row(conn, uuid.UUID(repo_id), active_branch)
            return {
                "label": f"workspace:{active_branch}",
                "snapshot": self._normalize_snapshot_for_diff(
                    await self.capture_bank_snapshot(workspace["workspace_bank_id"])
                ),
            }
        ref = await self._get_ref_row(conn, uuid.UUID(repo_id), active_branch)
        if not ref["head_commit_id"]:
            return {"label": f"branch:{active_branch}", "snapshot": None}
        return {
            "label": f"branch:{active_branch}",
            "snapshot": await self._load_commit_snapshot(conn, str(ref["head_commit_id"])),
        }

    async def _load_commit_snapshot(self, conn: "asyncpg.Connection", commit_id: str) -> dict[str, Any]:
        commit = await conn.fetchrow(
            f"SELECT root_manifest_hash FROM {_fq_table('memory_commits')} WHERE id = $1", uuid.UUID(commit_id)
        )
        if not commit:
            raise ValueError(f"Commit not found: {commit_id}")
        manifest_row = await conn.fetchrow(
            f"SELECT payload FROM {_fq_table('memory_objects')} WHERE object_hash = $1",
            commit["root_manifest_hash"],
        )
        manifest = self._decode_json_field(manifest_row["payload"])
        components: dict[str, Any] = {}
        for component_name, object_hash in manifest["component_hashes"].items():
            object_row = await conn.fetchrow(
                f"SELECT payload FROM {_fq_table('memory_objects')} WHERE object_hash = $1",
                object_hash,
            )
            components[component_name] = self._decode_json_field(object_row["payload"])
        return {"source_bank_id": manifest["source_bank_id"], "components": components, "stats": manifest["stats"]}

    async def _repo_summary(self, conn: "asyncpg.Connection", repo_row) -> dict[str, Any]:
        repo = self._repo_row_to_dict(repo_row)
        repo["branches"] = await self.list_branches(str(repo_row["id"]))
        return repo

    async def _get_repo_row(self, conn: "asyncpg.Connection", repo_id: str):
        row = await conn.fetchrow(f"SELECT * FROM {_fq_table('memory_repos')} WHERE id = $1", uuid.UUID(repo_id))
        if not row:
            raise ValueError(f"Repo not found: {repo_id}")
        return row

    async def _get_repo_summary_row(self, conn: "asyncpg.Connection", repo_id: str):
        row = await conn.fetchrow(
            f"""
            SELECT r.id, r.root_bank_id, r.name, r.active_branch, r.created_at, r.updated_at,
                   mr.head_commit_id,
                   mc.message AS head_message,
                   mc.created_at AS head_created_at
            FROM {_fq_table("memory_repos")} r
            LEFT JOIN {_fq_table("memory_refs")} mr
              ON mr.repo_id = r.id AND mr.ref_type = 'branch' AND mr.ref_name = r.active_branch
            LEFT JOIN {_fq_table("memory_commits")} mc
              ON mc.id = mr.head_commit_id
            WHERE r.id = $1
            """,
            uuid.UUID(repo_id),
        )
        if not row:
            raise ValueError(f"Repo not found: {repo_id}")
        return row

    async def _get_repo_summary_row_by_root_bank(self, conn: "asyncpg.Connection", bank_id: str):
        return await conn.fetchrow(
            f"""
            SELECT r.id, r.root_bank_id, r.name, r.active_branch, r.created_at, r.updated_at,
                   mr.head_commit_id,
                   mc.message AS head_message,
                   mc.created_at AS head_created_at
            FROM {_fq_table("memory_repos")} r
            LEFT JOIN {_fq_table("memory_refs")} mr
              ON mr.repo_id = r.id AND mr.ref_type = 'branch' AND mr.ref_name = r.active_branch
            LEFT JOIN {_fq_table("memory_commits")} mc
              ON mc.id = mr.head_commit_id
            WHERE r.root_bank_id = $1
            """,
            bank_id,
        )

    async def _get_ref_row(self, conn: "asyncpg.Connection", repo_id: uuid.UUID, branch_name: str):
        row = await conn.fetchrow(
            f"""
            SELECT * FROM {_fq_table("memory_refs")}
            WHERE repo_id = $1 AND ref_type = 'branch' AND ref_name = $2
            """,
            repo_id,
            branch_name,
        )
        if not row:
            raise ValueError(f"Branch not found: {branch_name}")
        return row

    async def _get_workspace_row(self, conn: "asyncpg.Connection", repo_id: uuid.UUID, branch_name: str):
        row = await conn.fetchrow(
            f"""
            SELECT * FROM {_fq_table("memory_workspaces")}
            WHERE repo_id = $1 AND branch_name = $2
            """,
            repo_id,
            branch_name,
        )
        if not row:
            raise ValueError(f"Workspace not found for branch: {branch_name}")
        return row

    async def _ensure_branch_absent(self, conn: "asyncpg.Connection", repo_id: uuid.UUID, branch_name: str) -> None:
        row = await conn.fetchrow(
            f"""
            SELECT 1 FROM {_fq_table("memory_refs")}
            WHERE repo_id = $1 AND ref_type = 'branch' AND ref_name = $2
            """,
            repo_id,
            branch_name,
        )
        if row:
            raise ValueError(f"Branch already exists: {branch_name}")

    async def _select_bank_rows(self, conn: "asyncpg.Connection", table: str, bank_id: str) -> list[dict[str, Any]]:
        columns = await self._get_columns(conn, table)
        column_list = ", ".join(column["column_name"] for column in columns)
        if table in _DIRECT_BANK_TABLES:
            if table == "banks":
                rows = await conn.fetch(f"SELECT {column_list} FROM {_fq_table(table)} WHERE bank_id = $1", bank_id)
            else:
                rows = await conn.fetch(f"SELECT {column_list} FROM {_fq_table(table)} WHERE bank_id = $1", bank_id)
        elif table == "unit_entities":
            rows = await conn.fetch(
                f"""
                SELECT {", ".join(f"ue.{column['column_name']}" for column in columns)}
                FROM {_fq_table("unit_entities")} ue
                JOIN {_fq_table("memory_units")} mu ON mu.id = ue.unit_id
                WHERE mu.bank_id = $1
                """,
                bank_id,
            )
        elif table == "entity_cooccurrences":
            rows = await conn.fetch(
                f"""
                SELECT {", ".join(f"ec.{column['column_name']}" for column in columns)}
                FROM {_fq_table("entity_cooccurrences")} ec
                JOIN {_fq_table("entities")} e ON e.id = ec.entity_id_1
                WHERE e.bank_id = $1
                """,
                bank_id,
            )
        elif table == "memory_links":
            rows = await conn.fetch(
                f"""
                SELECT {", ".join(f"ml.{column['column_name']}" for column in columns)}
                FROM {_fq_table("memory_links")} ml
                JOIN {_fq_table("memory_units")} mu ON mu.id = ml.from_unit_id
                WHERE mu.bank_id = $1
                """,
                bank_id,
            )
        else:
            raise ValueError(f"Unsupported snapshot table: {table}")
        return self._normalize_rows(rows, columns)

    async def _capture_storage_files(self, conn: "asyncpg.Connection", bank_id: str) -> list[dict[str, Any]]:
        keys = set()
        document_rows = await conn.fetch(
            f"SELECT file_storage_key FROM {_fq_table('documents')} WHERE bank_id = $1 AND file_storage_key IS NOT NULL",
            bank_id,
        )
        for row in document_rows:
            keys.add(row["file_storage_key"])
        snapshot_rows = await conn.fetch(
            f"""
            SELECT source_archive_storage_key
            FROM {_fq_table("codebase_snapshots")}
            WHERE bank_id = $1 AND source_archive_storage_key IS NOT NULL
            """,
            bank_id,
        )
        for row in snapshot_rows:
            keys.add(row["source_archive_storage_key"])
        files: list[dict[str, Any]] = []
        for key in sorted(keys):
            try:
                data = await self._engine._file_storage.retrieve(key)
            except FileNotFoundError:
                logger.warning("[MEMORY_REPO] Missing storage key during snapshot: %s", key)
                continue
            files.append({"storage_key": key, "data": self._encode_bytes(data)})
        return files

    async def _restore_snapshot_db_only(
        self,
        conn: "asyncpg.Connection",
        *,
        target_bank_id: str,
        snapshot: dict[str, Any],
        internal_workspace: bool,
        root_bank_id: str,
        branch_name: str,
    ) -> None:
        await self._delete_bank_contents(conn, target_bank_id)
        table_payloads: dict[str, list[dict[str, Any]]] = {}
        for component in snapshot["components"].values():
            if "tables" not in component:
                continue
            for table, rows in component["tables"].items():
                table_payloads[table] = rows
        restore_id_maps = self._build_restore_id_maps(
            table_payloads=table_payloads,
            target_bank_id=target_bank_id,
            source_bank_id=str(snapshot.get("source_bank_id") or ""),
        )
        for table in _RESTORE_ORDER:
            for row in table_payloads.get(table, []):
                transformed = self._remap_row(
                    table,
                    row,
                    restore_id_maps=restore_id_maps,
                    target_bank_id=target_bank_id,
                    internal_workspace=internal_workspace,
                    root_bank_id=root_bank_id,
                    branch_name=branch_name,
                )
                await self._insert_row(conn, table, transformed)

    async def _delete_bank_contents(self, conn: "asyncpg.Connection", bank_id: str) -> None:
        await conn.execute(f"DELETE FROM {_fq_table('documents')} WHERE bank_id = $1", bank_id)
        await conn.execute(f"DELETE FROM {_fq_table('memory_units')} WHERE bank_id = $1", bank_id)
        await conn.execute(f"DELETE FROM {_fq_table('entities')} WHERE bank_id = $1", bank_id)
        await conn.execute(f"DELETE FROM {_fq_table('async_operations')} WHERE bank_id = $1", bank_id)
        for table in (
            "codebases",
            "entity_trajectories",
            "entity_intelligence",
            "directives",
            "mental_models",
            "webhooks",
        ):
            await conn.execute(f"DELETE FROM {_fq_table(table)} WHERE bank_id = $1", bank_id)
        await conn.execute(f"DELETE FROM {_fq_table('banks')} WHERE bank_id = $1", bank_id)

    async def _insert_row(self, conn: "asyncpg.Connection", table: str, row: dict[str, Any]) -> None:
        columns = await self._get_columns(conn, table)
        selected = [column for column in columns if column["column_name"] in row]
        if not selected:
            return
        column_names: list[str] = []
        placeholders: list[str] = []
        params: list[Any] = []
        for column in selected:
            param_value, cast_sql = self._prepare_insert_value(column, row[column["column_name"]])
            params.append(param_value)
            column_names.append(column["column_name"])
            placeholders.append(f"${len(params)}{cast_sql}")
        await conn.execute(
            f"""
            INSERT INTO {_fq_table(table)} ({", ".join(column_names)})
            VALUES ({", ".join(placeholders)})
            """,
            *params,
        )

    async def _store_snapshot_files(self, snapshot: dict[str, Any]) -> None:
        for item in snapshot["components"].get("stored_files", {}).get("files", []):
            await self._engine._file_storage.store(self._decode_bytes(item["data"]), item["storage_key"])

    async def _get_columns(self, conn: "asyncpg.Connection", table: str) -> list[dict[str, str]]:
        from .memory_engine import get_current_schema

        schema = get_current_schema()
        cache_key = (schema, table)
        if cache_key in self._column_cache:
            return self._column_cache[cache_key]
        rows = await conn.fetch(
            """
            SELECT column_name, data_type, udt_name, is_generated
            FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            ORDER BY ordinal_position
            """,
            schema,
            table,
        )
        result = [
            {
                "column_name": row["column_name"],
                "data_type": row["data_type"],
                "udt_name": row["udt_name"],
                "is_generated": row["is_generated"],
            }
            for row in rows
            if row["is_generated"] == "NEVER"
        ]
        self._column_cache[cache_key] = result
        return result

    def _normalize_rows(self, rows, columns: list[dict[str, str]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for row in rows:
            item: dict[str, Any] = {}
            for column in columns:
                name = column["column_name"]
                value = row[name]
                if column["data_type"] in {"json", "jsonb"}:
                    value = self._decode_json_field(value)
                item[name] = self._serialize_value(value)
            normalized.append(item)
        normalized.sort(key=lambda item: json.dumps(item, sort_keys=True))
        return normalized

    def _remap_row(
        self,
        table: str,
        row: dict[str, Any],
        *,
        restore_id_maps: RestoreIdMaps,
        target_bank_id: str,
        internal_workspace: bool,
        root_bank_id: str,
        branch_name: str,
    ) -> dict[str, Any]:
        transformed = json.loads(json.dumps(row))
        if "bank_id" in transformed:
            transformed["bank_id"] = target_bank_id
        if restore_id_maps.remap_enabled:
            if table == "chunks":
                transformed["chunk_id"] = self._remap_value(restore_id_maps.chunk_ids, row.get("chunk_id"))
            elif table == "entities":
                transformed["id"] = self._remap_value(restore_id_maps.entity_ids, row.get("id"))
            elif table == "memory_units":
                transformed["id"] = self._remap_value(restore_id_maps.unit_ids, row.get("id"))
                transformed["chunk_id"] = self._remap_value(restore_id_maps.chunk_ids, row.get("chunk_id"))
                if isinstance(transformed.get("source_memory_ids"), list):
                    transformed["source_memory_ids"] = [
                        self._remap_value(restore_id_maps.unit_ids, value) for value in transformed["source_memory_ids"]
                    ]
            elif table == "unit_entities":
                transformed["unit_id"] = self._remap_value(restore_id_maps.unit_ids, row.get("unit_id"))
                transformed["entity_id"] = self._remap_value(restore_id_maps.entity_ids, row.get("entity_id"))
            elif table == "entity_cooccurrences":
                mapped_left = self._remap_value(restore_id_maps.entity_ids, row.get("entity_id_1"))
                mapped_right = self._remap_value(restore_id_maps.entity_ids, row.get("entity_id_2"))
                if mapped_left and mapped_right and mapped_left > mapped_right:
                    mapped_left, mapped_right = mapped_right, mapped_left
                transformed["entity_id_1"] = mapped_left
                transformed["entity_id_2"] = mapped_right
            elif table == "memory_links":
                transformed["from_unit_id"] = self._remap_value(restore_id_maps.unit_ids, row.get("from_unit_id"))
                transformed["to_unit_id"] = self._remap_value(restore_id_maps.unit_ids, row.get("to_unit_id"))
                transformed["entity_id"] = self._remap_value(restore_id_maps.entity_ids, row.get("entity_id"))
            elif table == "entity_trajectories":
                transformed["id"] = self._remap_value(restore_id_maps.entity_trajectory_ids, row.get("id"))
                transformed["entity_id"] = self._remap_value(restore_id_maps.entity_ids, row.get("entity_id"))
            elif table == "entity_intelligence":
                transformed["id"] = self._remap_value(restore_id_maps.entity_intelligence_ids, row.get("id"))
            elif table == "directives":
                transformed["id"] = self._remap_value(restore_id_maps.directive_ids, row.get("id"))
            elif table == "webhooks":
                transformed["id"] = self._remap_value(restore_id_maps.webhook_ids, row.get("id"))
            elif table == "codebases":
                transformed["id"] = self._remap_value(restore_id_maps.codebase_ids, row.get("id"))
                transformed["current_snapshot_id"] = self._remap_value(
                    restore_id_maps.codebase_snapshot_ids, row.get("current_snapshot_id")
                )
                transformed["approved_snapshot_id"] = self._remap_value(
                    restore_id_maps.codebase_snapshot_ids, row.get("approved_snapshot_id")
                )
            elif table == "codebase_snapshots":
                transformed["id"] = self._remap_value(restore_id_maps.codebase_snapshot_ids, row.get("id"))
                transformed["codebase_id"] = self._remap_value(restore_id_maps.codebase_ids, row.get("codebase_id"))
            elif table == "codebase_files":
                transformed["id"] = self._remap_value(restore_id_maps.codebase_file_ids, row.get("id"))
                transformed["codebase_id"] = self._remap_value(restore_id_maps.codebase_ids, row.get("codebase_id"))
                transformed["snapshot_id"] = self._remap_value(
                    restore_id_maps.codebase_snapshot_ids, row.get("snapshot_id")
                )
            elif table == "codebase_symbols":
                transformed["id"] = self._remap_value(restore_id_maps.codebase_symbol_ids, row.get("id"))
                transformed["codebase_id"] = self._remap_value(restore_id_maps.codebase_ids, row.get("codebase_id"))
                transformed["snapshot_id"] = self._remap_value(
                    restore_id_maps.codebase_snapshot_ids, row.get("snapshot_id")
                )
            elif table == "codebase_edges":
                transformed["id"] = self._remap_value(restore_id_maps.codebase_edge_ids, row.get("id"))
                transformed["codebase_id"] = self._remap_value(restore_id_maps.codebase_ids, row.get("codebase_id"))
                transformed["snapshot_id"] = self._remap_value(
                    restore_id_maps.codebase_snapshot_ids, row.get("snapshot_id")
                )
            elif table == "codebase_chunks":
                transformed["id"] = self._remap_value(restore_id_maps.codebase_chunk_ids, row.get("id"))
                transformed["codebase_id"] = self._remap_value(restore_id_maps.codebase_ids, row.get("codebase_id"))
                transformed["snapshot_id"] = self._remap_value(
                    restore_id_maps.codebase_snapshot_ids, row.get("snapshot_id")
                )
            elif table == "codebase_chunk_edges":
                transformed["id"] = self._remap_value(restore_id_maps.codebase_chunk_edge_ids, row.get("id"))
                transformed["codebase_id"] = self._remap_value(restore_id_maps.codebase_ids, row.get("codebase_id"))
                transformed["snapshot_id"] = self._remap_value(
                    restore_id_maps.codebase_snapshot_ids, row.get("snapshot_id")
                )
                transformed["from_chunk_id"] = self._remap_value(
                    restore_id_maps.codebase_chunk_ids, row.get("from_chunk_id")
                )
                transformed["to_chunk_id"] = self._remap_value(
                    restore_id_maps.codebase_chunk_ids, row.get("to_chunk_id")
                )
            elif table == "codebase_review_routes":
                transformed["id"] = self._remap_value(restore_id_maps.codebase_review_route_ids, row.get("id"))
                transformed["codebase_id"] = self._remap_value(restore_id_maps.codebase_ids, row.get("codebase_id"))
                transformed["snapshot_id"] = self._remap_value(
                    restore_id_maps.codebase_snapshot_ids, row.get("snapshot_id")
                )
                transformed["chunk_id"] = self._remap_value(restore_id_maps.codebase_chunk_ids, row.get("chunk_id"))
            elif table == "codebase_intel_artifacts":
                transformed["id"] = self._remap_value(restore_id_maps.codebase_intel_artifact_ids, row.get("id"))
                transformed["codebase_id"] = self._remap_value(restore_id_maps.codebase_ids, row.get("codebase_id"))
                transformed["snapshot_id"] = self._remap_value(
                    restore_id_maps.codebase_snapshot_ids, row.get("snapshot_id")
                )
            elif table == "codebase_auto_triage_overrides":
                transformed["id"] = self._remap_value(restore_id_maps.codebase_auto_triage_override_ids, row.get("id"))
                transformed["codebase_id"] = self._remap_value(restore_id_maps.codebase_ids, row.get("codebase_id"))
                transformed["snapshot_id"] = self._remap_value(
                    restore_id_maps.codebase_snapshot_ids, row.get("snapshot_id")
                )
                transformed["chunk_id"] = self._remap_value(restore_id_maps.codebase_chunk_ids, row.get("chunk_id"))
            elif table == "codebase_saved_intents":
                transformed["id"] = self._remap_value(restore_id_maps.codebase_saved_intent_ids, row.get("id"))
                transformed["codebase_id"] = self._remap_value(restore_id_maps.codebase_ids, row.get("codebase_id"))
        if table == "banks":
            config = transformed.get("config") or {}
            if internal_workspace:
                config["memory_repo_internal_workspace"] = True
                config["memory_repo_root_bank_id"] = root_bank_id
                config["memory_repo_branch_name"] = branch_name
                config["memory_repo_origin_id_maps"] = self._invert_restore_id_maps(restore_id_maps)
            else:
                config.pop("memory_repo_internal_workspace", None)
                config.pop("memory_repo_root_bank_id", None)
                config.pop("memory_repo_branch_name", None)
                config.pop("memory_repo_origin_id_maps", None)
            transformed["config"] = config
        return transformed

    def _build_restore_id_maps(
        self,
        *,
        table_payloads: dict[str, list[dict[str, Any]]],
        target_bank_id: str,
        source_bank_id: str,
    ) -> RestoreIdMaps:
        source_bank_config = self._snapshot_bank_config(table_payloads)
        origin_maps = source_bank_config.get("memory_repo_origin_id_maps")
        if isinstance(origin_maps, dict):
            return RestoreIdMaps(
                remap_enabled=True,
                **{field_name: dict(origin_maps.get(field_name) or {}) for field_name in _ORIGIN_ID_MAP_FIELDS},
            )
        if not source_bank_id or source_bank_id == target_bank_id:
            return RestoreIdMaps(remap_enabled=False)

        return RestoreIdMaps(
            remap_enabled=True,
            chunk_ids={
                str(row["chunk_id"]): f"{target_bank_id}_{row['document_id']}_{row['chunk_index']}"
                for row in table_payloads.get("chunks", [])
                if row.get("chunk_id") is not None
            },
            entity_ids=self._build_uuid_id_map(table_payloads.get("entities", []), "entities", target_bank_id),
            unit_ids=self._build_uuid_id_map(table_payloads.get("memory_units", []), "memory_units", target_bank_id),
            entity_trajectory_ids=self._build_uuid_id_map(
                table_payloads.get("entity_trajectories", []), "entity_trajectories", target_bank_id
            ),
            entity_intelligence_ids=self._build_uuid_id_map(
                table_payloads.get("entity_intelligence", []), "entity_intelligence", target_bank_id
            ),
            directive_ids=self._build_uuid_id_map(table_payloads.get("directives", []), "directives", target_bank_id),
            webhook_ids=self._build_uuid_id_map(table_payloads.get("webhooks", []), "webhooks", target_bank_id),
            codebase_ids=self._build_uuid_id_map(table_payloads.get("codebases", []), "codebases", target_bank_id),
            codebase_snapshot_ids=self._build_uuid_id_map(
                table_payloads.get("codebase_snapshots", []), "codebase_snapshots", target_bank_id
            ),
            codebase_file_ids=self._build_uuid_id_map(
                table_payloads.get("codebase_files", []), "codebase_files", target_bank_id
            ),
            codebase_symbol_ids=self._build_uuid_id_map(
                table_payloads.get("codebase_symbols", []), "codebase_symbols", target_bank_id
            ),
            codebase_edge_ids=self._build_uuid_id_map(
                table_payloads.get("codebase_edges", []), "codebase_edges", target_bank_id
            ),
            codebase_chunk_ids=self._build_uuid_id_map(
                table_payloads.get("codebase_chunks", []), "codebase_chunks", target_bank_id
            ),
            codebase_chunk_edge_ids=self._build_uuid_id_map(
                table_payloads.get("codebase_chunk_edges", []), "codebase_chunk_edges", target_bank_id
            ),
            codebase_review_route_ids=self._build_uuid_id_map(
                table_payloads.get("codebase_review_routes", []), "codebase_review_routes", target_bank_id
            ),
            codebase_intel_artifact_ids=self._build_uuid_id_map(
                table_payloads.get("codebase_intel_artifacts", []), "codebase_intel_artifacts", target_bank_id
            ),
            codebase_auto_triage_override_ids=self._build_uuid_id_map(
                table_payloads.get("codebase_auto_triage_overrides", []),
                "codebase_auto_triage_overrides",
                target_bank_id,
            ),
            codebase_saved_intent_ids=self._build_uuid_id_map(
                table_payloads.get("codebase_saved_intents", []), "codebase_saved_intents", target_bank_id
            ),
        )

    def _invert_restore_id_maps(self, restore_id_maps: RestoreIdMaps) -> dict[str, dict[str, str]]:
        if not restore_id_maps.remap_enabled:
            return {}
        result: dict[str, dict[str, str]] = {}
        for field_name in _ORIGIN_ID_MAP_FIELDS:
            mapping = getattr(restore_id_maps, field_name)
            if mapping:
                result[field_name] = {mapped: source for source, mapped in mapping.items()}
        return result

    def _snapshot_bank_config(self, table_payloads: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        bank_rows = table_payloads.get("banks") or []
        if not bank_rows:
            return {}
        config = bank_rows[0].get("config")
        return config if isinstance(config, dict) else {}

    def _normalize_snapshot_for_diff(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        components = snapshot.get("components") or {}
        bank_rows = components.get("profile_config", {}).get("tables", {}).get("banks", [])
        if not bank_rows:
            return snapshot
        bank_config = bank_rows[0].get("config")
        if not isinstance(bank_config, dict) or not bank_config.get("memory_repo_internal_workspace"):
            return snapshot

        root_bank_id = bank_config.get("memory_repo_root_bank_id")
        branch_name = bank_config.get("memory_repo_branch_name") or "main"
        if not isinstance(root_bank_id, str) or not root_bank_id:
            return snapshot

        table_payloads: dict[str, list[dict[str, Any]]] = {}
        for component in components.values():
            if "tables" not in component:
                continue
            for table, rows in component["tables"].items():
                table_payloads[table] = rows
        restore_id_maps = self._build_restore_id_maps(
            table_payloads=table_payloads,
            target_bank_id=root_bank_id,
            source_bank_id=str(snapshot.get("source_bank_id") or ""),
        )
        if not restore_id_maps.remap_enabled:
            return snapshot

        normalized_components: dict[str, Any] = {}
        for component_name, component in components.items():
            if "tables" not in component:
                normalized_components[component_name] = component
                continue
            normalized_tables: dict[str, list[dict[str, Any]]] = {}
            for table, rows in component["tables"].items():
                normalized_rows = [
                    self._remap_row(
                        table,
                        row,
                        restore_id_maps=restore_id_maps,
                        target_bank_id=root_bank_id,
                        internal_workspace=False,
                        root_bank_id=root_bank_id,
                        branch_name=branch_name,
                    )
                    for row in rows
                ]
                normalized_tables[table] = sorted(normalized_rows, key=lambda item: json.dumps(item, sort_keys=True))
            normalized_components[component_name] = {"tables": normalized_tables}
        return {
            "source_bank_id": root_bank_id,
            "components": normalized_components,
            "stats": snapshot.get("stats", {}),
        }

    def _build_uuid_id_map(
        self,
        rows: list[dict[str, Any]],
        table: str,
        target_bank_id: str,
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for row in rows:
            source_id = row.get("id")
            if source_id is None:
                continue
            source_id_text = str(source_id)
            result[source_id_text] = self._stable_workspace_uuid(
                target_bank_id=target_bank_id,
                table=table,
                source_id=source_id_text,
            )
        return result

    def _stable_workspace_uuid(self, *, target_bank_id: str, table: str, source_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"atulya-memory-repo:{target_bank_id}:{table}:{source_id}"))

    def _remap_value(self, mapping: dict[str, str], value: Any) -> Any:
        if value is None:
            return None
        return mapping.get(str(value), value)

    def _prepare_insert_value(self, column: dict[str, str], value: Any) -> tuple[Any, str]:
        if value is None:
            return None, ""
        data_type = column["data_type"]
        udt_name = column["udt_name"]
        if data_type in {"json", "jsonb"}:
            return json.dumps(value), "::jsonb" if data_type == "jsonb" else "::json"
        if data_type == "ARRAY":
            if udt_name == "_uuid":
                return [uuid.UUID(v) for v in value], "::uuid[]"
            if udt_name == "_text":
                return value, "::text[]"
            if udt_name == "_varchar":
                return value, "::varchar[]"
            if udt_name == "_bool":
                return value, "::boolean[]"
            if udt_name == "_int4":
                return value, "::integer[]"
            return value, ""
        if udt_name == "uuid":
            return uuid.UUID(value) if isinstance(value, str) else value, "::uuid"
        if udt_name == "vector":
            return self._serialize_vector_literal(value), "::vector"
        if data_type.startswith("timestamp"):
            return datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value, ""
        return self._deserialize_value(value), ""

    def _serialize_vector_literal(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, tuple):
            value = list(value)
        if isinstance(value, list):
            return "[" + ",".join(str(item) for item in value) + "]"
        return str(value)

    def _serialize_value(self, value: Any) -> Any:
        if isinstance(value, bytes):
            return self._encode_bytes(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, dict):
            return {str(key): self._serialize_value(val) for key, val in value.items()}
        if isinstance(value, list):
            return [self._serialize_value(item) for item in value]
        return value

    def _deserialize_value(self, value: Any) -> Any:
        if isinstance(value, dict) and "__memory_repo_bytes__" in value:
            return self._decode_bytes(value)
        if isinstance(value, list):
            return [self._deserialize_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._deserialize_value(item) for key, item in value.items()}
        return value

    def _decode_json_field(self, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    def _encode_bytes(self, value: bytes) -> dict[str, str]:
        return {"__memory_repo_bytes__": base64.b64encode(value).decode("ascii")}

    def _decode_bytes(self, value: dict[str, str]) -> bytes:
        return base64.b64decode(value["__memory_repo_bytes__"].encode("ascii"))

    def _hash_payload(self, payload: Any) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _snapshot_hash(self, snapshot: dict[str, Any] | None) -> str | None:
        if snapshot is None:
            return None
        return self._hash_payload(snapshot["components"])

    def _diff_snapshots(self, left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
        left_components = left["components"] if left else {}
        right_components = right["components"] if right else {}
        changed_components = [
            component
            for component in sorted(set(left_components) | set(right_components))
            if self._hash_payload(left_components.get(component)) != self._hash_payload(right_components.get(component))
        ]
        left_stats = left["stats"] if left else {}
        right_stats = right["stats"] if right else {}
        table_deltas: dict[str, dict[str, int]] = {}
        for table in sorted(set(left_stats) | set(right_stats)):
            before = int(left_stats.get(table, 0))
            after = int(right_stats.get(table, 0))
            if before != after:
                table_deltas[table] = {"before": before, "after": after, "delta": after - before}
        return {
            "dirty": bool(changed_components),
            "changed_components": changed_components,
            "table_deltas": table_deltas,
        }

    def _repo_row_to_dict(self, row) -> dict[str, Any]:
        return {
            "repo_id": str(row["id"]),
            "root_bank_id": row["root_bank_id"],
            "name": row["name"],
            "active_branch": row["active_branch"],
            "head_commit_id": str(row["head_commit_id"]) if "head_commit_id" in row and row["head_commit_id"] else None,
            "head_message": row["head_message"] if "head_message" in row else None,
            "head_created_at": row["head_created_at"].isoformat()
            if "head_created_at" in row and row["head_created_at"]
            else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    def _commit_row_to_dict(self, row) -> dict[str, Any]:
        return {
            "commit_id": str(row["id"]),
            "repo_id": str(row["repo_id"]),
            "parent_commit_id": str(row["parent_commit_id"]) if row["parent_commit_id"] else None,
            "branch_name": row["branch_name"],
            "message": row["message"],
            "actor": row["actor"],
            "root_manifest_hash": row["root_manifest_hash"],
            "stats": self._decode_json_field(row["stats"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }

    def _hidden_workspace_bank_id(self, repo_id: str, branch_name: str) -> str:
        digest = hashlib.sha1(branch_name.encode("utf-8")).hexdigest()[:12]
        return f"__repo__{repo_id[:8]}__{digest}"
