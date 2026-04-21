from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from textual.widget import Widget


class PanelPlugin(Protocol):
    name: str

    def build(self) -> Widget: ...


@dataclass(frozen=True)
class PanelSpec:
    name: str
    factory: PanelPlugin
