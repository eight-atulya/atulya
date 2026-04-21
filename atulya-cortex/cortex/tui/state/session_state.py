from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SessionState:
    busy: bool = False
    show_prompt_panel: bool = True
    turn_count: int = 0
    errors: list[str] = field(default_factory=list)
