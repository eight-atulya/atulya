"""tui.py — the screen-eye sensor.

A `Terminal` is the brain's TUI sensor: it opens the terminal, reads
keystrokes, and yields each typed line as a `Stimulus`. It also holds the
counterpart `print_reply` method that the `Reply` motor calls to render an
Intent back to the screen.

This is the simplest sensor — there is no network, no auth, no pairing.
Naming voice: `Terminal.open_terminal` / `read_keystroke` / `close_terminal`.
"""

from __future__ import annotations

import asyncio
import sys
from typing import AsyncIterator, Callable

from rich.console import Console

from cortex.bus import Stimulus

CHANNEL_PREFIX = "tui:"


class Terminal:
    """The screen-eye sensor. Reads keystrokes from stdin, writes to a Rich console."""

    def __init__(
        self,
        *,
        peer: str = "local",
        prompt: str = "you > ",
        console: Console | None = None,
        input_fn: Callable[[str], str] | None = None,
    ) -> None:
        self._peer = peer
        self._prompt = prompt
        self._console = console or Console()
        self._input = input_fn or self._default_input
        self._open = False
        self._stop = asyncio.Event()

    @property
    def channel(self) -> str:
        return f"{CHANNEL_PREFIX}{self._peer}"

    @property
    def sender(self) -> str:
        return self._peer

    def _default_input(self, prompt: str) -> str:
        sys.stdout.write(prompt)
        sys.stdout.flush()
        return sys.stdin.readline()

    async def awaken(self) -> None:
        if self._open:
            return
        self._open = True
        self._stop.clear()
        self._console.print(f"[dim]terminal awake (channel={self.channel})[/dim]")

    async def perceive(self) -> AsyncIterator[Stimulus]:
        if not self._open:
            await self.awaken()

        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            line = await loop.run_in_executor(None, self._input, self._prompt)
            if line is None:
                break
            text = line.rstrip("\n").rstrip("\r")
            if text == "":
                continue
            if text.strip().lower() in {"/exit", "/quit", ":q"}:
                self._stop.set()
                break
            yield Stimulus(channel=self.channel, sender=self.sender, text=text)

    async def rest(self) -> None:
        if not self._open:
            return
        self._stop.set()
        self._open = False
        self._console.print("[dim]terminal at rest[/dim]")

    def print_reply(self, text: str) -> None:
        """Render an outbound text reply to the terminal. Called by the Reply motor."""

        self._console.print(f"[bold green]atulya >[/bold green] {text}")


__all__ = ["CHANNEL_PREFIX", "Terminal"]
