"""tests/test_channels.py — Batch 3 unit + E2E tests.

Covers:
- Sensors: Terminal, TelegramEar (mocked Application), WhatsAppEar with both
  backends (mocked subprocess + httpx).
- Motors: Reply, Mouth (subprocess driver mocked), Hand (real bash + sandbox
  guards), Body (mocked reflector).
- Brainstem: Heartbeat, Breathing, Allowlist, DMPairing, ReflexChain, Router.
- E2E: a stub cortex that echoes; a Terminal stimulus is reflexed -> cortex
  -> Reply, end-to-end.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from brainstem import (
    Allowlist,
    Breathing,
    DMPairing,
    Heartbeat,
    ReflexChain,
    Router,
    RoutingOutcome,
)
from cortex.bus import Action, ActionResult, Intent, Reflex, Stimulus
from motors import Body, Hand, Mouth, Reply
from sensors import (
    BaileysBackend,
    Sensor,
    TelegramEar,
    Terminal,
    WhatsAppCloudBackend,
    WhatsAppEar,
)

# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------


class TestTerminal:
    @pytest.mark.asyncio
    async def test_perceives_keystrokes_until_exit(self) -> None:
        lines = iter(["hello\n", "how are you?\n", "/quit\n"])

        def fake_input(prompt: str) -> str:
            return next(lines)

        term = Terminal(peer="alice", input_fn=fake_input)
        await term.awaken()
        out: list[Stimulus] = []
        async for stim in term.perceive():
            out.append(stim)
        await term.rest()
        assert [s.text for s in out] == ["hello", "how are you?"]
        assert out[0].channel == "tui:alice"
        assert out[0].sender == "alice"

    def test_terminal_satisfies_sensor_protocol(self) -> None:
        assert isinstance(Terminal(peer="x", input_fn=lambda p: ""), Sensor)


class TestTelegramEar:
    @pytest.mark.asyncio
    async def test_pushes_inbound_messages_to_queue(self) -> None:
        app = MagicMock()
        app.initialize = AsyncMock()
        app.start = AsyncMock()
        app.stop = AsyncMock()
        app.shutdown = AsyncMock()
        app.updater = MagicMock()
        app.updater.start_polling = AsyncMock()
        app.updater.stop = AsyncMock()
        app.add_handler = MagicMock()

        ear = TelegramEar(token="fake-token", application=app)
        await ear.tune_in()

        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "hi"
        update.message.caption = None
        update.message.chat = MagicMock(id=42)
        update.message.from_user = MagicMock(id=7, username="bob")
        update.message.message_id = 99

        await ear._on_message(update, MagicMock())
        stim = await asyncio.wait_for(ear.hear(), timeout=1.0)
        assert stim.text == "hi"
        assert stim.channel == "telegram:42"
        assert stim.sender == "7"
        assert stim.raw["chat_id"] == 42
        assert stim.raw["username"] == "bob"

        await ear.tune_out()
        app.stop.assert_awaited()


class TestWhatsAppEar:
    @pytest.mark.asyncio
    async def test_cloud_backend_forwards_webhook_to_queue(self) -> None:
        backend = WhatsAppCloudBackend(access_token="t", phone_number_id="123")
        ear = WhatsAppEar(backend)
        await ear.tune_in()

        await backend.inject_inbound_webhook(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {"from": "5511999", "text": {"body": "hola"}}
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
        )
        stim = await asyncio.wait_for(ear.hear(), timeout=1.0)
        assert stim.text == "hola"
        assert stim.channel == "whatsapp:5511999"
        await ear.tune_out()

    def test_baileys_backend_satisfies_protocol(self) -> None:
        from sensors.whatsapp import WhatsAppBackend

        backend = BaileysBackend(bridge_command=["echo"], bridge_url="http://localhost")
        assert isinstance(backend, WhatsAppBackend)
        assert backend.name == "baileys"


# ---------------------------------------------------------------------------
# Motors
# ---------------------------------------------------------------------------


class TestReply:
    @pytest.mark.asyncio
    async def test_dispatches_to_registered_egress(self) -> None:
        seen: list[tuple[str, str, str]] = []

        async def egress(channel: str, target: str, text: str) -> None:
            seen.append((channel, target, text))

        reply = Reply()
        reply.register("tui", egress)
        intent = Intent(
            action=Action(kind="reply", payload={"text": "hello"}),
            channel="tui:alice",
            sender="alice",
        )
        result = await reply.act(intent)
        assert result.ok is True
        assert seen == [("tui:alice", "alice", "hello")]

    @pytest.mark.asyncio
    async def test_unknown_channel_prefix_is_non_fatal(self) -> None:
        reply = Reply()
        intent = Intent(
            action=Action(kind="reply", payload={"text": "x"}),
            channel="mars:rover",
            sender="rover",
        )
        result = await reply.act(intent)
        assert result.ok is False
        assert "no egress" in (result.detail or "")

    @pytest.mark.asyncio
    async def test_rejects_wrong_kind(self) -> None:
        reply = Reply()
        intent = Intent(
            action=Action(kind="speak", payload={"text": "x"}),
            channel="tui:a",
            sender="a",
        )
        result = await reply.act(intent)
        assert result.ok is False
        assert "Reply motor cannot handle" in (result.detail or "")


class TestMouth:
    @pytest.mark.asyncio
    async def test_no_driver_returns_non_fatal(self) -> None:
        mouth = Mouth(driver="none")
        intent = Intent(
            action=Action(kind="speak", payload={"text": "hi"}),
            channel="tui:a",
            sender="a",
        )
        result = await mouth.act(intent)
        assert result.ok is False
        assert "no TTS driver" in (result.detail or "")

    @pytest.mark.asyncio
    async def test_subprocess_driver_invokes_binary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mouth = Mouth(driver="espeak")
        called: dict[str, Any] = {}

        class FakeProc:
            async def wait(self) -> int:
                return 0

        async def fake_create(*args: Any, **kwargs: Any) -> FakeProc:
            called["args"] = args
            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
        intent = Intent(
            action=Action(kind="speak", payload={"text": "hello world"}),
            channel="tui:a",
            sender="a",
        )
        result = await mouth.act(intent)
        assert result.ok is True
        assert called["args"][0] == "espeak"
        assert called["args"][1] == "hello world"


class TestHand:
    @pytest.mark.asyncio
    async def test_bash_runs_in_safe_root(self, tmp_path: Path) -> None:
        hand = Hand(safe_root=tmp_path)
        intent = Intent(
            action=Action(
                kind="tool_call",
                payload={"name": "bash", "arguments": {"command": "echo hi"}},
            ),
            channel="tui:a",
            sender="a",
        )
        result = await hand.act(intent)
        assert result.ok is True
        assert result.artifact["output"]["exit_code"] == 0
        assert "hi" in result.artifact["output"]["stdout"]

    @pytest.mark.asyncio
    async def test_bash_blocks_dangerous_command(self) -> None:
        hand = Hand()
        intent = Intent(
            action=Action(
                kind="tool_call",
                payload={"name": "bash", "arguments": {"command": "rm -rf / "}},
            ),
            channel="tui:a",
            sender="a",
        )
        result = await hand.act(intent)
        assert result.ok is False
        assert "blocked" in (result.detail or "")

    @pytest.mark.asyncio
    async def test_write_then_read_then_edit_in_safe_root(self, tmp_path: Path) -> None:
        hand = Hand(safe_root=tmp_path)
        target = tmp_path / "hello.txt"

        async def call(name: str, args: dict[str, Any]) -> ActionResult:
            return await hand.act(
                Intent(
                    action=Action(kind="tool_call", payload={"name": name, "arguments": args}),
                    channel="tui:a",
                    sender="a",
                )
            )

        write_res = await call("write_file", {"path": str(target), "content": "hello world"})
        assert write_res.ok is True
        read_res = await call("read_file", {"path": str(target)})
        assert read_res.ok is True
        assert read_res.artifact["output"]["text"] == "hello world"
        edit_res = await call("edit_file", {"path": str(target), "old": "world", "new": "cortex"})
        assert edit_res.ok is True
        assert (tmp_path / "hello.txt").read_text() == "hello cortex"

    @pytest.mark.asyncio
    async def test_safe_root_blocks_escape(self, tmp_path: Path) -> None:
        hand = Hand(safe_root=tmp_path)
        outside = tmp_path.parent / "outside.txt"
        result = await hand.act(
            Intent(
                action=Action(
                    kind="tool_call",
                    payload={"name": "write_file", "arguments": {"path": str(outside), "content": "x"}},
                ),
                channel="tui:a",
                sender="a",
            )
        )
        assert result.ok is False
        assert "escapes safe_root" in (result.detail or "")

    @pytest.mark.asyncio
    async def test_unknown_tool(self) -> None:
        hand = Hand()
        result = await hand.act(
            Intent(
                action=Action(kind="tool_call", payload={"name": "nope", "arguments": {}}),
                channel="tui:a",
                sender="a",
            )
        )
        assert result.ok is False
        assert "unknown tool" in (result.detail or "")


class TestBody:
    @pytest.mark.asyncio
    async def test_delegates_to_reflector(self) -> None:
        async def reflector(stim: Stimulus) -> str:
            return f"sub-answered: {stim.text}"

        body = Body(reflector)
        result = await body.act(
            Intent(
                action=Action(kind="delegate", payload={"goal": "summarize the meeting"}),
                channel="tui:a",
                sender="a",
            )
        )
        assert result.ok is True
        assert "sub-answered" in result.artifact["answer"]
        assert result.artifact["subagent_channel"].startswith("subagent:")

    @pytest.mark.asyncio
    async def test_empty_goal_rejected(self) -> None:
        async def reflector(stim: Stimulus) -> str:
            return ""

        body = Body(reflector)
        result = await body.act(
            Intent(
                action=Action(kind="delegate", payload={"goal": ""}),
                channel="tui:a",
                sender="a",
            )
        )
        assert result.ok is False


# ---------------------------------------------------------------------------
# Brainstem
# ---------------------------------------------------------------------------


class TestHeartbeat:
    @pytest.mark.asyncio
    async def test_pulse_fires_all_callbacks(self) -> None:
        hb = Heartbeat(interval_s=10.0)
        seen: list[str] = []

        async def cb_a() -> None:
            seen.append("a")

        async def cb_b() -> None:
            seen.append("b")

        hb.register("a", cb_a)
        hb.register("b", cb_b)
        await hb.pulse()
        assert sorted(seen) == ["a", "b"]
        assert hb.pulse_count == 1

    @pytest.mark.asyncio
    async def test_one_failing_callback_does_not_break_pulse(self) -> None:
        hb = Heartbeat(interval_s=10.0)
        seen: list[str] = []

        async def cb_ok() -> None:
            seen.append("ok")

        async def cb_bad() -> None:
            raise RuntimeError("boom")

        hb.register("ok", cb_ok)
        hb.register("bad", cb_bad)
        await hb.pulse()
        assert seen == ["ok"]


class TestBreathing:
    def test_token_budget_consumes_and_replenishes(self) -> None:
        b = Breathing(token_budget=100, window_s=60.0, per_channel_burst=100)
        assert b.may_speak("tui:a", 30) is True
        assert b.may_speak("tui:a", 30) is True
        assert b.remaining_tokens() == 40
        assert b.may_speak("tui:a", 50) is False  # would exceed 100

    def test_per_channel_rate_limits_burst(self) -> None:
        b = Breathing(
            token_budget=10**9,
            window_s=3600.0,
            per_channel_rate_per_s=1.0,
            per_channel_burst=2,
        )
        assert b.may_speak("tui:a") is True
        assert b.may_speak("tui:a") is True
        assert b.may_speak("tui:a") is False

    def test_inhale_returns_tokens(self) -> None:
        b = Breathing(token_budget=100, window_s=60.0, per_channel_burst=100)
        assert b.may_speak("tui:a", 60) is True
        b.inhale(50)
        assert b.remaining_tokens() == 90


class TestAllowlist:
    @pytest.mark.asyncio
    async def test_allow_deny_default(self) -> None:
        al = Allowlist(allow=["tui:*"], deny=["telegram:spam"], default_decision="pair")
        assert (await al.evaluate(Stimulus(channel="tui:alice", sender="alice"))).decision == "allow"
        assert (await al.evaluate(Stimulus(channel="telegram:spam", sender="x"))).decision == "deny"
        assert (await al.evaluate(Stimulus(channel="whatsapp:55", sender="x"))).decision == "pair"


class TestDMPairing:
    @pytest.mark.asyncio
    async def test_first_message_pairs_then_approve_allows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / "pairings.json"
            pair = DMPairing(store)
            stim = Stimulus(channel="telegram:99", sender="99")
            r1 = await pair.evaluate(stim)
            assert r1.decision == "pair"
            assert pair.status("telegram:99") == "pending"
            pair.approve("telegram:99")
            r2 = await pair.evaluate(stim)
            assert r2.decision == "allow"
            data = json.loads(store.read_text())
            assert data["telegram:99"]["status"] == "approved"


class TestReflexChain:
    @pytest.mark.asyncio
    async def test_first_non_allow_wins(self) -> None:
        async def always_allow(stim: Stimulus) -> Reflex:
            return Reflex(decision="allow", reason="ok")

        async def always_deny(stim: Stimulus) -> Reflex:
            return Reflex(decision="deny", reason="no")

        class A:
            async def evaluate(self, stim: Stimulus) -> Reflex:
                return await always_allow(stim)

        class D:
            async def evaluate(self, stim: Stimulus) -> Reflex:
                return await always_deny(stim)

        chain = ReflexChain([A(), D(), A()])
        result = await chain.evaluate(Stimulus(channel="tui:a", sender="a"))
        assert result.decision == "deny"

    @pytest.mark.asyncio
    async def test_empty_chain_allows(self) -> None:
        chain = ReflexChain([])
        result = await chain.evaluate(Stimulus(channel="tui:a", sender="a"))
        assert result.decision == "allow"


# ---------------------------------------------------------------------------
# E2E: Terminal -> ReflexChain -> Stub Cortex -> Reply -> egress
# ---------------------------------------------------------------------------


class TestEchoE2E:
    @pytest.mark.asyncio
    async def test_terminal_to_reply_round_trip(self) -> None:
        captured: list[tuple[str, str, str]] = []

        async def egress(channel: str, target: str, text: str) -> None:
            captured.append((channel, target, text))

        reply = Reply({"tui": egress})
        reflexes = ReflexChain([Allowlist(allow=["tui:*"], default_decision="deny")])

        async def stub_cortex(stim: Stimulus, reflex: Reflex) -> Intent:
            return Intent(
                action=Action(kind="reply", payload={"text": f"echo: {stim.text}"}),
                channel=stim.channel,
                sender=stim.sender,
            )

        async def reply_motor(intent: Intent) -> ActionResult:
            return await reply.act(intent)

        router = Router(reflexes=reflexes, cortex=stub_cortex, reply_motor=reply_motor)
        outcome: RoutingOutcome = await router.route(
            Stimulus(channel="tui:alice", sender="alice", text="ping")
        )
        assert outcome.reflex.decision == "allow"
        assert outcome.intent is not None
        assert outcome.intent.action.payload["text"] == "echo: ping"
        assert captured == [("tui:alice", "alice", "echo: ping")]
        assert outcome.motor_result.ok is True

    @pytest.mark.asyncio
    async def test_pair_decision_emits_pairing_reply(self) -> None:
        captured: list[str] = []

        async def egress(channel: str, target: str, text: str) -> None:
            captured.append(text)

        reply = Reply({"telegram": egress})
        with tempfile.TemporaryDirectory() as td:
            pairing = DMPairing(Path(td) / "p.json")
            reflexes = ReflexChain([pairing])

            async def stub_cortex(stim: Stimulus, reflex: Reflex) -> Intent:
                raise AssertionError("cortex should not be called on pair decision")

            async def reply_motor(intent: Intent) -> ActionResult:
                return await reply.act(intent)

            router = Router(
                reflexes=reflexes,
                cortex=stub_cortex,
                reply_motor=reply_motor,
                pairing_message="please approve me",
            )
            outcome = await router.route(
                Stimulus(channel="telegram:42", sender="42", text="hi")
            )
            assert outcome.reflex.decision == "pair"
            assert captured == ["please approve me"]

    @pytest.mark.asyncio
    async def test_deny_drops_silently(self) -> None:
        captured: list[str] = []

        async def egress(channel: str, target: str, text: str) -> None:
            captured.append(text)

        reply = Reply({"tui": egress})
        reflexes = ReflexChain([Allowlist(deny=["tui:bad"], default_decision="allow")])

        cortex_called = False

        async def stub_cortex(stim: Stimulus, reflex: Reflex) -> Intent:
            nonlocal cortex_called
            cortex_called = True
            raise AssertionError("cortex should not be called on deny")

        router = Router(
            reflexes=reflexes,
            cortex=stub_cortex,
            reply_motor=lambda i: reply.act(i),  # type: ignore[arg-type]
        )
        outcome = await router.route(Stimulus(channel="tui:bad", sender="bad", text="x"))
        assert outcome.reflex.decision == "deny"
        assert cortex_called is False
        assert captured == []
