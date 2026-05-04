"""Search-engine SERP URLs must not be web_fetch'd."""

import pytest

from cortex.bus import Action, Intent
from motors.fine_motor_skills import Hand, _web_fetch_is_search_engine_serp


@pytest.mark.parametrize(
    "url,blocked",
    [
        ("https://www.google.com/search?q=sytolab", True),
        ("https://google.co.uk/search?q=test", True),
        ("https://www.bing.com/search?q=x", True),
        ("https://duckduckgo.com/?q=sytolab", True),
        ("https://example.com/", False),
        ("https://github.com/org/repo", False),
    ],
)
def test_serp_detection(url: str, blocked: bool) -> None:
    assert _web_fetch_is_search_engine_serp(url) is blocked


@pytest.mark.asyncio
async def test_web_fetch_rejects_google_when_web_search_available() -> None:
    class _FakeStack:
        pass

    hand = Hand(
        safe_root="/tmp",
        internet_stack=_FakeStack(),
        internet_limits={},
        internet_search_enabled=True,
        internet_extract_enabled=False,
    )
    intent = Intent(
        action=Action(
            kind="tool_call",
            payload={"name": "web_fetch", "arguments": {"url": "https://www.google.com/search?q=x"}},
        ),
        channel="tui:local",
        sender="local",
    )
    res = await hand.act(intent)
    assert res.ok is False
    assert res.detail and "web_search" in res.detail


@pytest.mark.asyncio
async def test_web_fetch_google_hint_when_no_web_search_tool() -> None:
    hand = Hand(safe_root="/tmp")
    intent = Intent(
        action=Action(
            kind="tool_call",
            payload={"name": "web_fetch", "arguments": {"url": "https://www.google.com/search?q=x"}},
        ),
        channel="tui:local",
        sender="local",
    )
    res = await hand.act(intent)
    assert res.ok is False
    assert res.detail and "internet_search_enabled" in res.detail


@pytest.mark.asyncio
async def test_web_fetch_allows_example_com() -> None:
    hand = Hand(safe_root="/tmp")
    intent = Intent(
        action=Action(
            kind="tool_call",
            payload={"name": "web_fetch", "arguments": {"url": "https://example.com"}},
        ),
        channel="tui:local",
        sender="local",
    )
    res = await hand.act(intent)
    assert res.ok is True
    out = res.artifact.get("output") or {}
    assert out.get("status") == 200
