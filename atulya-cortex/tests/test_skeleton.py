"""test_skeleton.py — Batch 1 acceptance tests.

These tests assert the shape of the skeleton without exercising any real
sensor / motor / memory / LLM. They prove that:
1. The bus types validate.
2. The Cortex stub returns an Intent that round-trips through Action.
3. Every ABC / Protocol can be satisfied by a small in-test stub.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

import pytest

from cortex import (
    Action,
    ActionResult,
    Cortex,
    Disposition,
    Intent,
    MediaRef,
    Recollection,
    Reflex,
    Stimulus,
    Thought,
)
from cortex.cortex import _stub_signature
from memory import MemoryStore
from motors import Motor
from sensors import Sensor

# ---------------------------------------------------------------------------
# Bus type validation
# ---------------------------------------------------------------------------


def test_stimulus_minimal_validates():
    s = Stimulus(channel="tui:local", sender="atulya")
    assert s.channel == "tui:local"
    assert s.text is None
    assert s.media == []
    assert isinstance(s.received_at, datetime)


def test_stimulus_full_validates():
    s = Stimulus(
        channel="telegram:123",
        sender="user-xyz",
        text="ping",
        media=[MediaRef(kind="image", uri="file:///tmp/a.jpg")],
        received_at=datetime(2026, 4, 19, tzinfo=timezone.utc),
        raw={"chat_id": 123},
    )
    assert s.text == "ping"
    assert len(s.media) == 1
    assert s.media[0].kind == "image"
    assert s.raw["chat_id"] == 123


def test_action_kinds_validate():
    for kind in ("reply", "tool_call", "delegate", "noop"):
        Action(kind=kind, payload={})


def test_action_rejects_unknown_kind():
    with pytest.raises(Exception):
        Action(kind="explode", payload={})


def test_intent_carries_envelope():
    intent = Intent(
        action=Action(kind="reply", payload={"text": "hi"}),
        channel="tui:local",
        sender="atulya",
    )
    assert intent.channel == "tui:local"
    assert intent.action.payload["text"] == "hi"


def test_recollection_validates():
    r = Recollection(kind="episodic", text="we met at PyCon", score=0.42, source="bank-x")
    assert r.kind == "episodic"


def test_reflex_decisions_validate():
    for d in ("allow", "deny", "pair", "sandbox"):
        Reflex(decision=d, reason="test")


def test_disposition_defaults():
    d = Disposition()
    assert d.mood == 0.0
    assert d.arousal == 0.0
    assert d.traits == {}


def test_thought_holds_stimulus():
    s = Stimulus(channel="tui:local", sender="a", text="hi")
    t = Thought(stimulus=s)
    assert t.stimulus.text == "hi"
    assert t.recollections == []
    assert t.drafted_action is None


def test_action_result_validates():
    r = ActionResult(ok=True, detail="done")
    assert r.ok is True


def test_extra_fields_forbidden_on_bus_types():
    with pytest.raises(Exception):
        Stimulus(channel="tui:local", sender="a", bogus="field")


# ---------------------------------------------------------------------------
# Cortex stub
# ---------------------------------------------------------------------------


def test_stub_signature_marks_real_loop_in_batch_four():
    sig = _stub_signature()
    assert sig["batch"] >= 4
    assert sig["real_loop"] is True


@pytest.mark.asyncio
async def test_cortex_reflect_echoes_text():
    cortex = Cortex()
    s = Stimulus(channel="tui:local", sender="atulya", text="ping")
    intent = await cortex.reflect(s)
    assert intent.action.kind == "reply"
    assert intent.action.payload["text"] == "hello back: ping"
    assert intent.channel == "tui:local"
    assert intent.sender == "atulya"


@pytest.mark.asyncio
async def test_cortex_reflect_handles_empty_text():
    cortex = Cortex()
    s = Stimulus(channel="tui:local", sender="atulya", text=None)
    intent = await cortex.reflect(s)
    assert intent.action.payload["text"] == "hello back"


@pytest.mark.asyncio
async def test_cortex_reflex_deny_returns_noop():
    cortex = Cortex()
    s = Stimulus(channel="tui:local", sender="atulya", text="ping")
    reflex = Reflex(decision="deny", reason="test deny")
    intent = await cortex.reflect(s, reflex=reflex)
    assert intent.action.kind == "noop"


@pytest.mark.asyncio
async def test_cortex_hold_materializes_thought():
    cortex = Cortex()
    s = Stimulus(channel="tui:local", sender="atulya", text="ping")
    t = await cortex.hold(s)
    assert isinstance(t, Thought)
    assert t.stimulus is s


# ---------------------------------------------------------------------------
# ABC / Protocol satisfiability
# ---------------------------------------------------------------------------


class _StubSensor:
    def __init__(self) -> None:
        self.opened = False
        self.closed = False

    async def awaken(self) -> None:
        self.opened = True

    async def perceive(self) -> AsyncIterator[Stimulus]:
        async def _gen():
            yield Stimulus(channel="stub:local", sender="x", text="hi")

        return _gen()

    async def rest(self) -> None:
        self.closed = True


class _StubMotor:
    def __init__(self) -> None:
        self.acted_with: Intent | None = None

    async def prepare(self) -> None:
        pass

    async def act(self, intent: Intent) -> ActionResult:
        self.acted_with = intent
        return ActionResult(ok=True, detail="stub-acted")

    async def recover(self) -> None:
        pass


class _StubMemory:
    async def encode(self, stimulus, *, kind, bank=None):
        return {"id": "stub", "kind": kind}

    async def recall(self, query, *, budget="mid", kinds=None, bank=None):
        return [
            Recollection(kind="episodic", text=f"stub for {query}", score=0.1, source="stub")
        ]

    async def disposition_for(self, bank: str) -> Disposition:
        return Disposition()


def test_stub_sensor_satisfies_protocol():
    assert isinstance(_StubSensor(), Sensor)


def test_stub_motor_satisfies_protocol():
    assert isinstance(_StubMotor(), Motor)


def test_stub_memory_satisfies_protocol():
    assert isinstance(_StubMemory(), MemoryStore)


@pytest.mark.asyncio
async def test_stub_motor_records_intent():
    motor = _StubMotor()
    intent = Intent(
        action=Action(kind="reply", payload={"text": "hi"}),
        channel="stub:local",
        sender="x",
    )
    result = await motor.act(intent)
    assert result.ok
    assert motor.acted_with is intent


@pytest.mark.asyncio
async def test_stub_memory_round_trip():
    memory = _StubMemory()
    receipt = await memory.encode(
        Stimulus(channel="stub:local", sender="x", text="hi"),
        kind="episodic",
    )
    assert receipt["kind"] == "episodic"
    rec = await memory.recall("hi")
    assert rec[0].text == "stub for hi"
    disp = await memory.disposition_for("bank-x")
    assert disp.mood == 0.0
