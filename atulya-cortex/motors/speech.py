"""speech.py — the `Mouth` motor (text-to-speech).

`Mouth` turns an `Intent.action.payload["text"]` into spoken audio. v1
supports three drivers in fallback order:

1. `pyttsx3` (cross-platform; optional dep `atulya-cortex[voice]`)
2. system `say` binary (macOS)
3. system `espeak` / `spd-say` (linux)

If no driver is available `Mouth.act()` returns a non-fatal `ActionResult`
with `ok=False` and an explanatory detail — the cortex falls back to text.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from typing import Literal

from cortex.bus import ActionResult, Intent

Driver = Literal["pyttsx3", "say", "espeak", "spd-say", "none"]


class Mouth:
    """Text-to-speech motor."""

    def __init__(self, *, driver: Driver | None = None) -> None:
        self._driver: Driver = driver or self._detect_driver()
        self._engine = None

    @staticmethod
    def _detect_driver() -> Driver:
        try:
            import pyttsx3  # noqa: F401

            return "pyttsx3"
        except ImportError:
            pass
        for cand in ("say", "espeak", "spd-say"):
            if shutil.which(cand) is not None:
                return cand  # type: ignore[return-value]
        return "none"

    @property
    def driver(self) -> Driver:
        return self._driver

    async def prepare(self) -> None:
        if self._driver == "pyttsx3" and self._engine is None:
            import pyttsx3  # type: ignore

            self._engine = pyttsx3.init()

    async def recover(self) -> None:
        self._engine = None

    async def act(self, intent: Intent) -> ActionResult:
        started = time.monotonic()
        if intent.action.kind != "speak":
            return ActionResult(
                ok=False,
                detail=f"Mouth motor cannot handle action.kind={intent.action.kind!r}",
                artifact={"elapsed_ms": (time.monotonic() - started) * 1000.0},
            )
        text = str(intent.action.payload.get("text", "")).strip()
        if not text:
            return ActionResult(
                ok=False,
                detail="speak payload missing 'text'",
                artifact={"elapsed_ms": (time.monotonic() - started) * 1000.0},
            )
        if self._driver == "none":
            return ActionResult(
                ok=False,
                detail="no TTS driver available; install atulya-cortex[voice] or `espeak`",
                artifact={"elapsed_ms": (time.monotonic() - started) * 1000.0},
            )
        try:
            if self._driver == "pyttsx3":
                await self._speak_pyttsx3(text)
            else:
                await self._speak_subprocess(text)
        except Exception as exc:
            return ActionResult(
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
                artifact={"elapsed_ms": (time.monotonic() - started) * 1000.0},
            )
        return ActionResult(
            ok=True,
            artifact={
                "driver": self._driver,
                "chars": len(text),
                "elapsed_ms": (time.monotonic() - started) * 1000.0,
            },
        )

    async def _speak_pyttsx3(self, text: str) -> None:
        await self.prepare()

        def _run() -> None:
            assert self._engine is not None
            self._engine.say(text)
            self._engine.runAndWait()

        await asyncio.get_running_loop().run_in_executor(None, _run)

    async def _speak_subprocess(self, text: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            self._driver,
            text,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()


__all__ = ["Driver", "Mouth"]
