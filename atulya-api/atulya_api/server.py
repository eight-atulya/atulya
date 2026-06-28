"""
FastAPI ASGI entry point for production and import-string deployments.

Purpose:
    Materialize a process-global ``MemoryEngine`` and expose it through the unified
    FastAPI application returned as ``app``. This is the module uvicorn loads when
    operators use ``uvicorn atulya_api.server:app``.

Trigger path:
    - ``uvicorn atulya_api.server:app`` (production / container default)
    - ``python -m atulya_api.server`` delegates to ``atulya_api.main.main``
    - ``atulya-api`` CLI uses ``main.py`` instead and constructs its own engine

Inputs:
    - Environment variables via ``get_config()`` (see ``atulya_api.config``)
    - Optional extension modules loaded from ``OPERATION_VALIDATOR`` and ``TENANT``
      env vars through ``load_extension``

Outputs / side effects:
    - Module-level ``_memory``: initialized ``MemoryEngine`` (DB pool, migrations,
      embeddings, LLM providers, task backend wiring)
    - Module-level ``app``: FastAPI app from ``create_app(...)`` with HTTP routes
      and optional MCP middleware mounted at ``/mcp``
    - Tenant extension receives ``DefaultExtensionContext`` for schema provisioning
    - Logging configured once at import time via ``config.configure_logging()``

Mutability:
    - ``_memory`` and ``app`` are created at import time and treated as immutable
      for the process lifetime. Workers spawn separate processes with their own copies.

Impact radius:
    - Every HTTP and MCP request in this process flows through ``app`` → routes in
      ``api/http.py`` / ``api/mcp.py`` → ``MemoryEngine`` methods.
    - Changing startup wiring here affects all endpoints, extension hooks, and MCP tools.

Core logic:
    1. Load static server config and configure logging.
    2. Load optional tenant and operation-validator extensions.
    3. Construct ``MemoryEngine`` (migrations controlled by ``run_migrations_on_startup``).
    4. Attach extension context to tenant extension when present.
    5. Build unified app with HTTP enabled and MCP gated by ``config.mcp_enabled``.

Failure modes:
    - Missing MCP optional deps raise ``ImportError`` at import if ``mcp_enabled`` is true.
    - Database / migration failures surface during first request or engine init depending
      on lazy vs eager pool startup inside ``MemoryEngine``.

Maintenance notes:
    - Good: add new extension hooks or pass additional ``create_app`` flags without
      changing route handlers.
    - Bad: perform per-request state on module globals; duplicate engine construction
      in both ``server.py`` and ``main.py`` with divergent parameters.
    - For interactive CLI/dev, prefer ``atulya-api`` in ``main.py`` which supports
      ``--reload``, daemon mode, and CLI overrides.
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
