"""whatsapp.py — the whatsapp ear sensor.

WhatsApp is the highest-risk sensor: backends churn (unofficial bridges get
banned), so the wire shape is hidden behind the `WhatsAppBackend` Protocol.
Two backends ship in v1:

- `BaileysBackend`        — wraps a Node Baileys subprocess. Default for dev:
                            QR pairing, no business account required.
                            Mirrors openclaw/extensions/whatsapp.
- `WhatsAppCloudBackend`  — direct Meta WhatsApp Cloud API over httpx.
                            Recommended for prod: ban-immune, but requires a
                            registered Meta Business account.

`WhatsAppEar` is the cortex-facing sensor; it is identical regardless of
backend. Switching backends is one config flag.

Naming voice: `WhatsAppEar.tune_in` / `hear` / `tune_out`.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Awaitable, Callable, Protocol, runtime_checkable

from cortex.bus import Stimulus

CHANNEL_PREFIX = "whatsapp:"
StimulusSink = Callable[[Stimulus], Awaitable[None]]


@runtime_checkable
class WhatsAppBackend(Protocol):
    """Contract every WhatsApp transport backend implements."""

    name: str

    async def start(self, sink: StimulusSink) -> None:
        """Connect; for every inbound message build a Stimulus and call `sink(stim)`."""
        ...

    async def stop(self) -> None: ...

    async def send(self, jid: str, text: str) -> None: ...


class WhatsAppEar:
    """The cortex-facing WhatsApp sensor. Backend-agnostic."""

    def __init__(self, backend: WhatsAppBackend) -> None:
        self._backend = backend
        self._queue: asyncio.Queue[Stimulus] = asyncio.Queue()
        self._tuned_in = False

    @property
    def backend_name(self) -> str:
        return getattr(self._backend, "name", type(self._backend).__name__)

    @staticmethod
    def channel_for_jid(jid: str) -> str:
        return f"{CHANNEL_PREFIX}{jid}"

    async def awaken(self) -> None:
        await self.tune_in()

    async def tune_in(self) -> None:
        if self._tuned_in:
            return
        await self._backend.start(self._queue.put)
        self._tuned_in = True

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
        await self._backend.stop()
        self._tuned_in = False

    async def send(self, jid: str, text: str) -> None:
        await self._backend.send(jid, text)


# ---------------------------------------------------------------------------
# Backend: Baileys subprocess
# ---------------------------------------------------------------------------


class BaileysBackend:
    """Baileys (Node) subprocess backend.

    The Node bridge listens on a unix socket / HTTP port and emits inbound
    messages as JSON lines. The Python side sends outbound messages by HTTP
    POST. Detailed wire format mirrors openclaw/extensions/whatsapp; see
    `docs/01_source_mapping.md` for the cite.

    In v1 the bridge binary is bundled separately (we point at it via an env
    var or constructor arg); cortex does not vendor Node.
    """

    name = "baileys"

    def __init__(
        self,
        *,
        bridge_command: list[str] | None = None,
        bridge_url: str = "http://127.0.0.1:7732",
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stderr_sink: Callable[[str], None] | None = None,
    ) -> None:
        self._bridge_command = bridge_command or ["node", "whatsapp-bridge.js"]
        self._bridge_url = bridge_url.rstrip("/")
        self._cwd = cwd
        self._env = env
        self._stderr_sink = stderr_sink
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None

    async def start(self, sink: StimulusSink) -> None:
        if self._process is not None:
            return
        # If the caller didn't hand us an env, fall back to the parent process's
        # env so PATH etc. are inherited. Critically, when the caller DID supply
        # an env (e.g. with CORTEX_WA_AUTH_DIR), we must pass it through —
        # otherwise the bridge silently boots with `./session` and pairs into a
        # different account than the user just QR-scanned.
        self._process = await asyncio.create_subprocess_exec(
            *self._bridge_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd,
            env=self._env,
        )
        self._reader_task = asyncio.create_task(self._read_loop(sink))
        self._stderr_task = asyncio.create_task(self._stderr_loop())

    async def _stderr_loop(self) -> None:
        """Drain the bridge's stderr to the configured sink (or sys.stderr).

        Without this drain the OS pipe buffer fills (~64 KiB) and the Node
        process eventually blocks on its next stderr write. We have to read it
        anyway, so route it somewhere visible by default.
        """

        assert self._process is not None and self._process.stderr is not None
        sink = self._stderr_sink
        if sink is None:
            import sys as _sys

            def _default_sink(line: str) -> None:
                _sys.stderr.write(line if line.endswith("\n") else line + "\n")
                _sys.stderr.flush()

            sink = _default_sink
        while True:
            line = await self._process.stderr.readline()
            if not line:
                return
            try:
                sink(line.decode("utf-8", "replace").rstrip("\n"))
            except Exception:
                continue

    async def _read_loop(self, sink: StimulusSink) -> None:
        assert self._process is not None and self._process.stdout is not None
        import json as _json

        while True:
            line = await self._process.stdout.readline()
            if not line:
                return
            try:
                event = _json.loads(line.decode("utf-8").strip())
            except Exception:
                continue
            text = event.get("body") or event.get("text")
            jid = event.get("from") or event.get("conversationId")
            if not text or not jid:
                continue
            await sink(
                Stimulus(
                    channel=WhatsAppEar.channel_for_jid(jid),
                    sender=str(event.get("from") or jid),
                    text=text,
                    raw=event,
                )
            )

    async def stop(self) -> None:
        for task in (self._reader_task, self._stderr_task):
            if task is not None:
                task.cancel()
        self._reader_task = None
        self._stderr_task = None
        if self._process is not None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass
            self._process = None

    async def send(self, jid: str, text: str) -> None:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._bridge_url}/send",
                json={"to": jid, "text": text},
            )
            # Surface bridge-side errors instead of silently dropping replies.
            # The bridge returns 503 if not yet connected, 500 if Baileys
            # rejects the send (e.g. invalid jid). Either way the user wants
            # to know — without this raise, replies would vanish into the
            # void during partial outages.
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"bridge POST /send failed: {resp.status_code} {resp.text!r}"
                )


# ---------------------------------------------------------------------------
# Backend: Meta WhatsApp Cloud API
# ---------------------------------------------------------------------------


class WhatsAppCloudBackend:
    """Meta WhatsApp Cloud API backend.

    Inbound messages arrive via a webhook the operator configures with Meta;
    we expose `inject_inbound_webhook(payload)` so the operator's webhook
    handler can hand the payload to us. Outbound goes through Meta's
    Graph API. No Node bridge.
    """

    name = "whatsapp-cloud"

    def __init__(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        api_version: str = "v18.0",
    ) -> None:
        if not access_token or not phone_number_id:
            raise ValueError("WhatsAppCloudBackend requires access_token and phone_number_id")
        self._access_token = access_token
        self._phone_number_id = phone_number_id
        self._api_version = api_version
        self._sink: StimulusSink | None = None

    async def start(self, sink: StimulusSink) -> None:
        self._sink = sink

    async def stop(self) -> None:
        self._sink = None

    async def inject_inbound_webhook(self, payload: dict[str, Any]) -> None:
        """Hand a Meta webhook payload to the cortex.

        The operator's HTTP server receives the webhook and calls this. We
        do not stand up a webhook server inside cortex in v1 — that belongs
        to the operator's deployment surface.
        """

        if self._sink is None:
            return
        try:
            entries = payload.get("entry", []) or []
            for entry in entries:
                changes = entry.get("changes", []) or []
                for change in changes:
                    value = change.get("value", {}) or {}
                    messages = value.get("messages", []) or []
                    for message in messages:
                        text = (message.get("text") or {}).get("body")
                        jid = message.get("from")
                        if not text or not jid:
                            continue
                        await self._sink(
                            Stimulus(
                                channel=WhatsAppEar.channel_for_jid(jid),
                                sender=str(jid),
                                text=text,
                                raw=message,
                            )
                        )
        except Exception:
            return

    async def send(self, jid: str, text: str) -> None:
        import httpx

        url = f"https://graph.facebook.com/{self._api_version}/{self._phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "messaging_product": "whatsapp",
            "to": jid,
            "type": "text",
            "text": {"body": text},
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(url, headers=headers, json=body)


__all__ = [
    "BaileysBackend",
    "CHANNEL_PREFIX",
    "WhatsAppBackend",
    "WhatsAppCloudBackend",
    "WhatsAppEar",
]
