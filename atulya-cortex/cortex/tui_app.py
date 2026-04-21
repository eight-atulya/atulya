"""Compatibility shim for the new Textual-based TUI.

`cli_commands/chat.py` imports `TuiContext` and `run_tui` from this module.
To keep runtime contracts stable, this file now forwards those symbols into
the modular `cortex.tui` package.
"""

from __future__ import annotations

from pathlib import Path

from cortex.tui import CortexCallable, TuiContext, run_textual_tui

ATULYA_LOGO = "ATULYA CORTEX"


async def run_tui(*, cortex_call: CortexCallable, ctx: TuiContext, history_path: Path, peer: str = "local") -> None:
    await run_textual_tui(cortex_call=cortex_call, ctx=ctx, history_path=history_path, peer=peer)


__all__ = ["ATULYA_LOGO", "TuiContext", "CortexCallable", "run_tui"]
