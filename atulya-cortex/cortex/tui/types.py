from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from cortex.bus import Intent, Stimulus

CortexCallable = Callable[[Stimulus], Awaitable[Intent | None]]


@dataclass
class TuiContext:
    home_root: Path
    profile_name: str
    provider: str
    model: str
    base_url: str
    persona_summary: str
    skills_dir: Path
    pairing_store: Path
    conversations_dir: Path | None = None
    active_channel: str = "tui"
    active_peer: str = "local"
    tool_names: tuple[str, ...] | None = None
    tool_max_actions: int = 0
    episodes_dir: Path | None = None
    facts_dir: Path | None = None
    sleep_now: Callable[..., Awaitable[dict]] | None = None
    system_prompt_provider: Callable[[], Awaitable[str]] | None = None
    extras: dict = field(default_factory=dict)
