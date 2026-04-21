from __future__ import annotations

from pathlib import Path

import pytest

from cortex.tui.commands.handlers import cmd_exit, cmd_help, cmd_model, cmd_system
from cortex.tui.types import TuiContext


class _FakeHost:
    def __init__(self, ctx: TuiContext):
        self._ctx = ctx
        self.lines: list[str] = []
        self.rich_count = 0
        self.exited = False

    @property
    def ctx(self) -> TuiContext:
        return self._ctx

    async def append_system(self, text: str) -> None:
        self.lines.append(text)

    async def append_rich(self, renderable) -> None:
        self.rich_count += 1

    async def request_exit(self) -> None:
        self.exited = True


def _ctx() -> TuiContext:
    async def _prompt() -> str:
        return "demo system prompt"

    return TuiContext(
        home_root=Path("/tmp/home"),
        profile_name="default",
        provider="lm_studio",
        model="google/gemma",
        base_url="http://localhost",
        persona_summary="voice: x",
        skills_dir=Path("/tmp/skills"),
        pairing_store=Path("/tmp/pairings.json"),
        system_prompt_provider=_prompt,
    )


@pytest.mark.asyncio
async def test_help_and_model_handlers_emit_text() -> None:
    host = _FakeHost(_ctx())
    await cmd_help(host, "")
    await cmd_model(host, "")
    assert any("/help" in line for line in host.lines)
    assert any("provider=lm_studio" in line for line in host.lines)


@pytest.mark.asyncio
async def test_system_handler_uses_rich_panel() -> None:
    host = _FakeHost(_ctx())
    await cmd_system(host, "")
    assert host.rich_count == 1


@pytest.mark.asyncio
async def test_exit_handler_requests_exit() -> None:
    host = _FakeHost(_ctx())
    await cmd_exit(host, "")
    assert host.exited is True
