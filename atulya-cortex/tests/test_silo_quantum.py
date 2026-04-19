"""tests/test_silo_quantum.py — Batch 5 tests.

Covers:
- Silo: LLMCache, EmbeddingCache, StateStore (round-trip + persistence).
- Quantum:
    - Coherence: hits the cache on the second identical call (TTFT win).
    - Entanglement: prefetches recollections; second call returns cached future.
    - Superposition: only idempotent allow-listed tools may speculate;
      rollback cancels in-flight work; commit returns the result.
    - Decoherence: collapse(channel) rolls back exactly the bound specs.
- Tiny TTFT benchmark sanity check (cached call < live call).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import pytest

from cortex.bus import Recollection
from cortex.language import Language, Provider, Utterance
from quantum import (
    SAFE_IDEMPOTENT_TOOLS,
    Coherence,
    Decoherence,
    Entanglement,
    SpeculationDenied,
    Superposition,
    prefix_id_for,
)
from silo import EmbeddingCache, LLMCache, StateStore

# ---------------------------------------------------------------------------
# Silo
# ---------------------------------------------------------------------------


def _make_utterance(text: str = "ok") -> Utterance:
    return Utterance(
        text=text,
        provider="stub",
        model="m",
        elapsed_ms=1.0,
        usage={"total_tokens": 1},
        raw={},
    )


class TestLLMCache:
    def test_round_trip(self, tmp_path: Any) -> None:
        cache = LLMCache(tmp_path / "llm")
        try:
            messages = [{"role": "user", "content": "hi"}]
            assert cache.recall(provider="p", model="m", messages=messages, temperature=0.1) is None
            cache.remember(
                _make_utterance("answer"),
                provider="p",
                model="m",
                messages=messages,
                temperature=0.1,
            )
            got = cache.recall(provider="p", model="m", messages=messages, temperature=0.1)
            assert got is not None
            assert got.text == "answer"
        finally:
            cache.close()

    def test_high_temperature_skips_cache_unless_force(self, tmp_path: Any) -> None:
        cache = LLMCache(tmp_path / "llm")
        try:
            messages = [{"role": "user", "content": "hi"}]
            ok = cache.remember(
                _make_utterance(),
                provider="p",
                model="m",
                messages=messages,
                temperature=0.95,
            )
            assert ok is False
            ok = cache.remember(
                _make_utterance(),
                provider="p",
                model="m",
                messages=messages,
                temperature=0.95,
                force=True,
            )
            assert ok is True
        finally:
            cache.close()

    def test_different_messages_yield_different_keys(self, tmp_path: Any) -> None:
        cache = LLMCache(tmp_path / "llm")
        try:
            cache.remember(
                _make_utterance("one"),
                provider="p",
                model="m",
                messages=[{"role": "user", "content": "a"}],
                temperature=0.1,
            )
            cache.remember(
                _make_utterance("two"),
                provider="p",
                model="m",
                messages=[{"role": "user", "content": "b"}],
                temperature=0.1,
            )
            got_a = cache.recall(
                provider="p",
                model="m",
                messages=[{"role": "user", "content": "a"}],
                temperature=0.1,
            )
            got_b = cache.recall(
                provider="p",
                model="m",
                messages=[{"role": "user", "content": "b"}],
                temperature=0.1,
            )
            assert got_a.text == "one"
            assert got_b.text == "two"
        finally:
            cache.close()


class TestEmbeddingCache:
    def test_round_trip(self, tmp_path: Any) -> None:
        cache = EmbeddingCache(tmp_path / "emb")
        try:
            assert cache.recall(model="m", text="hi") is None
            cache.remember([0.1, 0.2, 0.3], model="m", text="hi")
            got = cache.recall(model="m", text="hi")
            assert got == [0.1, 0.2, 0.3]
        finally:
            cache.close()


class TestStateStore:
    def test_round_trip_and_persistence(self, tmp_path: Any) -> None:
        path = tmp_path / "state.json"
        s = StateStore(path)
        s.remember("dream:tick", 7)
        s.remember("last_consolidation_at", "2025-01-01T00:00:00Z")
        assert s.recall("dream:tick") == 7
        assert sorted(s.keys()) == ["dream:tick", "last_consolidation_at"]
        del s

        s2 = StateStore(path)
        assert s2.recall("dream:tick") == 7
        s2.forget("dream:tick")
        assert s2.recall("dream:tick") is None

    def test_corrupt_file_returns_empty(self, tmp_path: Any) -> None:
        path = tmp_path / "state.json"
        path.write_text("not-json", encoding="utf-8")
        s = StateStore(path)
        assert s.snapshot() == {}


# ---------------------------------------------------------------------------
# Quantum: Coherence
# ---------------------------------------------------------------------------


class TestCoherence:
    @pytest.mark.asyncio
    async def test_second_identical_call_hits_cache(self, tmp_path: Any) -> None:
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(
                200,
                json={
                    "id": "x",
                    "model": "m",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": f"answer-{call_count['n']}"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"total_tokens": 1},
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            lang = Language([Provider(name="p", base_url="http://h/v1", default_model="m")], client=client)
            cache = LLMCache(tmp_path / "llm")
            try:
                co = Coherence(lang, cache)
                msgs = [{"role": "user", "content": "hi"}]
                u1 = await co.think(msgs, temperature=0.1)
                u2 = await co.think(msgs, temperature=0.1)
                assert u1.text == "answer-1"
                assert u2.text == "answer-1"
                assert call_count["n"] == 1
                assert co.stats.hits == 1
                assert co.stats.misses == 1
            finally:
                cache.close()
        finally:
            await client.aclose()

    def test_prefix_id_is_stable_for_same_system(self) -> None:
        a = [{"role": "system", "content": "S"}, {"role": "user", "content": "u1"}]
        b = [{"role": "system", "content": "S"}, {"role": "user", "content": "u2"}]
        c = [{"role": "system", "content": "T"}, {"role": "user", "content": "u1"}]
        assert prefix_id_for(a) == prefix_id_for(b)
        assert prefix_id_for(a) != prefix_id_for(c)


# ---------------------------------------------------------------------------
# Quantum: Entanglement
# ---------------------------------------------------------------------------


class TestEntanglement:
    @pytest.mark.asyncio
    async def test_prefetch_then_get_returns_warm_results(self) -> None:
        calls: list[tuple[str, str]] = []

        async def recall(query: str, kind: str, bank: str | None = None) -> list[Recollection]:
            calls.append((query, kind))
            await asyncio.sleep(0.01)
            return [Recollection(kind=kind, text=f"{kind}:{query}", score=0.9, source="b")]

        ent = Entanglement(recall, kinds=("episodic", "semantic"))
        from cortex.bus import Stimulus

        stim = Stimulus(channel="tui:a", sender="a", text="dragons")
        ent.entangle(stim)
        await asyncio.sleep(0.02)
        assert ent.pending_count == 2
        items = await ent.get(stim, "episodic")
        assert items[0].text == "episodic:dragons"
        items2 = await ent.get(stim, "semantic")
        assert items2[0].text == "semantic:dragons"
        assert sorted(c[1] for c in calls) == ["episodic", "semantic"]
        assert ent.pending_count == 0

    @pytest.mark.asyncio
    async def test_get_without_prefetch_falls_back_to_live_recall(self) -> None:
        calls: list[str] = []

        async def recall(query: str, kind: str, bank: str | None = None) -> list[Recollection]:
            calls.append(kind)
            return [Recollection(kind=kind, text="t", score=0.5, source="b")]

        ent = Entanglement(recall, kinds=("episodic",))
        from cortex.bus import Stimulus

        stim = Stimulus(channel="tui:a", sender="a", text="x")
        items = await ent.get(stim, "episodic")
        assert items[0].text == "t"
        assert calls == ["episodic"]

    @pytest.mark.asyncio
    async def test_aclose_cancels_pending(self) -> None:
        async def recall(query: str, kind: str, bank: str | None = None) -> list[Recollection]:
            await asyncio.sleep(10.0)
            return []

        ent = Entanglement(recall, kinds=("episodic",))
        from cortex.bus import Stimulus

        ent.entangle(Stimulus(channel="tui:a", sender="a", text="hi"))
        assert ent.pending_count == 1
        await ent.aclose()
        assert ent.pending_count == 0


# ---------------------------------------------------------------------------
# Quantum: Superposition + Decoherence
# ---------------------------------------------------------------------------


class TestSuperposition:
    @pytest.mark.asyncio
    async def test_idempotent_speculate_and_commit_returns_result(self) -> None:
        sup = Superposition()

        async def work() -> dict[str, Any]:
            await asyncio.sleep(0.01)
            return {"x": 1}

        spec = sup.speculate(tool="read_file", idempotent=True, work=work)
        result = await sup.commit(spec)
        assert result == {"x": 1}
        assert sup.in_flight == 0
        assert spec.settled

    @pytest.mark.asyncio
    async def test_non_idempotent_is_denied(self) -> None:
        sup = Superposition()

        async def work() -> int:
            return 0

        with pytest.raises(SpeculationDenied):
            sup.speculate(tool="read_file", idempotent=False, work=work)

    @pytest.mark.asyncio
    async def test_non_allowlisted_is_denied(self) -> None:
        sup = Superposition()

        async def work() -> int:
            return 0

        with pytest.raises(SpeculationDenied):
            sup.speculate(tool="bash", idempotent=True, work=work)

    @pytest.mark.asyncio
    async def test_rollback_cancels_in_flight(self) -> None:
        sup = Superposition()
        cancelled = asyncio.Event()

        async def work() -> int:
            try:
                await asyncio.sleep(10.0)
                return 0
            except asyncio.CancelledError:
                cancelled.set()
                raise

        spec = sup.speculate(tool="web_fetch", idempotent=True, work=work)
        await asyncio.sleep(0)
        await sup.rollback(spec)
        assert spec.settled
        assert spec.rolled_back
        assert cancelled.is_set()

    def test_default_allowlist_is_strict(self) -> None:
        assert SAFE_IDEMPOTENT_TOOLS == frozenset({"read_file", "web_fetch"})


class TestDecoherence:
    @pytest.mark.asyncio
    async def test_collapse_rolls_back_only_bound_channel(self) -> None:
        sup = Superposition()
        deco = Decoherence(sup)

        async def slow() -> int:
            await asyncio.sleep(10.0)
            return 0

        s_a1 = sup.speculate(tool="read_file", idempotent=True, work=slow)
        s_a2 = sup.speculate(tool="read_file", idempotent=True, work=slow)
        s_b1 = sup.speculate(tool="web_fetch", idempotent=True, work=slow)
        deco.bind("tui:a", s_a1)
        deco.bind("tui:a", s_a2)
        deco.bind("tui:b", s_b1)
        n = await deco.collapse("tui:a")
        assert n == 2
        assert s_a1.rolled_back and s_a2.rolled_back
        assert not s_b1.rolled_back
        await deco.collapse_all()
        assert s_b1.rolled_back


# ---------------------------------------------------------------------------
# Tiny TTFT benchmark: cached call < live call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coherence_ttft_benchmark(tmp_path: Any) -> None:
    """A tiny benchmark: the second (cached) call must be at least 5x faster
    than the first (mock-with-latency) call. Run in-process so it is fast and
    deterministic on CI; the absolute numbers are noise but the *ratio* is
    the assertion."""

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(
            200,
            json={
                "id": "x",
                "model": "m",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}
                ],
                "usage": {"total_tokens": 1},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(slow_handler))
    try:
        lang = Language([Provider(name="p", base_url="http://h/v1", default_model="m")], client=client)
        cache = LLMCache(tmp_path / "ttft")
        try:
            co = Coherence(lang, cache)
            msgs = [{"role": "user", "content": "hi"}]
            t0 = time.monotonic()
            await co.think(msgs, temperature=0.1)
            t_live = time.monotonic() - t0
            t1 = time.monotonic()
            await co.think(msgs, temperature=0.1)
            t_cached = time.monotonic() - t1
            assert t_cached * 5 < t_live, (
                f"cached call ({t_cached*1000:.1f} ms) should be ≥5x faster "
                f"than live call ({t_live*1000:.1f} ms)"
            )
        finally:
            cache.close()
    finally:
        await client.aclose()
