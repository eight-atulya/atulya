"""
ASGI entrypoint and process-level wiring for the Atulya API server.

Purpose:
    Bootstrap configuration, extensions, ``MemoryEngine``, and the unified FastAPI
    app (HTTP + optional MCP) for uvicorn or ``python -m atulya_api.server``.

Trigger path:
    - Production: ``uvicorn atulya_api.server:app`` (import string).
    - Direct run: ``__main__`` delegates to ``atulya_api.main`` CLI.
    - Tests may import ``app`` or ``_memory`` for in-process clients.

Inputs:
    - Environment variables via ``get_config()`` (``.env`` loaded in ``config.py``).
    - Optional extensions: ``OPERATION_VALIDATOR``, ``TENANT`` (env class paths).

Outputs:
    - Module-level ``app``: FastAPI ASGI application.
    - Module-level ``_memory``: initialized ``MemoryEngine`` singleton.

Side effects:
    - Configures logging, suppresses third-party deprecation warnings.
    - Sets ``TOKENIZERS_PARALLELISM=false`` for embedding workers.
    - Runs DB migrations when ``run_migrations_on_startup`` is true (idempotent).
    - Sets tenant extension context (DB URL + engine reference) when loaded.

Mutability:
    - ``_memory`` and ``app`` are created at import time — reload restarts process.

Impact radius:
    - Every HTTP/MCP route and background task handler depends on this wiring order.
    - Changing extension load order can break schema provisioning or auth.

Core logic:
    Load config → extensions → engine → ``create_app(memory=..., mcp_enabled=...)``.

Failure modes:
    - Extension import/instantiation failures fail process startup.
    - Migration failures block engine init when migrations enabled.

Maintenance notes:
    Good: add new extension hooks following ``load_extension`` pattern.
    Bad: lazy-init ``MemoryEngine`` inside route handlers — breaks MCP mount and
    extension context setup done here at import time.
"""

import logging
import os
import warnings

# Filter deprecation warnings from third-party libraries
warnings.filterwarnings("ignore", message="websockets.legacy is deprecated")
warnings.filterwarnings("ignore", message="websockets.server.WebSocketServerProtocol is deprecated")

from atulya_api import MemoryEngine
from atulya_api.api import create_app
from atulya_api.config import get_config
from atulya_api.extensions import (
    DefaultExtensionContext,
    OperationValidatorExtension,
    TenantExtension,
    load_extension,
)

# Disable tokenizers parallelism to avoid warnings
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Load configuration and configure logging
config = get_config()
config.configure_logging()

# Load operation validator extension if configured
operation_validator = load_extension("OPERATION_VALIDATOR", OperationValidatorExtension)
if operation_validator:
    logging.info(f"Loaded operation validator: {operation_validator.__class__.__name__}")

# Load tenant extension if configured
tenant_extension = load_extension("TENANT", TenantExtension)
if tenant_extension:
    logging.info(f"Loaded tenant extension: {tenant_extension.__class__.__name__}")

# Create app at module level (required for uvicorn import string)
# MemoryEngine reads configuration from environment variables automatically
# Note: run_migrations=True by default, but migrations are idempotent so safe with workers
_memory = MemoryEngine(
    operation_validator=operation_validator,
    tenant_extension=tenant_extension,
    run_migrations=config.run_migrations_on_startup,
)

# Set extension context on tenant extension (needed for schema provisioning)
if tenant_extension:
    extension_context = DefaultExtensionContext(
        database_url=config.database_url,
        memory_engine=_memory,
    )
    tenant_extension.set_context(extension_context)
    logging.info("Extension context set on tenant extension")

# Create unified app with both HTTP and optionally MCP
app = create_app(
    memory=_memory,
    http_api_enabled=True,
    mcp_api_enabled=config.mcp_enabled,
    mcp_mount_path="/mcp",
    initialize_memory=True,
)


if __name__ == "__main__":
    # When run directly, delegate to the CLI
    from atulya_api.main import main

    main()
