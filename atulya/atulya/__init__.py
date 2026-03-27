"""
Atulya — a living algorithm for machine intelligence (MI).

This package provides a simple way to run Atulya locally with embedded PostgreSQL.

Easiest way - Embedded client (recommended):
    ```python
    from atulya import AtulyaEmbedded

    # Server starts automatically on first use
    client = AtulyaEmbedded(
        profile="myapp",
        llm_provider="groq",
        llm_api_key="your-api-key",
    )

    # Use immediately - no manual server management needed
    client.retain(bank_id="alice", content="Alice loves AI")
    results = client.recall(bank_id="alice", query="What does Alice like?")
    ```

Manual server management:
    ```python
    from atulya import start_server, AtulyaClient

    # Start server with embedded PostgreSQL (pg0)
    server = start_server(
        llm_provider="groq",
        llm_api_key="your-api-key",
        llm_model="openai/gpt-oss-120b"
    )

    # Create client
    client = AtulyaClient(base_url=server.url)

    # Store memories
    client.retain(bank_id="assistant", content="User prefers Python for data analysis")

    # Search memories
    results = client.recall(bank_id="assistant", query="programming preferences")

    # Generate contextual response
    response = client.reflect(bank_id="assistant", query="What are my interests?")

    # Stop server when done
    server.stop()
    ```

Using context manager:
    ```python
    from atulya import AtulyaServer, AtulyaClient

    with AtulyaServer(llm_provider="groq", llm_api_key="...") as server:
        client = AtulyaClient(base_url=server.url)
        # ... use client ...
    # Server automatically stops
    ```
"""

from .client_wrapper import AtulyaClient
from .embedded import AtulyaEmbedded
from .server import Server as AtulyaServer, start_server

__all__ = [
    "AtulyaServer",
    "start_server",
    "AtulyaClient",
    "AtulyaEmbedded",
]
