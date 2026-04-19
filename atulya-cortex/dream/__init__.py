"""dream — background consolidation.

Two organs:
- `consolidation.py` — heartbeat-triggered delta-mode mental model refresh
                       (uses the feature shipped in the previous sprint)
- `skill_distill.py` — distill successful runs into a new lesson under
                       `atulya-cortex/life/40_knowledge/17_lessons_learned/`
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Dreamer(Protocol):
    """Anything that runs in the background between turns."""

    async def dream(self) -> None: ...


from dream.consolidation import Consolidation, ConsolidationStats  # noqa: E402
from dream.skill_distill import (  # noqa: E402
    DEFAULT_LESSONS_SUBDIR,
    DistillStats,
    SkillDistill,
)

__all__ = [
    "Consolidation",
    "ConsolidationStats",
    "DEFAULT_LESSONS_SUBDIR",
    "DistillStats",
    "Dreamer",
    "SkillDistill",
]
