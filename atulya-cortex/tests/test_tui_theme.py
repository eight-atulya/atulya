from __future__ import annotations

from cortex.tui.theme import APP_CSS, TOKENS


def test_theme_has_required_palette_tokens() -> None:
    assert TOKENS["bg"] == "#0B0B0B"
    assert TOKENS["text"] == "#FFFFFF"
    assert TOKENS["primary"] == "#D00000"
    assert TOKENS["accent_yellow"] == "#FFD400"
    assert TOKENS["accent_green"] == "#39FF14"
    assert TOKENS["accent_blue"] == "#1E90FF"


def test_css_contains_key_component_blocks() -> None:
    assert "#chatLog" in APP_CSS
    assert "#promptPane" in APP_CSS
    assert "#telemetryPane" in APP_CSS
