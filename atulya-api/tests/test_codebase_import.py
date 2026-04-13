"""
Focused tests for ASD-first codebase import, review, routing, and approval.
"""

from __future__ import annotations

import io
import json
import uuid
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


async def _route_all_chunks_to_memory(memory_engine, bank_id: str, codebase_id: str, request_context) -> list[dict]:
    chunks_result = await memory_engine.list_codebase_chunks(
        bank_id,
        codebase_id,
        request_context=request_context,
    )
    assert chunks_result["items"]
    await memory_engine.route_codebase_review_items(
        bank_id,
        codebase_id,
        item_ids=[item["id"] for item in chunks_result["items"]],
        target="memory",
        request_context=request_context,
    )
    return chunks_result["items"]


@pytest.mark.asyncio
async def test_codebase_zip_import_requires_chunk_routing_before_memory_hydration(
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
        assert import_operation["result"]["status"] == "review_required"

        codebase = await memory_no_llm_verify.get_codebase(
            bank_id,
            submit_result["codebase_id"],
            request_context=request_context,
        )
        assert codebase is not None
        assert codebase["snapshot_status"] == "review_required"
        assert codebase["approval_status"] == "pending_approval"
        assert codebase["memory_status"] == "not_hydrated"
        assert codebase["stats"]["chunk_count"] >= 4

        review_summary = await memory_no_llm_verify.get_codebase_review(
            bank_id,
            submit_result["codebase_id"],
            request_context=request_context,
        )
        assert review_summary["review_counts"]["unrouted"] >= 4

        files_result = await memory_no_llm_verify.list_codebase_files(
            bank_id,
            submit_result["codebase_id"],
            request_context=request_context,
        )
        files_by_path = {item["path"]: item for item in files_result["items"]}
        assert files_by_path["src/main.py"]["status"] == "indexed"
        assert files_by_path["src/main.py"]["document_id"] is None
        assert files_by_path["src/main.py"]["chunk_count"] >= 1
        assert files_by_path["dist/generated.js"]["status"] == "excluded"

        chunks_result = await memory_no_llm_verify.list_codebase_chunks(
            bank_id,
            submit_result["codebase_id"],
            request_context=request_context,
        )
        main_chunk = next(item for item in chunks_result["items"] if item["path"] == "src/main.py")
        assert main_chunk["route_target"] == "unrouted"

        pre_approval_document = await memory_no_llm_verify.get_document(
            f"codebase:{submit_result['codebase_id']}:chunk:{main_chunk['chunk_key']}",
            bank_id,
            request_context=request_context,
        )
        assert pre_approval_document is None

        detail = await memory_no_llm_verify.get_codebase_chunk_detail(
            bank_id,
            submit_result["codebase_id"],
            main_chunk["id"],
            request_context=request_context,
        )
        assert "from src.util import helper" in detail["content_text"]

        symbols_result = await memory_no_llm_verify.search_codebase_symbols(
            bank_id,
            submit_result["codebase_id"],
            q="helper",
            request_context=request_context,
        )
        helper_matches = [item for item in symbols_result["items"] if item["name"] == "helper"]
        assert helper_matches
        assert helper_matches[0]["chunk_ids"]

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

        await _route_all_chunks_to_memory(
            memory_no_llm_verify,
            bank_id,
            submit_result["codebase_id"],
            request_context,
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
        assert approve_operation["result"]["applied_routes"] >= 4

        approved_codebase = await memory_no_llm_verify.get_codebase(
            bank_id,
            submit_result["codebase_id"],
            request_context=request_context,
        )
        assert approved_codebase is not None
        assert approved_codebase["approved_snapshot_id"] == submit_result["snapshot_id"]
        assert approved_codebase["approval_status"] == "approved"
        assert approved_codebase["memory_status"] == "hydrated"

        approved_chunks = await memory_no_llm_verify.list_codebase_chunks(
            bank_id,
            submit_result["codebase_id"],
            request_context=request_context,
        )
        approved_main_chunk = next(item for item in approved_chunks["items"] if item["chunk_key"] == main_chunk["chunk_key"])
        assert approved_main_chunk["document_id"] == f"codebase:{submit_result['codebase_id']}:chunk:{main_chunk['chunk_key']}"

        approved_document = await memory_no_llm_verify.get_document(
            approved_main_chunk["document_id"],
            bank_id,
            request_context=request_context,
        )
        assert approved_document is not None
        assert "from src.util import helper" in approved_document["original_text"]
    finally:
        await memory_no_llm_verify.delete_bank(bank_id, request_context=request_context)


@pytest.mark.asyncio
async def test_codebase_github_refresh_keeps_previous_memory_until_new_snapshot_is_rerouted_and_approved(
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

        imported_chunks = await _route_all_chunks_to_memory(
            memory_no_llm_verify,
            bank_id,
            codebase_id,
            request_context,
        )
        imported_main_chunk = next(item for item in imported_chunks if item["path"] == "src/main.py")
        imported_util_chunk = next(
            item for item in imported_chunks if item["path"] == "src/util.py" and item["kind"] == "function"
        )
        imported_obsolete_chunk = next(item for item in imported_chunks if item["path"] == "src/obsolete.py")

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

        stable_main_document_id = f"codebase:{codebase_id}:chunk:{imported_main_chunk['chunk_key']}"
        stable_util_document_id = f"codebase:{codebase_id}:chunk:{imported_util_chunk['chunk_key']}"
        obsolete_document_id = f"codebase:{codebase_id}:chunk:{imported_obsolete_chunk['chunk_key']}"

        initial_main_document = await memory_no_llm_verify.get_document(
            stable_main_document_id,
            bank_id,
            request_context=request_context,
        )
        assert initial_main_document is not None
        initial_util_document = await memory_no_llm_verify.get_document(
            stable_util_document_id,
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

        refreshed_codebase = await memory_no_llm_verify.get_codebase(
            bank_id,
            codebase_id,
            request_context=request_context,
        )
        assert refreshed_codebase is not None
        assert refreshed_codebase["approved_snapshot_id"] != refresh_result["snapshot_id"]
        assert refreshed_codebase["memory_status"] == "hydrated_from_previous_snapshot"

        refreshed_files = await memory_no_llm_verify.list_codebase_files(
            bank_id,
            codebase_id,
            request_context=request_context,
        )
        refreshed_by_path = {item["path"]: item for item in refreshed_files["items"]}
        assert refreshed_by_path["src/main.py"]["document_id"] is None
        assert "src/obsolete.py" not in refreshed_by_path

        still_approved_obsolete = await memory_no_llm_verify.get_document(
            obsolete_document_id,
            bank_id,
            request_context=request_context,
        )
        assert still_approved_obsolete is not None
        still_approved_util = await memory_no_llm_verify.get_document(
            stable_util_document_id,
            bank_id,
            request_context=request_context,
        )
        assert still_approved_util is not None
        assert "v1" in still_approved_util["original_text"]

        refreshed_chunks = await _route_all_chunks_to_memory(
            memory_no_llm_verify,
            bank_id,
            codebase_id,
            request_context,
        )
        refreshed_util_chunk = next(
            item for item in refreshed_chunks if item["path"] == "src/util.py" and item["kind"] == "function"
        )
        refreshed_new_module_chunk = next(item for item in refreshed_chunks if item["path"] == "src/new_module.py")

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
        assert approve_v2_operation["result"]["deleted_files"] >= 1

        final_codebase = await memory_no_llm_verify.get_codebase(
            bank_id,
            codebase_id,
            request_context=request_context,
        )
        assert final_codebase is not None
        assert final_codebase["approved_snapshot_id"] == refresh_result["snapshot_id"]
        assert final_codebase["approval_status"] == "approved"

        updated_util_document = await memory_no_llm_verify.get_document(
            f"codebase:{codebase_id}:chunk:{refreshed_util_chunk['chunk_key']}",
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
            f"codebase:{codebase_id}:chunk:{refreshed_new_module_chunk['chunk_key']}",
            bank_id,
            request_context=request_context,
        )
        assert new_module_document is not None
    finally:
        await memory_no_llm_verify.delete_bank(bank_id, request_context=request_context)


@pytest.mark.asyncio
async def test_codebase_http_endpoints_expose_review_chunk_routing_then_approve_flow(
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
            assert detail_payload["snapshot_status"] == "review_required"

            review_response = await client.get(f"/v1/default/banks/{bank_id}/codebases/{codebase_id}/review")
            assert review_response.status_code == 200
            assert review_response.json()["review_counts"]["unrouted"] >= 2

            chunks_response = await client.get(f"/v1/default/banks/{bank_id}/codebases/{codebase_id}/chunks")
            assert chunks_response.status_code == 200
            chunks_payload = chunks_response.json()
            assert chunks_payload["items"]

            first_chunk_id = chunks_payload["items"][0]["id"]
            chunk_detail_response = await client.get(
                f"/v1/default/banks/{bank_id}/codebases/{codebase_id}/chunks/{first_chunk_id}"
            )
            assert chunk_detail_response.status_code == 200

            route_response = await client.post(
                f"/v1/default/banks/{bank_id}/codebases/{codebase_id}/review/route",
                json={"item_ids": [item["id"] for item in chunks_payload["items"]], "target": "memory"},
            )
            assert route_response.status_code == 200
            assert route_response.json()["review_counts"]["memory"] >= 2

            research_response = await client.get(f"/v1/default/banks/{bank_id}/codebases/{codebase_id}/research")
            assert research_response.status_code == 200
            assert research_response.json()["items"] == []

            symbols_response = await client.get(
                f"/v1/default/banks/{bank_id}/codebases/{codebase_id}/symbols",
                params={"q": "helper"},
            )
            assert symbols_response.status_code == 200
            assert any(item["name"] == "helper" for item in symbols_response.json()["items"])

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

            approve_operation = await memory_no_llm_verify.get_operation_result(
                bank_id,
                approve_payload["operation_id"],
                request_context=request_context,
            )
            assert approve_operation["status"] == "completed"
            assert approve_operation["result"]["status"] == "approved"

            approved_chunks_response = await client.get(
                f"/v1/default/banks/{bank_id}/codebases/{codebase_id}/chunks"
            )
            assert approved_chunks_response.status_code == 200
            assert any(item["document_id"] for item in approved_chunks_response.json()["items"])
    finally:
        await memory_no_llm_verify.delete_bank(bank_id, request_context=request_context)


@pytest.mark.asyncio
async def test_public_github_archive_download_follows_redirects(memory_no_llm_verify):
    archive_bytes = _build_repo_zip({"demo-repo/src/main.py": "print('ok')\n"})

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(
                302,
                headers={"Location": "https://codeload.github.com/octocat/hello-world/legacy.zip/sha-v1"},
                request=request,
            )
        if request.url.host == "codeload.github.com":
            return httpx.Response(
                200,
                content=archive_bytes,
                headers={"Content-Length": str(len(archive_bytes))},
                request=request,
            )
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(mock_handler),
        follow_redirects=False,
        timeout=10.0,
    ) as client:
        memory_no_llm_verify._http_client = client
        downloaded = await memory_no_llm_verify._download_public_github_archive(
            "octocat",
            "hello-world",
            "sha-v1",
        )

    assert downloaded == archive_bytes


@pytest.mark.asyncio
async def test_public_github_archive_download_rejects_unexpected_redirect_host(memory_no_llm_verify):
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(
                302,
                headers={"Location": "https://example.com/malicious.zip"},
                request=request,
            )
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(mock_handler),
        follow_redirects=False,
        timeout=10.0,
    ) as client:
        memory_no_llm_verify._http_client = client
        with pytest.raises(ValueError, match="redirect target is not allowed"):
            await memory_no_llm_verify._download_public_github_archive(
                "octocat",
                "hello-world",
                "sha-v1",
            )


@pytest.mark.asyncio
async def test_codebase_github_http_import_accepts_repo_url(
    memory_no_llm_verify, request_context, monkeypatch
):
    bank_id = _bank_id("github_url")
    archive_bytes = _build_repo_zip(
        {
            "demo-repo/src/util.py": "def helper():\n    return 'ok'\n",
            "demo-repo/src/main.py": "from src.util import helper\n",
        }
    )
    app = create_app(memory_no_llm_verify, initialize_memory=False)

    async def fake_resolve(owner: str, repo: str, ref: str) -> str:
        assert owner == "octocat"
        assert repo == "hello-world"
        assert ref == "main"
        return "sha-v1"

    async def fake_download(owner: str, repo: str, commit_sha: str) -> bytes:
        assert owner == "octocat"
        assert repo == "hello-world"
        assert commit_sha == "sha-v1"
        return archive_bytes

    monkeypatch.setattr(memory_no_llm_verify, "_resolve_public_github_commit_sha", fake_resolve)
    monkeypatch.setattr(memory_no_llm_verify, "_download_public_github_archive", fake_download)

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            bank_response = await client.put(f"/v1/default/banks/{bank_id}", json={"name": "GitHub URL Bank"})
            assert bank_response.status_code in (200, 201)

            import_response = await client.post(
                f"/v1/default/banks/{bank_id}/codebases/import/github",
                json={
                    "repo_url": "https://github.com/octocat/hello-world.git",
                    "ref": "main",
                    "refresh_existing": True,
                },
            )
            assert import_response.status_code == 200
            import_payload = import_response.json()

            codebase = await memory_no_llm_verify.get_codebase(
                bank_id,
                import_payload["codebase_id"],
                request_context=request_context,
            )
            assert codebase is not None
            assert codebase["source_type"] == "github"
            assert codebase["source_config"]["owner"] == "octocat"
            assert codebase["source_config"]["repo"] == "hello-world"
            assert codebase["source_config"]["ref"] == "main"
    finally:
        await memory_no_llm_verify.delete_bank(bank_id, request_context=request_context)


@pytest.mark.asyncio
async def test_cancel_pending_codebase_import_cleans_up_staged_snapshot(
    memory_no_llm_verify, request_context
):
    bank_id = _bank_id("cancel_codebase")
    pool = await memory_no_llm_verify._get_pool()
    codebase_id = uuid.uuid4()
    snapshot_id = uuid.uuid4()
    operation_id = uuid.uuid4()

    await pool.execute(
        """
        INSERT INTO codebases (id, bank_id, name, source_type, source_config)
        VALUES ($1, $2, $3, 'github', $4::jsonb)
        """,
        codebase_id,
        bank_id,
        "octocat/hello-world",
        json.dumps({"owner": "octocat", "repo": "hello-world", "ref": "main"}),
    )
    await pool.execute(
        """
        INSERT INTO codebase_snapshots (id, codebase_id, bank_id, source_ref, source_commit_sha, status)
        VALUES ($1, $2, $3, 'main', 'sha-v1', 'pending')
        """,
        snapshot_id,
        codebase_id,
        bank_id,
    )
    await pool.execute(
        """
        INSERT INTO async_operations (operation_id, bank_id, operation_type, status, result_metadata)
        VALUES ($1, $2, 'codebase_import', 'pending', $3::jsonb)
        """,
        operation_id,
        bank_id,
        json.dumps(
            {
                "codebase_id": str(codebase_id),
                "snapshot_id": str(snapshot_id),
                "source_type": "github",
                "source_ref": "main",
            }
        ),
    )

    result = await memory_no_llm_verify.cancel_operation(
        bank_id=bank_id,
        operation_id=str(operation_id),
        request_context=request_context,
    )

    assert result["success"] is True
    remaining_op = await pool.fetchval(
        "SELECT COUNT(*) FROM async_operations WHERE operation_id = $1",
        operation_id,
    )
    remaining_snapshot = await pool.fetchval(
        "SELECT COUNT(*) FROM codebase_snapshots WHERE id = $1",
        snapshot_id,
    )
    remaining_codebase = await pool.fetchval(
        "SELECT COUNT(*) FROM codebases WHERE id = $1",
        codebase_id,
    )

    assert remaining_op == 0
    assert remaining_snapshot == 0
    assert remaining_codebase == 0
