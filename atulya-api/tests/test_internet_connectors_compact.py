"""Unit tests for compact internet tool payloads."""

from atulya_api.cortex.internet_connectors import InternetStackClient


def test_truncate_for_tool_inserts_marker() -> None:
    long = "a" * 2000
    out, trunc = InternetStackClient.truncate_for_tool(long, 100)
    assert trunc is True
    assert len(out) <= 100
    assert "truncated" in out


def test_truncate_collapses_blank_lines() -> None:
    raw = "line1\n\n\n\nline2"
    out, trunc = InternetStackClient.truncate_for_tool(raw, 500)
    assert trunc is False
    assert "\n\n\n" not in out
