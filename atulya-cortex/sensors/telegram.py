"""telegram.py — the telegram ear sensor.

`TelegramEar` listens for inbound Telegram messages via long-polling and
yields them as `Stimulus`. It uses `python-telegram-bot` (PTB) lazily so
cortex stays importable when the optional dependency is not installed.

Naming voice: `TelegramEar.tune_in` / `hear` / `tune_out`.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from cortex.bus import Stimulus

CHANNEL_PREFIX = "telegram:"


class TelegramEar:
    """Telegram inbound sensor. Long-poll only in v1 (no webhooks)."""

    def __init__(
        self,
        *,
        token: str,
        application: Any | None = None,
    ) -> None:
        if not token:
            raise ValueError("TelegramEar requires a bot token")
        self._token = token
        self._application = application
        self._queue: asyncio.Queue[Stimulus] = asyncio.Queue()
        self._tuned_in = False

    @staticmethod
    def channel_for_chat(chat_id: int | str) -> str:
        return f"{CHANNEL_PREFIX}{chat_id}"

    async def awaken(self) -> None:
        await self.tune_in()

    async def tune_in(self) -> None:
        if self._tuned_in:
            return

        if self._application is None:
            self._application = _build_application(self._token, self._on_message)
        else:
            _attach_handler(self._application, self._on_message)

        await self._application.initialize()
        await self._application.start()
        await self._application.updater.start_polling()
        self._tuned_in = True

    async def _on_message(self, update: Any, context: Any) -> None:  # noqa: ARG002
        message = getattr(update, "message", None) or getattr(update, "channel_post", None)
        if message is None:
            return
        text = getattr(message, "text", None) or getattr(message, "caption", None)
        if not text:
            return
        chat_id = getattr(getattr(message, "chat", None), "id", None) or getattr(message, "chat_id", None)
        from_user = getattr(message, "from_user", None)
        sender_id = str(getattr(from_user, "id", "")) if from_user is not None else str(chat_id)
        await self._queue.put(
            Stimulus(
                channel=self.channel_for_chat(chat_id),
                sender=sender_id,
                text=text,
                raw={
                    "chat_id": chat_id,
                    "from_user_id": getattr(from_user, "id", None) if from_user else None,
                    "username": getattr(from_user, "username", None) if from_user else None,
                    "message_id": getattr(message, "message_id", None),
                },
            )
        )

    async def perceive(self) -> AsyncIterator[Stimulus]:
        if not self._tuned_in:
            await self.tune_in()
        while True:
            stim = await self._queue.get()
            yield stim

    async def hear(self) -> Stimulus:
        if not self._tuned_in:
            await self.tune_in()
        return await self._queue.get()

    async def rest(self) -> None:
        await self.tune_out()

    async def tune_out(self) -> None:
        if not self._tuned_in:
            return
        try:
            await self._application.updater.stop()
        finally:
            try:
                await self._application.stop()
            finally:
                await self._application.shutdown()
                self._tuned_in = False

    async def send(self, chat_id: int | str, text: str, *, message_thread_id: int | None = None) -> None:
        """Outbound send — used by the Reply motor."""

        if self._application is None:
            self._application = _build_application(self._token, self._on_message)
        bot = self._application.bot
        await bot.send_message(chat_id=chat_id, text=text, message_thread_id=message_thread_id)


def _build_application(token: str, handler: Any) -> Any:
    """Lazily import python-telegram-bot and build an Application."""

    try:
        from telegram.ext import Application, MessageHandler, filters
    except ImportError as exc:  # pragma: no cover - optional dep
        raise ImportError(
            "TelegramEar requires python-telegram-bot. Install with `uv pip install "
            "atulya-cortex[telegram]` or `pip install python-telegram-bot`."
        ) from exc

    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.ALL, handler))
    return app


def _attach_handler(application: Any, handler: Any) -> None:
    try:
        from telegram.ext import MessageHandler, filters
    except ImportError:  # pragma: no cover - optional dep
        return
    application.add_handler(MessageHandler(filters.ALL, handler))


__all__ = ["CHANNEL_PREFIX", "TelegramEar"]
