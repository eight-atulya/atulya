"""
Local MCP server entry point for use with Claude Code (HTTP transport).

This is a thin wrapper around the main atulya-api server that pre-configures
sensible defaults for local use (embedded PostgreSQL via pg0, warning log level).

The full API runs on localhost:8888. Configure Claude Code's MCP settings:
    claude mcp add --transport http atulya http://localhost:8888/mcp/

Or pinned to a specific bank (single-bank mode):
    claude mcp add --transport http atulya http://localhost:8888/mcp/default/

Run with:
    atulya-local-mcp

Or with uvx:
    uvx atulya-api@latest atulya-local-mcp

Environment variables:
    ATULYA_API_LLM_API_KEY: Required. API key for LLM provider.
    ATULYA_API_LLM_PROVIDER: Optional. LLM provider (default: "openai").
    ATULYA_API_LLM_MODEL: Optional. LLM model (default: "gpt-4o-mini").
    ATULYA_API_DATABASE_URL: Optional. Override database URL (default: pg0://atulya-mcp).
"""

import os


def main() -> None:
    """Start the Atulya API server with local defaults."""
    # Set local defaults (only if not already configured by the user)
    os.environ.setdefault("ATULYA_API_DATABASE_URL", "pg0://atulya-mcp")

    from atulya_api.main import main as api_main

    api_main()


if __name__ == "__main__":
    main()
