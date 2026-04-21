from __future__ import annotations

from collections.abc import Iterable

from cortex.tui.plugins.base import PanelSpec


class PluginRegistry:
    def __init__(self) -> None:
        self._panels: dict[str, PanelSpec] = {}

    def register_panel(self, spec: PanelSpec) -> None:
        self._panels[spec.name] = spec

    def list_panels(self) -> tuple[PanelSpec, ...]:
        return tuple(self._panels.values())

    def load_builtin(self, specs: Iterable[PanelSpec]) -> None:
        for spec in specs:
            self.register_panel(spec)
