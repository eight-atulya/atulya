"""
Focused tests for ASD-first codebase import, review, approval, and query APIs.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone

import httpx
import pytest

from atulya_api.api import create_app


def _build_repo_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def _bank_id(suffix: str) -> str:
    return f"codebase_{suffix}_{datetime.now(timezone.utc).timestamp()}"


@pytest.mark.asyncio
async def test_codebase_zip_import_requires_approval_before_memory_hydration(
    memory_no_llm_verify, request_context
):
    bank_id = _bank_id("zip")
    archive_bytes = _build_repo_zip(
        {
            "demo-repo/src/util.py": "def helper():\n    return 'ok'\n",
            "demo-repo/src/main.py": "from src.util import helper\n\ndef run():\n    return helper()\n",
            "demo-repo/web/lib.ts": "export function thing() {\n  return 'hi';\n}\n",
            "demo-repo/web/app.ts": "import { thing } from './lib';\nexport function screen() {\n  return thing();\n}\n",
            "demo-repo/package.json": json.dumps({"name": "demo-repo", "private": True}),
            "demo-repo/dist/generated.js": "var bundled=true;",
        }
    )

    try:
        await memory_no_llm_verify.get_bank_profile(bank_id=bank_id, request_context=request_context)

        submit_result = await memory_no_llm_verify.submit_async_codebase_zip_import(
            bank_id=bank_id,
            name="demo-repo",
            archive_name="demo-repo.zip",
            archive_bytes=archive_bytes,
            request_context=request_context,
        )

        import_operation = await memory_no_llm_verify.get_operation_result(
            bank_id,
            submit_result["operation_id"],
            request_context=request_context,
        )
        assert import_operation["status"] == "completed"
        assert import_operation["result"]["snapshot_id"] == submit_result["snapshot_id"]
        assert import_operation["result"]["status"] == "review_required"

        codebase = await memory_no_llm_verify.get_codebase(
            bank_id,
            submit_result["codebase_id"],
            request_context=request_context,
        )
        assert codebase is not None
        assert codebase["current_snapshot_id"] == submit_result["snapshot_id"]
        assert codebase["approved_snapshot_id"] is None
        assert codebase["source_type"] == "zip"
        assert codebase["snapshot_status"] == "review_required"
        assert codebase["approval_status"] == "pending_approval"
        assert codebase["memory_status"] == "not_hydrated"
        assert codebase["stats"]["total_files"] == 6
        assert codebase["stats"]["indexed_files"] >= 4

        files_result = await memory_no_llm_verify.list_codebase_files(
            bank_id,
            submit_result["codebase_id"],
            request_context=request_context,
        )
        files_by_path = {item["path"]: item for item in files_result["items"]}
        assert files_result["snapshot_status"] == "review_required"
        assert files_by_path["src/main.py"]["status"] == "indexed"
        assert files_by_path["src/main.py"]["document_id"] is None
        assert files_by_path["dist/generated.js"]["status"] == "excluded"
        assert files_by_path["package.json"]["status"] == "retained"

        pre_approval_document = await memory_no_llm_verify.get_document(
            f"codebase:{submit_result['codebase_id']}:src/main.py",
            bank_id,
            request_context=request_context,
        )
        assert pre_approval_document is None

        symbols_result = await memory_no_llm_verify.search_codebase_symbols(
            bank_id,
            submit_result["codebase_id"],
            q="helper",
            request_context=request_context,
        )
        helper_matches = [item for item in symbols_result["items"] if item["name"] == "helper"]
        assert helper_matches
        assert helper_matches[0]["path"] == "src/util.py"

        impact_result = await memory_no_llm_verify.analyze_codebase_impact(
            bank_id,
            submit_result["codebase_id"],
            path="src/util.py",
            max_depth=2,
            limit=10,
            request_context=request_context,
        )
        impacted_paths = [item["path"] for item in impact_result["impacted_files"]]
        assert "src/util.py" in impacted_paths
        assert "src/main.py" in impacted_paths
        assert any(
            edge["from_path"] == "src/main.py" and edge["to_path"] == "src/util.py"
            for edge in impact_result["edges"]
        )

        approve_result = await memory_no_llm_verify.submit_async_codebase_approval(
            bank_id,
            submit_result["codebase_id"],
            request_context=request_context,
        )
        approve_operation = await memory_no_llm_verify.get_operation_result(
            bank_id,
            approve_result["operation_id"],
            request_context=request_context,
        )
        assert approve_operation["status"] == "completed"
        assert approve_operation["result"]["status"] == "approved"
        assert approve_operation["result"]["hydrated_files"] >= 4

        approved_codebase = await memory_no_llm_verify.get_codebase(
            bank_id,
            submit_result["codebase_id"],
            request_context=request_context,
        )
        assert approved_codebase is not None
        assert approved_codebase["approved_snapshot_id"] == submit_result["snapshot_id"]
        assert approved_codebase["approval_status"] == "approved"
        assert approved_codebase["memory_status"] == "hydrated"
        assert approved_codebase["approved_snapshot_status"] == "approved"

        approved_files = await memory_no_llm_verify.list_codebase_files(
            bank_id,
            submit_result["codebase_id"],
            request_context=request_context,
        )
        approved_by_path = {item["path"]: item for item in approved_files["items"]}
        assert approved_by_path["src/main.py"]["document_id"] == (
            f"codebase:{submit_result['codebase_id']}:src/main.py"
        )

        approved_document = await memory_no_llm_verify.get_document(
            f"codebase:{submit_result['codebase_id']}:src/main.py",
            bank_id,
            request_context=request_context,
        )
        assert approved_document is not None
        assert "from src.util import helper" in approved_document["original_text"]
    finally:
        await memory_no_llm_verify.delete_bank(bank_id, request_context=request_context)


@pytest.mark.asyncio
async def test_codebase_github_refresh_keeps_previous_memory_until_new_snapshot_is_approved(
    memory_no_llm_verify, request_context, monkeypatch
):
    bank_id = _bank_id("github")
    archive_v1 = _build_repo_zip(
        {
            "demo-repo/src/util.py": "def helper():\n    return 'v1'\n",
            "demo-repo/src/main.py": "from src.util import helper\n\ndef run():\n    return helper()\n",
            "demo-repo/src/obsolete.py": "VALUE = 1\n",
        }
    )
    archive_v2 = _build_repo_zip(
        {
            "demo-repo/src/util.py": "def helper():\n    return 'v2'\n",
            "demo-repo/src/main.py": "from src.util import helper\n\ndef run():\n    return helper()\n",
            "demo-repo/src/new_module.py": "def fresh():\n    return 2\n",
        }
    )
    remote_state = {"sha": "sha-v1", "archive": archive_v1}

    async def fake_resolve(owner: str, repo: str, ref: str) -> str:
        assert owner == "octocat"
        assert repo == "hello-world"
        assert ref == "main"
        return remote_state["sha"]

    async def fake_download(owner: str, repo: str, commit_sha: str) -> bytes:
        assert owner == "octocat"
        assert repo == "hello-world"
        assert commit_sha == remote_state["sha"]
        return remote_state["archive"]

    monkeypatch.setattr(memory_no_llm_verify, "_resolve_public_github_commit_sha", fake_resolve)
    monkeypatch.setattr(memory_no_llm_verify, "_download_public_github_archive", fake_download)

    try:
        await memory_no_llm_verify.get_bank_profile(bank_id=bank_id, request_context=request_context)

        import_result = await memory_no_llm_verify.submit_async_codebase_github_import(
            bank_id=bank_id,
            owner="octocat",
            repo="hello-world",
            ref="main",
            request_context=request_context,
        )
        codebase_id = import_result["codebase_id"]

        imported_files = await memory_no_llm_verify.list_codebase_files(
            bank_id,
            codebase_id,
            request_context=request_context,
        )
        imported_by_path = {item["path"]: item for item in imported_files["items"]}
        assert imported_by_path["src/main.py"]["document_id"] is None

        pre_approval_doc = await memory_no_llm_verify.get_document(
            f"codebase:{codebase_id}:src/main.py",
            bank_id,
            request_context=request_context,
        )
        assert pre_approval_doc is None

        approve_v1 = await memory_no_llm_verify.submit_async_codebase_approval(
            bank_id,
            codebase_id,
            request_context=request_context,
        )
        approve_v1_operation = await memory_no_llm_verify.get_operation_result(
            bank_id,
            approve_v1["operation_id"],
            request_context=request_context,
        )
        assert approve_v1_operation["status"] == "completed"

        stable_main_document_id = f"codebase:{codebase_id}:src/main.py"
        obsolete_document_id = f"codebase:{codebase_id}:src/obsolete.py"

        initial_main_document = await memory_no_llm_verify.get_document(
            stable_main_document_id,
            bank_id,
            request_context=request_context,
        )
        assert initial_main_document is not None
        initial_util_document = await memory_no_llm_verify.get_document(
            f"codebase:{codebase_id}:src/util.py",
            bank_id,
            request_context=request_context,
        )
        assert initial_util_document is not None
        assert "v1" in initial_util_document["original_text"]

        noop_refresh = await memory_no_llm_verify.submit_async_codebase_refresh(
            bank_id,
            codebase_id,
            request_context=request_context,
        )
        assert noop_refresh["noop"] is True
        assert noop_refresh["operation_id"] is None

        remote_state["sha"] = "sha-v2"
        remote_state["archive"] = archive_v2
        refresh_result = await memory_no_llm_verify.submit_async_codebase_refresh(
            bank_id,
            codebase_id,
            request_context=request_context,
        )
        assert refresh_result["noop"] is False
        assert refresh_result["operation_id"] is not None

        refresh_operation = await memory_no_llm_verify.get_operation_result(
            bank_id,
            refresh_result["operation_id"],
            request_context=request_context,
        )
        assert refresh_operation["status"] == "completed"
        assert refresh_operation["result"]["status"] == "review_required"
        assert refresh_operation["result"]["changed_files"] == 1
        assert refresh_operation["result"]["added_files"] == 1
        assert refresh_operation["result"]["deleted_files"] == 1

        refreshed_codebase = await memory_no_llm_verify.get_codebase(
            bank_id,
            codebase_id,
            request_context=request_context,
        )
        assert refreshed_codebase is not None
        assert refreshed_codebase["current_snapshot_id"] == refresh_result["snapshot_id"]
        assert refreshed_codebase["approved_snapshot_id"] != refresh_result["snapshot_id"]
        assert refreshed_codebase["approval_status"] == "pending_approval"
        assert refreshed_codebase["memory_status"] == "hydrated_from_previous_snapshot"

        refreshed_files = await memory_no_llm_verify.list_codebase_files(
            bank_id,
            codebase_id,
            request_context=request_context,
        )
        refreshed_by_path = {item["path"]: item for item in refreshed_files["items"]}
        assert refreshed_files["snapshot_id"] == refresh_result["snapshot_id"]
        assert refreshed_files["snapshot_status"] == "review_required"
        assert refreshed_by_path["src/main.py"]["document_id"] is None
        assert refreshed_by_path["src/util.py"]["document_id"] is None
        assert refreshed_by_path["src/new_module.py"]["document_id"] is None
        assert "src/obsolete.py" not in refreshed_by_path

        still_approved_obsolete = await memory_no_llm_verify.get_document(
            obsolete_document_id,
            bank_id,
            request_context=request_context,
        )
        assert still_approved_obsolete is not None
        still_approved_util = await memory_no_llm_verify.get_document(
            f"codebase:{codebase_id}:src/util.py",
            bank_id,
            request_context=request_context,
        )
        assert still_approved_util is not None
        assert "v1" in still_approved_util["original_text"]

        approve_v2 = await memory_no_llm_verify.submit_async_codebase_approval(
            bank_id,
            codebase_id,
            request_context=request_context,
        )
        approve_v2_operation = await memory_no_llm_verify.get_operation_result(
            bank_id,
            approve_v2["operation_id"],
            request_context=request_context,
        )
        assert approve_v2_operation["status"] == "completed"
        assert approve_v2_operation["result"]["status"] == "approved"
        assert approve_v2_operation["result"]["deleted_files"] == 1

        final_codebase = await memory_no_llm_verify.get_codebase(
            bank_id,
            codebase_id,
            request_context=request_context,
        )
        assert final_codebase is not None
        assert final_codebase["approved_snapshot_id"] == refresh_result["snapshot_id"]
        assert final_codebase["approval_status"] == "approved"
        assert final_codebase["memory_status"] == "hydrated"

        updated_util_document = await memory_no_llm_verify.get_document(
            f"codebase:{codebase_id}:src/util.py",
            bank_id,
            request_context=request_context,
        )
        assert updated_util_document is not None
        assert "v2" in updated_util_document["original_text"]

        deleted_document = await memory_no_llm_verify.get_document(
            obsolete_document_id,
            bank_id,
            request_context=request_context,
        )
        assert deleted_document is None

        new_module_document = await memory_no_llm_verify.get_document(
            f"codebase:{codebase_id}:src/new_module.py",
            bank_id,
            request_context=request_context,
        )
        assert new_module_document is not None

        approved_files = await memory_no_llm_verify.list_codebase_files(
            bank_id,
            codebase_id,
            request_context=request_context,
        )
        approved_by_path = {item["path"]: item for item in approved_files["items"]}
        assert approved_by_path["src/main.py"]["document_id"] == stable_main_document_id
    finally:
        await memory_no_llm_verify.delete_bank(bank_id, request_context=request_context)


@pytest.mark.asyncio
async def test_codebase_http_endpoints_expose_review_then_approve_flow(
    memory_no_llm_verify, request_context
):
    bank_id = _bank_id("http")
    archive_bytes = _build_repo_zip(
        {
            "demo-repo/src/util.py": "def helper():\n    return 'ok'\n",
            "demo-repo/src/main.py": "from src.util import helper\n\ndef run():\n    return helper()\n",
        }
    )
    app = create_app(memory_no_llm_verify, initialize_memory=False)

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            bank_response = await client.put(f"/v1/default/banks/{bank_id}", json={"name": "HTTP Codebase Bank"})
            assert bank_response.status_code in (200, 201)

            files = {"archive": ("demo-repo.zip", archive_bytes, "application/zip")}
            data = {"request": json.dumps({"name": "demo-repo"})}
            import_response = await client.post(
                f"/v1/default/banks/{bank_id}/codebases/import/zip",
                files=files,
                data=data,
            )
            assert import_response.status_code == 200
            import_payload = import_response.json()
            codebase_id = import_payload["codebase_id"]

            detail_response = await client.get(f"/v1/default/banks/{bank_id}/codebases/{codebase_id}")
            assert detail_response.status_code == 200
            detail_payload = detail_response.json()
            assert detail_payload["name"] == "demo-repo"
            assert detail_payload["snapshot_status"] == "review_required"
            assert detail_payload["approval_status"] == "pending_approval"
            assert detail_payload["approved_snapshot_id"] is None

            files_response = await client.get(f"/v1/default/banks/{bank_id}/codebases/{codebase_id}/files")
            assert files_response.status_code == 200
            files_payload = files_response.json()
            assert files_payload["snapshot_status"] == "review_required"
            files_by_path = {item["path"]: item for item in files_payload["items"]}
            assert files_by_path["src/main.py"]["document_id"] is None

            symbols_response = await client.get(
                f"/v1/default/banks/{bank_id}/codebases/{codebase_id}/symbols",
                params={"q": "helper"},
            )
            assert symbols_response.status_code == 200
            symbol_names = [item["name"] for item in symbols_response.json()["items"]]
            assert "helper" in symbol_names

            impact_response = await client.post(
                f"/v1/default/banks/{bank_id}/codebases/{codebase_id}/impact",
                json={"path": "src/util.py", "max_depth": 2, "limit": 10},
            )
            assert impact_response.status_code == 200
            impacted_paths = [item["path"] for item in impact_response.json()["impacted_files"]]
            assert "src/main.py" in impacted_paths

            approve_response = await client.post(
                f"/v1/default/banks/{bank_id}/codebases/{codebase_id}/approve",
                json={},
            )
            assert approve_response.status_code == 200
            approve_payload = approve_response.json()
            assert approve_payload["codebase_id"] == codebase_id

            approve_operation = await memory_no_llm_verify.get_operation_result(
                bank_id,
                approve_payload["operation_id"],
                request_context=request_context,
            )
            assert approve_operation["status"] == "completed"
            assert approve_operation["result"]["status"] == "approved"

            approved_detail_response = await client.get(f"/v1/default/banks/{bank_id}/codebases/{codebase_id}")
            assert approved_detail_response.status_code == 200
            approved_detail = approved_detail_response.json()
            assert approved_detail["approved_snapshot_id"] == detail_payload["current_snapshot_id"]
            assert approved_detail["approval_status"] == "approved"
            assert approved_detail["memory_status"] == "hydrated"

            approved_files_response = await client.get(
                f"/v1/default/banks/{bank_id}/codebases/{codebase_id}/files"
            )
            assert approved_files_response.status_code == 200
            approved_files = approved_files_response.json()
            approved_by_path = {item["path"]: item for item in approved_files["items"]}
            assert approved_by_path["src/main.py"]["document_id"] == f"codebase:{codebase_id}:src/main.py"
    finally:
        await memory_no_llm_verify.delete_bank(bank_id, request_context=request_context)
