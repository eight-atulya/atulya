from datetime import datetime

import httpx
import pytest
import pytest_asyncio

from atulya_api.api import create_app
from atulya_api.engine.db_utils import acquire_with_retry
from atulya_api.engine.memory_engine import fq_table


@pytest_asyncio.fixture
async def api_client(memory_no_llm_verify):
    app = create_app(memory_no_llm_verify, initialize_memory=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _bank_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now().timestamp()}"


async def _first_embedding_text(memory, bank_id: str) -> str | None:
    pool = await memory._get_pool()
    async with acquire_with_retry(pool) as conn:
        row = await conn.fetchrow(
            f"""
            SELECT embedding::text AS embedding_text
            FROM {fq_table('memory_units')}
            WHERE bank_id = $1
            ORDER BY id
            LIMIT 1
            """,
            bank_id,
        )
    return row["embedding_text"] if row else None


async def _seed_repo_vector_fixture(memory, embeddings, bank_id: str) -> str:
    embedding = embeddings.encode(["Alpha launch plan beta rollout checklist"])[0]
    embedding_text = "[" + ",".join(str(value) for value in embedding) + "]"
    chunk_id = f"{bank_id}_launch-notes_1"
    pool = await memory._get_pool()
    async with acquire_with_retry(pool) as conn:
        await conn.execute(
            f"""
            INSERT INTO {fq_table('documents')} (id, bank_id, original_text)
            VALUES ($1, $2, $3)
            """,
            "launch-notes",
            bank_id,
            "Alpha launch plan. Beta feedback. Gamma rollout checklist.",
        )
        await conn.execute(
            f"""
            INSERT INTO {fq_table('chunks')} (chunk_id, document_id, bank_id, chunk_index, chunk_text)
            VALUES ($1, $2, $3, $4, $5)
            """,
            chunk_id,
            "launch-notes",
            bank_id,
            1,
            "Alpha launch plan. Beta feedback. Gamma rollout checklist.",
        )
        await conn.execute(
            f"""
            INSERT INTO {fq_table('memory_units')} (bank_id, document_id, chunk_id, text, embedding, fact_type)
            VALUES ($1, $2, $3, $4, $5::vector, 'world')
            """,
            bank_id,
            "launch-notes",
            chunk_id,
            "Alpha launch plan beta rollout checklist",
            embedding_text,
        )
    return embedding_text


@pytest.mark.asyncio
async def test_memory_repo_branch_checkout_isolates_workspace(memory_no_llm_verify, request_context):
    memory = memory_no_llm_verify
    bank_id = _bank_id("repo_branch")
    await memory.get_bank_profile(bank_id, request_context=request_context)
    await memory.update_bank(bank_id, name="Main Bank", request_context=request_context)

    repo = await memory.enable_memory_repo(bank_id, request_context=request_context)
    repo_id = repo["repo_id"]

    await memory.create_memory_repo_branch(repo_id, branch_name="v2", request_context=request_context)
    await memory.checkout_memory_repo_branch(repo_id, branch_name="v2", request_context=request_context)
    await memory.update_bank(bank_id, name="V2 Bank", request_context=request_context)

    dirty_status = await memory.get_memory_repo_status(repo_id, request_context=request_context)
    assert dirty_status["dirty"] is True

    await memory.commit_memory_repo(repo_id, message="Rename branch workspace", request_context=request_context)

    repo_summary = await memory.get_memory_repo(repo_id, request_context=request_context)
    assert repo_summary["head_commit_id"] is not None
    assert repo_summary["head_message"] == "Rename branch workspace"
    assert repo_summary["head_created_at"] is not None
    assert (await memory.get_memory_repo_for_bank(bank_id, request_context=request_context))["repo_id"] == repo_id
    branch_summaries = await memory.list_memory_repo_branches_for_bank(bank_id, request_context=request_context)
    assert any(item["branch_name"] == "v2" for item in branch_summaries)

    v2_profile = await memory.get_bank_profile(bank_id, request_context=request_context)
    assert v2_profile["name"] == "V2 Bank"

    await memory.checkout_memory_repo_branch(repo_id, branch_name="main", request_context=request_context)
    main_profile = await memory.get_bank_profile(bank_id, request_context=request_context)
    assert main_profile["name"] == "Main Bank"

    diff = await memory.diff_memory_repo(
        repo_id,
        from_branch="main",
        to_branch="v2",
        request_context=request_context,
    )
    assert diff["dirty"] is True
    assert "profile_config" in diff["changed_components"]


@pytest.mark.asyncio
async def test_memory_repo_reset_hard_discards_uncommitted_changes(memory_no_llm_verify, request_context):
    memory = memory_no_llm_verify
    bank_id = _bank_id("repo_reset")
    await memory.get_bank_profile(bank_id, request_context=request_context)
    await memory.update_bank(bank_id, name="Base Bank", request_context=request_context)

    repo = await memory.enable_memory_repo(bank_id, request_context=request_context)
    repo_id = repo["repo_id"]
    await memory.create_memory_repo_branch(repo_id, branch_name="experiment", request_context=request_context)
    await memory.checkout_memory_repo_branch(repo_id, branch_name="experiment", request_context=request_context)

    await memory.update_bank(bank_id, name="Committed Branch Name", request_context=request_context)
    commit = await memory.commit_memory_repo(
        repo_id,
        message="Commit branch rename",
        request_context=request_context,
    )

    await memory.update_bank(bank_id, name="Dirty Branch Name", request_context=request_context)
    status_before = await memory.get_memory_repo_status(repo_id, request_context=request_context)
    assert status_before["dirty"] is True

    status_after = await memory.reset_memory_repo_hard(
        repo_id,
        commit_id=commit["commit_id"],
        force=True,
        request_context=request_context,
    )
    assert status_after["dirty"] is False

    profile = await memory.get_bank_profile(bank_id, request_context=request_context)
    assert profile["name"] == "Committed Branch Name"


@pytest.mark.asyncio
async def test_memory_repo_hidden_workspaces_are_excluded_from_bank_list(memory_no_llm_verify, request_context):
    memory = memory_no_llm_verify
    bank_id = _bank_id("repo_hidden")
    await memory.get_bank_profile(bank_id, request_context=request_context)
    repo = await memory.enable_memory_repo(bank_id, request_context=request_context)
    repo_id = repo["repo_id"]

    branch = await memory.create_memory_repo_branch(
        repo_id,
        branch_name="experiment",
        request_context=request_context,
    )
    assert branch["workspace_bank_id"].startswith("__repo__")

    banks = await memory.list_banks(request_context=request_context)
    bank_ids = [item["bank_id"] for item in banks]

    assert bank_id in bank_ids
    assert branch["workspace_bank_id"] not in bank_ids


@pytest.mark.asyncio
async def test_memory_repo_branch_creation_with_retained_documents_remaps_workspace_ids(
    memory_no_llm_verify, embeddings, request_context
):
    memory = memory_no_llm_verify
    bank_id = _bank_id("repo_docs")
    await memory.get_bank_profile(bank_id, request_context=request_context)
    await _seed_repo_vector_fixture(memory, embeddings, bank_id)
    original_embedding = await _first_embedding_text(memory, bank_id)
    assert original_embedding is not None

    repo = await memory.enable_memory_repo(bank_id, request_context=request_context)
    repo_id = repo["repo_id"]

    branch = await memory.create_memory_repo_branch(
        repo_id,
        branch_name="docs-v2",
        request_context=request_context,
    )
    assert branch["branch_name"] == "docs-v2"
    branch_embedding = await _first_embedding_text(memory, branch["workspace_bank_id"])
    assert branch_embedding == original_embedding

    await memory.checkout_memory_repo_branch(repo_id, branch_name="docs-v2", request_context=request_context)
    status = await memory.get_memory_repo_status(repo_id, request_context=request_context)
    assert status["dirty"] is False
    checked_out_embedding = await _first_embedding_text(memory, bank_id)
    assert checked_out_embedding == original_embedding

    documents = await memory.list_documents(bank_id=bank_id, request_context=request_context)
    assert documents["total"] == 1
    assert documents["items"][0]["id"] == "launch-notes"


@pytest.mark.asyncio
async def test_memory_repo_branch_reads_work_without_checkout(memory_no_llm_verify, embeddings, request_context):
    memory = memory_no_llm_verify
    bank_id = _bank_id("repo_branch_read")
    await memory.get_bank_profile(bank_id, request_context=request_context)
    repo = await memory.enable_memory_repo(bank_id, request_context=request_context)
    repo_id = repo["repo_id"]

    await memory.create_memory_repo_branch(repo_id, branch_name="research", request_context=request_context)
    await memory.checkout_memory_repo_branch(repo_id, branch_name="research", request_context=request_context)
    await memory.update_bank(bank_id, name="Research Workspace", request_context=request_context)
    await _seed_repo_vector_fixture(memory, embeddings, bank_id)
    await memory.commit_memory_repo(repo_id, message="Add branch-only research notes", request_context=request_context)

    await memory.checkout_memory_repo_branch(repo_id, branch_name="main", request_context=request_context)

    main_profile = await memory.get_bank_profile(bank_id, request_context=request_context)
    assert main_profile["name"] != "Research Workspace"
    main_documents = await memory.list_documents(bank_id=bank_id, request_context=request_context)
    assert main_documents["total"] == 0
    assert await memory.get_document("launch-notes", bank_id, request_context=request_context) is None

    branch_profile = await memory.get_bank_profile(
        bank_id,
        branch_name="research",
        request_context=request_context,
    )
    assert branch_profile["name"] == "Research Workspace"

    branch_documents = await memory.list_documents(
        bank_id=bank_id,
        branch_name="research",
        request_context=request_context,
    )
    assert branch_documents["total"] == 1
    assert branch_documents["items"][0]["id"] == "launch-notes"

    branch_document = await memory.get_document(
        "launch-notes",
        bank_id,
        branch_name="research",
        request_context=request_context,
    )
    assert branch_document is not None
    assert branch_document["id"] == "launch-notes"

    main_recall = await memory.recall_async(
        bank_id=bank_id,
        query="rollout checklist",
        max_tokens=512,
        request_context=request_context,
    )
    assert main_recall.results == []

    branch_recall = await memory.recall_async(
        bank_id=bank_id,
        branch_name="research",
        query="rollout checklist",
        max_tokens=512,
        request_context=request_context,
    )
    assert any("rollout checklist" in result.text.lower() for result in branch_recall.results)


@pytest.mark.asyncio
async def test_submit_async_reflect_preserves_branch_name(memory_no_llm_verify, request_context, monkeypatch):
    memory = memory_no_llm_verify
    bank_id = _bank_id("repo_async_reflect")
    await memory.get_bank_profile(bank_id, request_context=request_context)

    captured: dict[str, object] = {}

    async def fake_submit_async_operation(**kwargs):
        captured.update(kwargs)
        return {"operation_id": "op-branch-reflect"}

    monkeypatch.setattr(memory, "_submit_async_operation", fake_submit_async_operation)

    result = await memory.submit_async_reflect(
        bank_id=bank_id,
        query="Summarize the branch state",
        branch_name="research",
        request_context=request_context,
    )

    assert result["operation_id"] == "op-branch-reflect"
    assert captured["task_payload"]["branch_name"] == "research"
    assert captured["result_metadata"]["branch_name"] == "research"


@pytest.mark.asyncio
async def test_memory_repo_http_endpoints(api_client):
    bank_id = _bank_id("repo_http")

    response = await api_client.put(f"/v1/default/banks/{bank_id}", json={"name": "Repo HTTP Bank"})
    assert response.status_code == 200

    response = await api_client.post(
        f"/v1/default/banks/{bank_id}/repos/enable",
        json={"repo_name": "HTTP Repo"},
    )
    assert response.status_code == 200
    repo = response.json()
    repo_id = repo["repo_id"]

    response = await api_client.get(f"/v1/default/banks/{bank_id}/repo")
    assert response.status_code == 200
    assert response.json()["repo"]["repo_id"] == repo_id

    response = await api_client.get(f"/v1/default/banks/{bank_id}/repo/branches")
    assert response.status_code == 200
    assert any(item["branch_name"] == "main" for item in response.json()["branches"])

    response = await api_client.get("/v1/default/repos")
    assert response.status_code == 200
    assert any(item["repo_id"] == repo_id for item in response.json()["repos"])

    response = await api_client.post(
        f"/v1/default/repos/{repo_id}/branches",
        json={"branch_name": "v2"},
    )
    assert response.status_code == 200

    response = await api_client.post(
        f"/v1/default/repos/{repo_id}/checkout",
        json={"branch_name": "v2"},
    )
    assert response.status_code == 200
    assert response.json()["active_branch"] == "v2"

    response = await api_client.put(
        f"/v1/default/banks/{bank_id}",
        json={"name": "HTTP Repo V2"},
    )
    assert response.status_code == 200

    response = await api_client.post(
        f"/v1/default/repos/{repo_id}/commit",
        json={"message": "Commit HTTP branch rename"},
    )
    assert response.status_code == 200

    response = await api_client.get(f"/v1/default/repos/{repo_id}/status")
    assert response.status_code == 200
    assert response.json()["dirty"] is False

    response = await api_client.get(f"/v1/default/repos/{repo_id}/branches")
    assert response.status_code == 200
    assert any(item["branch_name"] == "v2" for item in response.json()["branches"])


@pytest.mark.asyncio
async def test_memory_repo_http_branch_query_endpoints(api_client, embeddings):
    memory = api_client._transport.app.state.memory
    bank_id = _bank_id("repo_http_branch")

    response = await api_client.put(f"/v1/default/banks/{bank_id}", json={"name": "HTTP Branch Bank"})
    assert response.status_code == 200

    response = await api_client.post(f"/v1/default/banks/{bank_id}/repos/enable", json={"repo_name": "HTTP Branch Repo"})
    assert response.status_code == 200
    repo_id = response.json()["repo_id"]

    response = await api_client.post(f"/v1/default/repos/{repo_id}/branches", json={"branch_name": "research"})
    assert response.status_code == 200
    response = await api_client.post(f"/v1/default/repos/{repo_id}/checkout", json={"branch_name": "research"})
    assert response.status_code == 200

    await _seed_repo_vector_fixture(memory, embeddings, bank_id)
    response = await api_client.post(
        f"/v1/default/repos/{repo_id}/commit",
        json={"message": "Commit branch-only research notes"},
    )
    assert response.status_code == 200

    response = await api_client.post(f"/v1/default/repos/{repo_id}/checkout", json={"branch_name": "main"})
    assert response.status_code == 200

    response = await api_client.post(
        f"/v1/default/banks/{bank_id}/memories/recall",
        json={"query": "rollout checklist", "branch_name": "research", "max_tokens": 512},
    )
    assert response.status_code == 200
    assert any("rollout checklist" in item["text"].lower() for item in response.json()["results"])

    response = await api_client.get(f"/v1/default/banks/{bank_id}/documents", params={"branch_name": "research"})
    assert response.status_code == 200
    assert response.json()["total"] == 1

    response = await api_client.get(
        f"/v1/default/banks/{bank_id}/documents/launch-notes",
        params={"branch_name": "research"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "launch-notes"

    response = await api_client.get(f"/v1/default/banks/{bank_id}/memories/list", params={"branch_name": "research"})
    assert response.status_code == 200
    assert response.json()["total"] == 1


@pytest.mark.asyncio
async def test_memory_repo_mcp_tools_are_registered_and_callable(memory_no_llm_verify, embeddings, request_context):
    from atulya_api.api.mcp import create_mcp_server

    memory = memory_no_llm_verify
    bank_id = _bank_id("repo_mcp")
    await memory.get_bank_profile(bank_id, request_context=request_context)
    await memory.update_bank(bank_id, name="MCP Main", request_context=request_context)
    repo = await memory.enable_memory_repo(bank_id, request_context=request_context)
    repo_id = repo["repo_id"]

    server = create_mcp_server(memory, multi_bank=True)
    tools = server._tool_manager._tools

    for tool_name in (
        "memory_repo_list",
        "memory_repo_get",
        "memory_repo_branch_list",
        "memory_repo_status",
        "memory_repo_log",
        "memory_repo_diff",
        "memory_repo_branch_create",
        "memory_repo_checkout",
        "memory_repo_commit",
        "memory_repo_reset_hard",
    ):
        assert tool_name in tools

    repo_get = await tools["memory_repo_get"].fn(bank_id=bank_id)
    assert repo_id in repo_get

    branch_list = await tools["memory_repo_branch_list"].fn(bank_id=bank_id)
    assert "\"main\"" in branch_list

    branch_create = await tools["memory_repo_branch_create"].fn(repo_id=repo_id, branch_name="mcp-v2")
    assert "mcp-v2" in branch_create

    checkout = await tools["memory_repo_checkout"].fn(repo_id=repo_id, branch_name="mcp-v2")
    assert "mcp-v2" in checkout

    await memory.update_bank(bank_id, name="MCP V2", request_context=request_context)
    commit = await tools["memory_repo_commit"].fn(repo_id=repo_id, message="Commit MCP branch")
    assert "Commit MCP branch" in commit

    await _seed_repo_vector_fixture(memory, embeddings, bank_id)
    await memory.commit_memory_repo(repo_id, message="Commit MCP research notes", request_context=request_context)
    await memory.checkout_memory_repo_branch(repo_id, branch_name="main", request_context=request_context)

    branch_recall = await tools["recall"].fn(query="rollout checklist", bank_id=bank_id, branch_name="mcp-v2")
    assert "rollout checklist" in branch_recall.lower()

    branch_documents = await tools["list_documents"].fn(bank_id=bank_id, branch_name="mcp-v2")
    assert "launch-notes" in branch_documents

    status = await tools["memory_repo_status"].fn(repo_id=repo_id)
    assert "\"dirty\": false" in status

    diff = await tools["memory_repo_diff"].fn(repo_id=repo_id, from_branch="main", to_branch="mcp-v2")
    assert "profile_config" in diff
