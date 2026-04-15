from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP

from atulya_api.mcp_tools import MCPToolsConfig, register_mcp_tools


@pytest.mark.asyncio
async def test_mcp_registers_and_calls_anomaly_tool_multi_bank():
    memory = MagicMock()
    memory.get_anomaly_intelligence = AsyncMock(
        return_value={"summary": {"total_events": 0, "open_events": 0, "resolved_events": 0, "avg_severity": 0.0, "by_type": {}}}
    )
    mcp = FastMCP("test")
    register_mcp_tools(
        mcp,
        memory,
        MCPToolsConfig(
            bank_id_resolver=lambda: "bank-a",
            include_bank_id_param=True,
            tools={"get_anomaly_intelligence"},
        ),
    )
    tools = mcp._tool_manager._tools
    assert "get_anomaly_intelligence" in tools
    await tools["get_anomaly_intelligence"].fn(limit=5, bank_id="bank-b")
    memory.get_anomaly_intelligence.assert_awaited_once()
    assert memory.get_anomaly_intelligence.call_args.kwargs["bank_id"] == "bank-b"

