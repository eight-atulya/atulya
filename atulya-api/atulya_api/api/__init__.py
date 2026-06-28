"""
Unified FastAPI application factory for HTTP REST and MCP surfaces.

Purpose:
    Compose a single ASGI app that can expose the dataplane HTTP API, the MCP
    protocol (multi-bank and single-bank servers), or both. HTTP route definitions
    live in ``api/http.py``; MCP wiring lives in ``api/mcp.py``.

Trigger path:
    - ``create_app`` called from ``server.py`` and ``main.py`` after ``MemoryEngine``
      construction
    - Tests may call ``create_app`` with feature flags disabled for isolation

Inputs:
    - Pre-constructed ``MemoryEngine`` (migrations already controlled at engine level)
    - Feature flags: ``http_api_enabled``, ``mcp_api_enabled``, ``mcp_mount_path``,
      ``initialize_memory``

Outputs:
    - Configured ``FastAPI`` instance with chained lifespans when MCP is enabled

Side effects:
    - MCP middleware intercepts ``/mcp*`` requests before FastAPI routing
    - Lifespan hooks start/stop MCP Starlette apps alongside HTTP startup/shutdown

Impact radius:
    - Changing mount order, lifespan chaining, or middleware here affects every
      external integration (control plane proxies, CLI, MCP clients).

Maintenance notes:
    - Good: add optional surfaces behind explicit flags without altering default HTTP.
    - Bad: mount MCP with Starlette ``Mount`` (causes 307 redirect on ``/mcp``);
      the wrapping ``MCPMiddleware`` exists specifically to avoid that behavior.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from atulya_api import MemoryEngine

logger = logging.getLogger(__name__)


def create_app(
    memory: MemoryEngine,
    http_api_enabled: bool = True,
    mcp_api_enabled: bool = False,
    mcp_mount_path: str = "/mcp",
    initialize_memory: bool = True,
) -> FastAPI:
    """
    Create and configure the unified Atulya API application.

    Purpose:
        Single composition root for HTTP routes and optional MCP servers sharing one
        ``MemoryEngine`` instance.

    Trigger path:
        Called at process startup from ``server.py`` / ``main.py`` after engine init.

    Inputs:
        memory: Fully constructed ``MemoryEngine`` (pool, extensions, migrations flag).
        http_api_enabled: When True, delegates to ``api.http.create_app`` for REST routes.
        mcp_api_enabled: When True, loads MCP deps and wraps app with ``MCPMiddleware``.
        mcp_mount_path: URL prefix for MCP (default ``/mcp``; no trailing slash required).
        initialize_memory: Passed to HTTP app lifespan for eager vs lazy engine warmup.

    Outputs:
        ``FastAPI`` app ready for uvicorn. MCP lifespans are chained when MCP is on.

    Side effects:
        Imports ``api.http`` and/or ``api.mcp`` submodules; MCP path raises
        ``ImportError`` if optional ``atulya-api[mcp]`` extras are missing.

    Impact radius:
        All external API contracts (OpenAPI, MCP tools) depend on which flags are enabled.

    Failure modes:
        ``ImportError`` when ``mcp_api_enabled=True`` without MCP dependencies installed.

    Maintenance notes:
        - Good: gate new protocol surfaces behind explicit boolean flags.
        - Bad: construct a second ``MemoryEngine`` inside this factory.
    """
    mcp_servers = None

    # Create MCP servers first if enabled (we need their lifespans for chaining)
    if mcp_api_enabled:
        try:
            from .mcp import MCPMiddleware, create_mcp_servers

            mcp_servers = create_mcp_servers(memory=memory)
        except ImportError as e:
            logger.error(f"MCP server requested but dependencies not available: {e}")
            logger.error("Install with: pip install atulya-api[mcp]")
            raise

    # Import and create HTTP API if enabled
    if http_api_enabled:
        from .http import create_app as create_http_app

        app = create_http_app(memory=memory, initialize_memory=initialize_memory)
        logger.info("HTTP REST API enabled")
    else:
        # Create minimal FastAPI app
        app = FastAPI(title="Atulya API", version="0.0.7")
        logger.info("HTTP REST API disabled")

    # Add MCP middleware and chain its lifespan if enabled
    if mcp_servers is not None:
        multi_bank_server, single_bank_server, multi_bank_starlette_app, single_bank_starlette_app = mcp_servers

        # Store the original lifespan
        original_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def chained_lifespan(app_instance: FastAPI):
            """Chain both MCP lifespans with the main app lifespan."""
            # Start both MCP lifespans (multi-bank and single-bank)
            async with multi_bank_starlette_app.router.lifespan_context(multi_bank_starlette_app):
                async with single_bank_starlette_app.router.lifespan_context(single_bank_starlette_app):
                    logger.info("MCP lifespans started (multi-bank and single-bank)")
                    # Then start the original app lifespan
                    async with original_lifespan(app_instance):
                        yield
                logger.info("MCP lifespans stopped")

        # Replace the app's lifespan with the chained version
        app.router.lifespan_context = chained_lifespan

        # Add MCP as a wrapping middleware — intercepts /mcp* requests directly,
        # passes everything else through to the FastAPI app. No Starlette Mount
        # means no 307 redirect for /mcp (no trailing slash).
        app.add_middleware(
            MCPMiddleware,
            memory=memory,
            prefix=mcp_mount_path,
            multi_bank_app=multi_bank_starlette_app,
            single_bank_app=single_bank_starlette_app,
            multi_bank_server=multi_bank_server,
            single_bank_server=single_bank_server,
        )

        logger.info(f"MCP server enabled at {mcp_mount_path}/")

    return app


# Re-export commonly used items for backwards compatibility
from .http import (
    CreateBankRequest,
    DispositionTraits,
    MemoryItem,
    RecallRequest,
    RecallResponse,
    RecallResult,
    ReflectRequest,
    ReflectResponse,
    RetainRequest,
)

__all__ = [
    "create_app",
    "RecallRequest",
    "RecallResult",
    "RecallResponse",
    "MemoryItem",
    "RetainRequest",
    "ReflectRequest",
    "ReflectResponse",
    "CreateBankRequest",
    "DispositionTraits",
]
