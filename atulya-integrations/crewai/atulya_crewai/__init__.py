"""Atulya-CrewAI: Persistent memory for AI agent crews.

Provides a Atulya-backed Storage implementation for CrewAI's
ExternalMemory system, giving your crews long-term memory across runs.

Basic usage::

    from atulya_crewai import configure, AtulyaStorage
    from crewai.memory.external.external_memory import ExternalMemory
    from crewai import Crew

    configure(atulya_api_url="http://localhost:8888")

    crew = Crew(
        agents=[...],
        tasks=[...],
        external_memory=ExternalMemory(
            storage=AtulyaStorage(bank_id="my-crew")
        ),
    )

Per-agent banks::

    storage = AtulyaStorage(
        bank_id="crew-shared",
        per_agent_banks=True,
    )
"""

from .config import (
    AtulyaCrewAIConfig,
    configure,
    get_config,
    reset_config,
)
from .errors import AtulyaError
from .storage import AtulyaStorage
from .tools import AtulyaReflectTool

__version__ = "0.8.2"

__all__ = [
    "configure",
    "get_config",
    "reset_config",
    "AtulyaCrewAIConfig",
    "AtulyaStorage",
    "AtulyaReflectTool",
    "AtulyaError",
]
