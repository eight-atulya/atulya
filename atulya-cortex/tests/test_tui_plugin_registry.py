from __future__ import annotations

from textual.widgets import Static

from cortex.tui.plugins.base import PanelSpec
from cortex.tui.plugins.registry import PluginRegistry


class DummyPanel:
    name = "dummy"

    def build(self):
        return Static("hello")


def test_plugin_registry_register_and_list() -> None:
    registry = PluginRegistry()
    registry.register_panel(PanelSpec(name="dummy", factory=DummyPanel()))
    panels = registry.list_panels()
    assert len(panels) == 1
    assert panels[0].name == "dummy"
