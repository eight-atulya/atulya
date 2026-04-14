"""Atulya-Pydantic AI: Persistent memory tools for AI agents.

Provides Atulya-backed tools and instructions for Pydantic AI agents,
giving them long-term memory across runs.

Basic usage::

    from atulya_client import Atulya
    from atulya_pydantic_ai import create_atulya_tools, memory_instructions
    from pydantic_ai import Agent

    client = Atulya(base_url="http://localhost:8888")

    agent = Agent(
        "openai:gpt-4o",
        tools=create_atulya_tools(client=client, bank_id="user-123"),
        instructions=[memory_instructions(client=client, bank_id="user-123")],
    )

    result = await agent.run("What do you remember about my preferences?")
"""

from .config import (
    AtulyaPydanticAIConfig,
    configure,
    get_config,
    reset_config,
)
from .errors import AtulyaError
from .tools import create_atulya_tools, memory_instructions

__version__ = "0.8.3"

__all__ = [
    "configure",
    "get_config",
    "reset_config",
    "AtulyaPydanticAIConfig",
    "AtulyaError",
    "create_atulya_tools",
    "memory_instructions",
]
