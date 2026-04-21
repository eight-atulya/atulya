from __future__ import annotations

from cortex.tui.commands.registry import CommandRegistry


def test_default_registry_includes_required_commands() -> None:
    reg = CommandRegistry.with_defaults()
    names = {spec.name for spec in reg.list()}
    assert "/help" in names
    assert "/model" in names
    assert "/history" in names
    assert "/sleep" in names
    assert "/system" in names
    assert "/quit" in names


def test_registry_get_unknown_returns_none() -> None:
    reg = CommandRegistry.with_defaults()
    assert reg.get("/not-real") is None
