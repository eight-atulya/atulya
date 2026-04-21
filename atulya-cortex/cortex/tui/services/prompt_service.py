from __future__ import annotations

from cortex.tui.types import TuiContext


class PromptService:
    def __init__(self, ctx: TuiContext) -> None:
        self._ctx = ctx

    async def current(self) -> str:
        if self._ctx.system_prompt_provider is None:
            return "system prompt inspector is not available in this session."
        try:
            text = await self._ctx.system_prompt_provider()
        except Exception as exc:
            return f"system prompt failed: {exc}"
        return text.strip() or "(empty system prompt)"
