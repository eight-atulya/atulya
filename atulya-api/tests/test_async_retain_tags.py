"""Unit tests for async retain tag propagation."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from atulya_api.engine.memory_engine import MemoryEngine
from atulya_api.models import RequestContext


@pytest.mark.asyncio
async def test_submit_async_retain_includes_document_tags_in_task_payload():
    """submit_async_retain should include document_tags in queued task payload."""
    engine = MemoryEngine.__new__(MemoryEngine)
    engine._initialized = True
    engine._authenticate_tenant = AsyncMock()
    engine._operation_validator = None
    engine._submit_async_operation = AsyncMock(return_value={"operation_id": "op-1"})

    # Mock the pool and connection for parent operation creation
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.transaction = MagicMock()
    mock_conn.transaction.return_value.__aenter__ = AsyncMock()
    mock_conn.transaction.return_value.__aexit__ = AsyncMock()

    mock_pool = AsyncMock()
    mock_pool.acquire = AsyncMock(return_value=mock_conn)
    mock_pool.release = AsyncMock()

    engine._get_pool = AsyncMock(return_value=mock_pool)

    request_context = RequestContext(
        tenant_id="tenant-a",
        api_key_id="key-a",
        org_id="org-a",
        membership_id="membership-a",
        principal_id="principal-a",
        principal_type="human",
        role="owner",
        schema_name="org_a",
        allowed_actions=["memory.retain"],
        action_scopes={"memory.retain": ["org:*"]},
    )
    contents = [{"content": "Async retain payload test."}]
    document_tags = ["scope:tools", "user:alice"]

    result = await MemoryEngine.submit_async_retain(
        engine,
        bank_id="bank-1",
        contents=contents,
        document_tags=document_tags,
        request_context=request_context,
    )

    # Check result structure
    assert "operation_id" in result
    assert "items_count" in result
    assert result["items_count"] == 1

    # Verify authentication was called
    engine._authenticate_tenant.assert_awaited_once_with(request_context)

    # Verify child operation was submitted
    engine._submit_async_operation.assert_awaited_once()

    # Verify child operation payload contains document_tags
    kwargs = engine._submit_async_operation.await_args.kwargs
    assert kwargs["bank_id"] == "bank-1"
    assert kwargs["operation_type"] == "retain"
    assert kwargs["task_type"] == "batch_retain"
    assert kwargs["task_payload"]["contents"] == contents
    assert kwargs["task_payload"]["document_tags"] == document_tags
    assert kwargs["task_payload"]["_tenant_id"] == "tenant-a"
    assert kwargs["task_payload"]["_api_key_id"] == "key-a"
    assert kwargs["request_context"] is request_context
    authorization = request_context.to_task_authorization()
    assert authorization["principal_id"] == "principal-a"
    assert authorization["allowed_actions"] == ["memory.retain"]
    assert authorization["action_scopes"] == {"memory.retain": ["org:*"]}
    assert "api_key" not in authorization


@pytest.mark.asyncio
async def test_handle_batch_retain_forwards_document_tags_to_retain_batch_async():
    """Worker handler should forward document_tags from task payload."""
    engine = MemoryEngine.__new__(MemoryEngine)
    engine._initialized = True
    engine.retain_batch_async = AsyncMock(return_value={"items_count": 1})

    task_dict = {
        "bank_id": "bank-1",
        "contents": [{"content": "Forward tags test."}],
        "document_tags": ["scope:client"],
        "_tenant_id": "tenant-a",
        "_api_key_id": "key-a",
    }

    await MemoryEngine._handle_batch_retain(engine, task_dict)

    engine.retain_batch_async.assert_awaited_once()
    kwargs = engine.retain_batch_async.await_args.kwargs
    assert kwargs["bank_id"] == "bank-1"
    assert kwargs["contents"] == task_dict["contents"]
    assert kwargs["document_tags"] == ["scope:client"]

    request_context = kwargs["request_context"]
    assert request_context.internal is True
    assert request_context.user_initiated is True
    assert request_context.tenant_id == "tenant-a"
    assert request_context.api_key_id == "key-a"


@pytest.mark.asyncio
async def test_worker_restores_effective_authorization_from_task_envelope():
    """A session-authenticated task must retain its action and bank scope in the worker."""
    engine = MemoryEngine.__new__(MemoryEngine)
    engine._initialized = True
    engine.retain_batch_async = AsyncMock(return_value={"items_count": 1})

    await MemoryEngine._handle_batch_retain(
        engine,
        {
            "bank_id": "bank-1",
            "contents": [{"content": "Authorization envelope test."}],
            "_authorization": {
                "version": 1,
                "tenant_id": "org-a",
                "org_id": "org-a",
                "membership_id": "membership-a",
                "principal_id": "principal-a",
                "principal_type": "human",
                "role": "operator",
                "schema_name": "org_a",
                "allowed_actions": ["memory.retain"],
                "action_scopes": {"memory.retain": ["bank:bank-1"]},
                "user_initiated": True,
            },
        },
    )

    request_context = engine.retain_batch_async.await_args.kwargs["request_context"]
    assert request_context.internal is True
    assert request_context.user_initiated is True
    assert request_context.principal_id == "principal-a"
    assert request_context.allowed_actions == ["memory.retain"]
    assert request_context.action_scopes == {"memory.retain": ["bank:bank-1"]}

    from atulya_api.auth import can_perform

    assert can_perform(request_context, "memory.retain", "bank-1") is True
    assert can_perform(request_context, "memory.retain", "other-bank") is False
