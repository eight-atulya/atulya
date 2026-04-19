"""test_memory.py — Batch 2 acceptance tests.

All tests except the gated daemon test use `InMemorySubstrate` so CI stays
under one second. The real-daemon round-trip is gated by the env var
ATULYA_CORTEX_RUN_DAEMON_TEST=1 — flip it on a workstation with atulya-embed
configured to verify wiring against the production substrate.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from cortex.bus import Disposition, Intent, MemoryKind, Recollection, Stimulus
from memory import (
    AtulyaSubstrate,
    EpisodicMemory,
    Hippocampus,
    InMemorySubstrate,
    MemoryStore,
    ProceduralMemory,
    Recall,
    SemanticMemory,
    WorkingMemory,
    channel_tag,
    kind_tag,
    sender_tag,
)

# ---------------------------------------------------------------------------
# tag helpers
# ---------------------------------------------------------------------------


def test_kind_tag_format():
    assert kind_tag("episodic") == "cortex:kind:episodic"
    assert kind_tag("semantic") == "cortex:kind:semantic"
    assert kind_tag("procedural") == "cortex:kind:procedural"
    assert kind_tag("emotional") == "cortex:kind:emotional"


def test_channel_and_sender_tag_format():
    assert channel_tag("telegram:123") == "cortex:channel:telegram:123"
    assert sender_tag("user-x") == "cortex:sender:user-x"


# ---------------------------------------------------------------------------
# InMemorySubstrate (fast Protocol implementation)
# ---------------------------------------------------------------------------


def test_in_memory_substrate_satisfies_protocol():
    assert isinstance(InMemorySubstrate(), MemoryStore)


@pytest.mark.asyncio
async def test_in_memory_round_trip():
    sub = InMemorySubstrate()
    stim = Stimulus(channel="tui:local", sender="atulya", text="we shipped delta mode")
    receipt = await sub.encode(stim, kind="episodic")
    assert receipt["ok"] is True
    assert receipt["kind"] == "episodic"
    assert "cortex:kind:episodic" in receipt["tags"]

    rec = await sub.recall("delta mode")
    assert len(rec) == 1
    assert rec[0].kind == "episodic"
    assert "delta mode" in rec[0].text


@pytest.mark.asyncio
async def test_in_memory_skips_empty_text():
    sub = InMemorySubstrate()
    receipt = await sub.encode(Stimulus(channel="tui:local", sender="x", text="   "), kind="semantic")
    assert receipt.get("skipped") is True
    rec = await sub.recall("")
    assert rec == []


@pytest.mark.asyncio
async def test_in_memory_kind_filter_excludes_other_kinds():
    sub = InMemorySubstrate()
    await sub.encode(Stimulus(channel="tui:local", sender="x", text="alpha"), kind="episodic")
    await sub.encode(Stimulus(channel="tui:local", sender="x", text="alpha"), kind="semantic")

    only_episodic = await sub.recall("alpha", kinds=["episodic"])
    assert len(only_episodic) == 1
    assert only_episodic[0].kind == "episodic"

    both = await sub.recall("alpha")
    assert len(both) == 2


@pytest.mark.asyncio
async def test_in_memory_disposition_round_trip():
    sub = InMemorySubstrate()
    assert (await sub.disposition_for("bank-x")).mood == 0.0
    sub.set_disposition("bank-x", Disposition(mood=0.7, arousal=-0.2))
    d = await sub.disposition_for("bank-x")
    assert d.mood == 0.7
    assert d.arousal == -0.2


@pytest.mark.asyncio
async def test_in_memory_budget_caps_results():
    sub = InMemorySubstrate()
    for i in range(50):
        await sub.encode(
            Stimulus(channel="tui:local", sender="x", text=f"item {i} alpha"),
            kind="semantic",
        )
    low = await sub.recall("alpha", budget="low")
    mid = await sub.recall("alpha", budget="mid")
    large = await sub.recall("alpha", budget="large")
    assert len(low) <= 3
    assert len(mid) <= 8
    assert len(large) <= 24
    assert len(large) >= len(mid) >= len(low)


# ---------------------------------------------------------------------------
# Hippocampus + Recall against a mocked AtulyaEmbedded
# ---------------------------------------------------------------------------


def _mock_embedded():
    embedded = MagicMock()
    embedded.aretain = AsyncMock(return_value=MagicMock(model_dump=lambda: {"ok": True}))
    return embedded


@pytest.mark.asyncio
async def test_hippocampus_encode_passes_correct_tags_and_metadata():
    embedded = _mock_embedded()
    hip = Hippocampus(embedded, default_bank="cortex-test")

    stim = Stimulus(
        channel="telegram:42",
        sender="user-7",
        text="ship the brain",
        received_at=datetime(2026, 4, 19, tzinfo=timezone.utc),
    )
    out = await hip.encode(stim, kind="semantic", extra_tags=["sprint:v1"])

    assert out["ok"] is True
    assert out["bank_id"] == "cortex-test"
    assert "cortex:kind:semantic" in out["tags"]
    assert "cortex:channel:telegram:42" in out["tags"]
    assert "cortex:sender:user-7" in out["tags"]
    assert "sprint:v1" in out["tags"]

    embedded.aretain.assert_awaited_once()
    kwargs = embedded.aretain.await_args.kwargs
    assert kwargs["bank_id"] == "cortex-test"
    assert kwargs["content"] == "ship the brain"
    assert kwargs["timestamp"] == datetime(2026, 4, 19, tzinfo=timezone.utc)
    assert kwargs["metadata"] == {"channel": "telegram:42", "sender": "user-7"}
    assert "cortex:kind:semantic" in kwargs["tags"]


@pytest.mark.asyncio
async def test_hippocampus_skips_empty_stimulus_without_substrate_call():
    embedded = _mock_embedded()
    hip = Hippocampus(embedded)
    out = await hip.encode(Stimulus(channel="tui:local", sender="x", text="   "), kind="episodic")
    assert out.get("skipped") is True
    embedded.aretain.assert_not_called()


@pytest.mark.asyncio
async def test_hippocampus_encode_text_for_skill_distill():
    embedded = _mock_embedded()
    hip = Hippocampus(embedded)
    out = await hip.encode_text("how to ship: ...", kind="procedural")
    assert out["ok"] is True
    assert "cortex:kind:procedural" in out["tags"]
    embedded.aretain.assert_awaited_once()


@pytest.mark.asyncio
async def test_recall_maps_kinds_to_substrate_types_and_tags():
    embedded = MagicMock()
    embedded.arecall = AsyncMock(
        return_value=MagicMock(
            results=[
                MagicMock(
                    id="r1",
                    text="match A",
                    type="experience",
                    document_id="doc-1",
                    tags=["cortex:kind:episodic"],
                ),
                MagicMock(
                    id="r2",
                    text="match B",
                    type="world",
                    document_id=None,
                    tags=["cortex:kind:semantic"],
                ),
            ]
        )
    )
    rec = Recall(embedded, default_bank="cortex-test")
    out = await rec.recall("alpha", kinds=["episodic", "semantic"], bank="bank-x", top_k=10)

    embedded.arecall.assert_awaited_once()
    kwargs = embedded.arecall.await_args.kwargs
    assert kwargs["bank_id"] == "bank-x"
    assert kwargs["query"] == "alpha"
    assert sorted(kwargs["types"]) == ["experience", "world"]
    assert kwargs["budget"] == "mid"
    assert "cortex:kind:episodic" in kwargs["tags"]
    assert "cortex:kind:semantic" in kwargs["tags"]

    assert len(out) == 2
    assert out[0].text == "match A"
    assert out[0].kind == "episodic"
    assert out[0].score > out[1].score  # linear decay preserves rank
    assert out[1].kind == "semantic"
    assert out[0].source == "doc-1"
    assert out[1].source == "r2"


@pytest.mark.asyncio
async def test_recall_short_circuits_on_empty_query():
    embedded = MagicMock()
    embedded.arecall = AsyncMock()
    rec = Recall(embedded)
    assert await rec.recall("") == []
    embedded.arecall.assert_not_called()


@pytest.mark.asyncio
async def test_recall_handles_procedural_kind_tag_only():
    """Procedural has no native substrate type; we must still pass the kind tag."""
    embedded = MagicMock()
    embedded.arecall = AsyncMock(return_value=MagicMock(results=[]))
    rec = Recall(embedded)
    await rec.recall("how do I ship?", kinds=["procedural"])
    kwargs = embedded.arecall.await_args.kwargs
    assert kwargs["types"] is None
    assert "cortex:kind:procedural" in kwargs["tags"]


# ---------------------------------------------------------------------------
# Typed routers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_episodic_memory_pins_kind():
    embedded = _mock_embedded()
    embedded.arecall = AsyncMock(return_value=MagicMock(results=[]))
    hip = Hippocampus(embedded)
    rec = Recall(embedded)
    epi = EpisodicMemory(hip, rec)

    await epi.remember(Stimulus(channel="tui:local", sender="x", text="hi"))
    assert "cortex:kind:episodic" in embedded.aretain.await_args.kwargs["tags"]

    await epi.recall_about("hi")
    assert embedded.arecall.await_args.kwargs["types"] == ["experience"]


@pytest.mark.asyncio
async def test_semantic_memory_pins_kind():
    embedded = _mock_embedded()
    embedded.arecall = AsyncMock(return_value=MagicMock(results=[]))
    sem = SemanticMemory(Hippocampus(embedded), Recall(embedded))

    await sem.remember(Stimulus(channel="tui:local", sender="x", text="2+2=4"))
    assert "cortex:kind:semantic" in embedded.aretain.await_args.kwargs["tags"]

    await sem.recall_about("math facts")
    assert embedded.arecall.await_args.kwargs["types"] == ["world"]


@pytest.mark.asyncio
async def test_procedural_memory_skill_helper():
    embedded = _mock_embedded()
    embedded.arecall = AsyncMock(return_value=MagicMock(results=[]))
    proc = ProceduralMemory(Hippocampus(embedded), Recall(embedded))

    await proc.remember_skill("ship", "1) lint 2) test 3) push")
    tags = embedded.aretain.await_args.kwargs["tags"]
    assert "cortex:kind:procedural" in tags
    assert "cortex:skill:ship" in tags


# ---------------------------------------------------------------------------
# WorkingMemory (no substrate dependency)
# ---------------------------------------------------------------------------


def test_working_memory_buffer_appends_in_fifo_order():
    wm = WorkingMemory(turn_buffer=3)
    a = Stimulus(channel="tui:local", sender="x", text="a")
    b = Stimulus(channel="tui:local", sender="x", text="b")
    c = Stimulus(channel="tui:local", sender="x", text="c")
    d = Stimulus(channel="tui:local", sender="x", text="d")
    for s in (a, b, c, d):
        wm.remember_stimulus(s)
    turns = wm.recent_turns("tui:local", "x")
    assert [t[0].text for t in turns] == ["b", "c", "d"]
    assert wm.turn_count("tui:local", "x") == 3


def test_working_memory_attaches_intent_to_last_stimulus():
    wm = WorkingMemory()
    s = Stimulus(channel="tui:local", sender="x", text="ping")
    wm.remember_stimulus(s)
    intent = Intent(
        action=__import__("cortex.bus", fromlist=["Action"]).Action(
            kind="reply", payload={"text": "pong"}
        ),
        channel="tui:local",
        sender="x",
    )
    wm.attach_intent(intent)
    turns = wm.recent_turns("tui:local", "x")
    assert turns[-1][1] is intent


def test_working_memory_isolates_per_channel_per_sender():
    wm = WorkingMemory()
    wm.remember_stimulus(Stimulus(channel="a", sender="1", text="A1"))
    wm.remember_stimulus(Stimulus(channel="a", sender="2", text="A2"))
    wm.remember_stimulus(Stimulus(channel="b", sender="1", text="B1"))
    assert wm.turn_count("a", "1") == 1
    assert wm.turn_count("a", "2") == 1
    assert wm.turn_count("b", "1") == 1
    assert wm.conversation_count() == 3


def test_working_memory_lru_eviction_order():
    wm = WorkingMemory(lru_capacity=3)
    wm.lru_put("k1", 1)
    wm.lru_put("k2", 2)
    wm.lru_put("k3", 3)
    assert wm.lru_get("k1") == 1  # touch k1
    wm.lru_put("k4", 4)  # should evict k2 (least recently used after touch)
    assert wm.lru_get("k1") == 1
    assert wm.lru_get("k2") is None
    assert wm.lru_get("k3") == 3
    assert wm.lru_get("k4") == 4
    assert wm.lru_size() == 3


def test_working_memory_reset_clears_everything():
    wm = WorkingMemory()
    wm.remember_stimulus(Stimulus(channel="a", sender="x", text="hi"))
    wm.lru_put("k", "v")
    wm.reset()
    assert wm.conversation_count() == 0
    assert wm.lru_size() == 0


# ---------------------------------------------------------------------------
# EmotionalMemory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emotional_memory_projects_disposition():
    from memory.emotional import EmotionalMemory

    embedded = MagicMock()
    embedded.get_bank_config.return_value = {
        "config": {
            "disposition_empathy": 80,
            "disposition_skepticism": 20,
            "disposition_literalism": 50,
        }
    }
    em = EmotionalMemory(embedded)
    d = await em.disposition_for("bank-x")
    # empathy 80 -> mood (80-50)/50 = 0.6
    # skepticism 20 -> arousal (20-50)/50 = -0.6
    assert abs(d.mood - 0.6) < 1e-6
    assert abs(d.arousal - (-0.6)) < 1e-6
    assert d.traits["empathy"] == 80.0


@pytest.mark.asyncio
async def test_emotional_memory_returns_neutral_on_failure():
    from memory.emotional import EmotionalMemory

    embedded = MagicMock()
    embedded.get_bank_config.side_effect = RuntimeError("daemon down")
    em = EmotionalMemory(embedded)
    d = await em.disposition_for("bank-x")
    assert d.mood == 0.0
    assert d.arousal == 0.0


# ---------------------------------------------------------------------------
# AtulyaSubstrate composite (mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_atulya_substrate_protocol_satisfied():
    embedded = _mock_embedded()
    embedded.arecall = AsyncMock(return_value=MagicMock(results=[]))
    embedded.get_bank_config = MagicMock(return_value={"config": {}})
    sub = AtulyaSubstrate(embedded)
    assert isinstance(sub, MemoryStore)
    assert isinstance(sub.episodic, EpisodicMemory)
    assert isinstance(sub.semantic, SemanticMemory)
    assert isinstance(sub.procedural, ProceduralMemory)


@pytest.mark.asyncio
async def test_atulya_substrate_routes_to_hippocampus_recall_and_emotional():
    embedded = _mock_embedded()
    embedded.arecall = AsyncMock(return_value=MagicMock(results=[]))
    embedded.get_bank_config = MagicMock(return_value={"config": {"disposition_empathy": 50}})
    sub = AtulyaSubstrate(embedded)

    await sub.encode(Stimulus(channel="tui:local", sender="x", text="hi"), kind="episodic")
    embedded.aretain.assert_awaited_once()

    await sub.recall("hi")
    embedded.arecall.assert_awaited_once()

    d = await sub.disposition_for("bank-x")
    assert isinstance(d, Disposition)
    embedded.get_bank_config.assert_called_with("bank-x")


# ---------------------------------------------------------------------------
# Real-daemon round-trip (gated)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("ATULYA_CORTEX_RUN_DAEMON_TEST") != "1",
    reason="daemon round-trip is gated; set ATULYA_CORTEX_RUN_DAEMON_TEST=1 to run",
)
@pytest.mark.asyncio
async def test_atulya_substrate_real_daemon_roundtrip():
    """Encode + recall against a real atulya-embed daemon.

    Requires:
    - atulya-embed installed
    - ATULYA_CORTEX_RUN_DAEMON_TEST=1
    - LLM provider configured via env (ATULYA_API_LLM_PROVIDER + key) or a
      cortex profile already initialized.
    """

    from atulya import AtulyaEmbedded

    profile = os.environ.get("ATULYA_CORTEX_TEST_PROFILE", "atulya-cortex-test")
    bank = os.environ.get("ATULYA_CORTEX_TEST_BANK", f"cortex-test-{datetime.now(timezone.utc).timestamp():.0f}")

    embedded = AtulyaEmbedded(profile=profile)
    try:
        try:
            embedded.banks.create(bank_id=bank, name="cortex test bank")
        except Exception:
            # bank may already exist from a prior run; ignore
            pass

        sub = AtulyaSubstrate(embedded, default_bank=bank)
        receipt = await sub.encode(
            Stimulus(channel="test:local", sender="cortex-test", text="The Atulya Cortex shipped on April 19 2026."),
            kind="episodic",
        )
        assert receipt.get("ok") is True

        # Recall is best-effort against a real LLM-backed pipeline.
        rec = await sub.recall("when did the Atulya Cortex ship?", kinds=["episodic"])
        assert isinstance(rec, list)
        if rec:
            assert any("April" in r.text or "2026" in r.text for r in rec)
    finally:
        try:
            embedded.banks.delete(bank_id=bank)
        except Exception:
            pass
        embedded.close()
