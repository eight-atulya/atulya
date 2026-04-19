"""tests/test_memory_brain.py — biomimetic memory: affect, episodes, facts, sleep.

The flow under test mirrors the architecture diagram:
    score_text -> EpisodeStore.append -> Sleep.consolidate -> FactStore.upsert
                                                  ^                  |
                                                  +------ Cortex.reflect ---+
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cortex import Cortex, Stimulus, Utterance
from cortex.affect import Affect, score_text, score_with_augmentor
from cortex.consolidation import Sleep, _parse_facts_json
from cortex.conversation import ConversationStore
from cortex.episodes import Episode, EpisodeStore, render_episode_block
from cortex.semantic_facts import Fact, FactStore, _jaccard

# ---------------------------------------------------------------------------
# affect
# ---------------------------------------------------------------------------


class TestAffect:
    def test_neutral_for_empty(self) -> None:
        a = score_text("")
        assert a == Affect.neutral()

    def test_positive_burst(self) -> None:
        a = score_text("This is amazing! I love it, fantastic work!")
        assert a.valence > 0.4
        assert a.arousal > 0.0
        assert a.salience > 0.3
        assert "love" in a.triggers or "amazing" in a.triggers

    def test_negative_burst(self) -> None:
        a = score_text("I am so frustrated, this is broken and stupid.")
        assert a.valence < -0.4
        assert a.salience > 0.3

    def test_arousal_boosted_by_caps_and_excl(self) -> None:
        a = score_text("URGENT! FIX THIS NOW!!!")
        assert a.arousal > 0.5

    def test_salience_increases_with_question_length(self) -> None:
        short = score_text("ok")
        long_q = score_text(
            "Could you please explain why this matters and how I should "
            "decide between approaches? I'm not sure what's going on."
        )
        assert long_q.salience > short.salience

    def test_to_dict_roundtrip(self) -> None:
        a = score_text("happy")
        d = a.to_dict()
        assert set(d) == {"valence", "arousal", "salience", "triggers"}
        assert isinstance(d["triggers"], list)

    @pytest.mark.asyncio
    async def test_augmentor_can_override(self) -> None:
        async def aug(text: str) -> Affect:
            return Affect(valence=0.99, arousal=0.99, salience=0.99, triggers=("aug",))

        a = await score_with_augmentor("plain text", aug)
        assert a.valence == 0.99 and a.salience == 0.99

    @pytest.mark.asyncio
    async def test_augmentor_failure_falls_back(self) -> None:
        async def boom(text: str) -> Affect:
            raise RuntimeError("boom")

        a = await score_with_augmentor("happy day", boom)
        assert a.valence > 0  # heuristic still ran


# ---------------------------------------------------------------------------
# episodes
# ---------------------------------------------------------------------------


class TestEpisodeStore:
    def test_append_and_recent(self, tmp_path: Path) -> None:
        store = EpisodeStore(tmp_path)
        for i in range(5):
            store.append(
                channel="tui",
                peer="anurag",
                user_text=f"q{i}",
                assistant_text=f"a{i}",
                affect=score_text(f"q{i}"),
            )
        eps = store.recent(channel="tui", peer="anurag", n=3)
        assert [e.user_text for e in eps] == ["q2", "q3", "q4"]

    def test_skip_empty_turns(self, tmp_path: Path) -> None:
        store = EpisodeStore(tmp_path)
        out = store.append(channel="tui", peer="x", user_text="", assistant_text="")
        assert out is None
        assert store.recent(channel="tui", peer="x", n=10) == []

    def test_top_salient_blends_affect_and_recency(self, tmp_path: Path) -> None:
        store = EpisodeStore(tmp_path)
        # Older, very emotional
        store.append(
            channel="tui",
            peer="p",
            user_text="I am furious about this broken bug!",
            assistant_text="ack",
            affect=score_text("I am furious about this broken bug!"),
        )
        # Recent neutral
        for _ in range(3):
            store.append(
                channel="tui",
                peer="p",
                user_text="ok",
                assistant_text="ok",
                affect=score_text("ok"),
            )
        top = store.top_salient(channel="tui", peer="p", n=2)
        # Both the emotional one AND the most-recent should make the cut.
        ids = {e.user_text for e in top}
        assert "I am furious about this broken bug!" in ids

    def test_mark_consolidated_idempotent(self, tmp_path: Path) -> None:
        store = EpisodeStore(tmp_path)
        ep = store.append(channel="tui", peer="p", user_text="q", assistant_text="a")
        assert ep is not None
        n1 = store.mark_consolidated(channel="tui", peer="p", episode_ids=[ep.id])
        n2 = store.mark_consolidated(channel="tui", peer="p", episode_ids=[ep.id])
        assert n1 == 1 and n2 == 0
        eps = store.recent(channel="tui", peer="p", n=10)
        assert eps[0].consolidated is True

    def test_set_digest(self, tmp_path: Path) -> None:
        store = EpisodeStore(tmp_path)
        ep = store.append(channel="tui", peer="p", user_text="q", assistant_text="a")
        assert ep is not None
        assert store.set_digest(channel="tui", peer="p", episode_id=ep.id, digest="hi") is True
        assert store.recent(channel="tui", peer="p", n=1)[0].digest == "hi"

    def test_iter_since_filters_by_ts(self, tmp_path: Path) -> None:
        store = EpisodeStore(tmp_path)
        e1 = store.append(channel="tui", peer="p", user_text="a", assistant_text="x")
        assert e1 is not None
        e2 = store.append(channel="tui", peer="p", user_text="b", assistant_text="y")
        assert e2 is not None
        new = list(store.iter_since(channel="tui", peer="p", ts=e1.ts))
        assert all(e.ts > e1.ts for e in new)

    def test_skips_corrupt_lines(self, tmp_path: Path) -> None:
        store = EpisodeStore(tmp_path)
        store.append(channel="tui", peer="p", user_text="q", assistant_text="a")
        path = store._path("tui", "p")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("not-json\n")
            fh.write("{}\n")  # missing all fields, but valid json -> tolerated
        eps = store.recent(channel="tui", peer="p", n=10)
        assert len(eps) >= 1  # at least the valid one survived

    def test_clear(self, tmp_path: Path) -> None:
        store = EpisodeStore(tmp_path)
        store.append(channel="tui", peer="p", user_text="q", assistant_text="a")
        n = store.clear(channel="tui", peer="p")
        assert n > 0
        assert store.recent(channel="tui", peer="p", n=1) == []

    def test_render_episode_block_handles_empty(self) -> None:
        assert render_episode_block([]) == ""

    def test_render_episode_block_marks_strong(self) -> None:
        ep = Episode(
            id="x",
            ts="2026-04-19T00:00:00+00:00",
            channel="tui",
            peer="p",
            user_text="this is amazing fantastic wonderful",
            assistant_text="",
            tools_used=(),
            affect=score_text("this is amazing fantastic wonderful"),
        )
        block = render_episode_block([ep])
        assert "[strong]" in block or "[notable]" in block


# ---------------------------------------------------------------------------
# facts
# ---------------------------------------------------------------------------


class TestFactStore:
    def test_upsert_creates(self, tmp_path: Path) -> None:
        store = FactStore(tmp_path)
        f = store.upsert("anurag", text="prefers terse replies")
        assert f is not None and f.id
        assert store.facts_for("anurag")[0].text == "prefers terse replies"

    def test_upsert_dedups_similar(self, tmp_path: Path) -> None:
        store = FactStore(tmp_path)
        f1 = store.upsert("anurag", text="prefers terse replies", confidence=0.6)
        f2 = store.upsert("anurag", text="prefers terse replies", confidence=0.6)
        assert f1 is not None and f2 is not None
        assert f1.id == f2.id
        assert f2.confidence > f1.confidence  # bumped on reinforcement

    def test_upsert_keeps_distinct_facts_separate(self, tmp_path: Path) -> None:
        store = FactStore(tmp_path)
        store.upsert("anurag", text="lives in Bangalore")
        store.upsert("anurag", text="works at startup XYZ")
        assert len(store.facts_for("anurag")) == 2

    def test_upsert_skips_empty(self, tmp_path: Path) -> None:
        store = FactStore(tmp_path)
        assert store.upsert("anurag", text="   ") is None
        assert store.facts_for("anurag") == []

    def test_render_for_prompt_filters_low_confidence(self, tmp_path: Path) -> None:
        store = FactStore(tmp_path)
        store.upsert("anurag", text="strong belief", confidence=0.9)
        store.upsert("anurag", text="weak guess", confidence=0.2)
        block = store.render_for_prompt("anurag", min_confidence=0.5)
        assert "strong belief" in block
        assert "weak guess" not in block

    def test_forget_removes_one_fact(self, tmp_path: Path) -> None:
        store = FactStore(tmp_path)
        f = store.upsert("p", text="alpha")
        assert f is not None
        assert store.forget("p", fact_id=f.id) is True
        assert store.facts_for("p") == []

    def test_clear_wipes_peer(self, tmp_path: Path) -> None:
        store = FactStore(tmp_path)
        store.upsert("p", text="alpha")
        n = store.clear("p")
        assert n > 0
        assert store.facts_for("p") == []

    def test_jaccard(self) -> None:
        assert _jaccard("a b c", "a b c") == 1.0
        assert _jaccard("a b", "c d") == 0.0
        assert 0 < _jaccard("a b c", "a b d") < 1


# ---------------------------------------------------------------------------
# consolidation (Sleep)
# ---------------------------------------------------------------------------


class ScriptedLanguage:
    """Minimal stub that returns a queued JSON facts blob."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls = 0

    async def think(self, messages: list[dict[str, Any]], **_kw: Any) -> Utterance:
        self.calls += 1
        text = self._replies.pop(0)
        return Utterance(text=text, provider="stub", model="stub", elapsed_ms=0.0)


def _seed_episodes(store: EpisodeStore, n: int = 5, *, channel: str = "tui", peer: str = "p") -> None:
    texts = [
        "I love terse replies, please be brief.",
        "I work in Bangalore at a startup called Atulya.",
        "My daughter's name is Kuhi.",
        "I prefer dark mode in everything.",
        "I am furious when bugs slip into production!",
    ]
    for i in range(n):
        body = texts[i % len(texts)]
        store.append(
            channel=channel,
            peer=peer,
            user_text=body,
            assistant_text="ok",
            affect=score_text(body),
        )


class TestSleep:
    @pytest.mark.asyncio
    async def test_consolidate_extracts_and_persists_facts(self, tmp_path: Path) -> None:
        episodes = EpisodeStore(tmp_path / "ep")
        facts = FactStore(tmp_path / "fa")
        _seed_episodes(episodes, n=5)
        lang = ScriptedLanguage(
            [
                '{"facts": ['
                '{"text": "prefers terse replies", "tags": ["preference"], "confidence": 0.85},'
                '{"text": "works in Bangalore", "tags": ["identity"], "confidence": 0.8}'
                "]}"
            ]
        )
        sleep = Sleep(
            language=lang,
            episodes=episodes,
            facts=facts,
            state_path=tmp_path / "cursor.json",
            min_episodes=2,
            min_total_salience=0.0,  # don't gate on salience for the test
            cooldown_s=0.0,
        )
        out = await sleep.consolidate(channel="tui", peer="p")
        assert out["status"] == "ok"
        assert out["facts_upserted"] == 2
        stored = {f.text for f in facts.facts_for("p")}
        assert "prefers terse replies" in stored
        assert "works in Bangalore" in stored

    @pytest.mark.asyncio
    async def test_consolidate_skips_when_too_few_episodes(self, tmp_path: Path) -> None:
        episodes = EpisodeStore(tmp_path / "ep")
        facts = FactStore(tmp_path / "fa")
        episodes.append(channel="tui", peer="p", user_text="hi", assistant_text="hi")
        sleep = Sleep(
            language=ScriptedLanguage(["never called"]),
            episodes=episodes,
            facts=facts,
            state_path=tmp_path / "cursor.json",
            min_episodes=10,
            cooldown_s=0.0,
        )
        out = await sleep.consolidate(channel="tui", peer="p")
        assert out["status"] == "skipped_no_episodes"
        assert sleep.language.calls == 0

    @pytest.mark.asyncio
    async def test_consolidate_skips_low_salience(self, tmp_path: Path) -> None:
        episodes = EpisodeStore(tmp_path / "ep")
        facts = FactStore(tmp_path / "fa")
        for _ in range(5):
            episodes.append(
                channel="tui",
                peer="p",
                user_text="ok",
                assistant_text="ok",
                affect=score_text("ok"),
            )
        sleep = Sleep(
            language=ScriptedLanguage(["never called"]),
            episodes=episodes,
            facts=facts,
            state_path=tmp_path / "cursor.json",
            min_episodes=2,
            min_total_salience=0.5,
            cooldown_s=0.0,
        )
        out = await sleep.consolidate(channel="tui", peer="p")
        assert out["status"] == "skipped_low_salience"

    @pytest.mark.asyncio
    async def test_consolidate_advances_cursor(self, tmp_path: Path) -> None:
        episodes = EpisodeStore(tmp_path / "ep")
        facts = FactStore(tmp_path / "fa")
        _seed_episodes(episodes, n=4)
        lang = ScriptedLanguage(['{"facts": []}', '{"facts": []}'])
        sleep = Sleep(
            language=lang,
            episodes=episodes,
            facts=facts,
            state_path=tmp_path / "cursor.json",
            min_episodes=2,
            min_total_salience=0.0,
            cooldown_s=0.0,
        )
        out1 = await sleep.consolidate(channel="tui", peer="p")
        assert out1["status"] == "ok"
        # Second call: no new episodes, so it must skip without LLM cost.
        out2 = await sleep.consolidate(channel="tui", peer="p")
        assert out2["status"] in {"skipped_no_episodes"}
        assert lang.calls == 1  # cursor prevented re-distillation

    @pytest.mark.asyncio
    async def test_consolidate_force_overrides_gates(self, tmp_path: Path) -> None:
        episodes = EpisodeStore(tmp_path / "ep")
        facts = FactStore(tmp_path / "fa")
        episodes.append(channel="tui", peer="p", user_text="hi", assistant_text="hi")
        sleep = Sleep(
            language=ScriptedLanguage(['{"facts": []}']),
            episodes=episodes,
            facts=facts,
            state_path=tmp_path / "cursor.json",
            min_episodes=10,
            min_total_salience=999.0,
            cooldown_s=999.0,
        )
        out = await sleep.consolidate(channel="tui", peer="p", force=True)
        assert out["status"] == "ok"


class TestParseFactsJson:
    def test_strips_fences(self) -> None:
        out = _parse_facts_json('```json\n{"facts": [{"text": "x"}]}\n```')
        assert out and out[0]["text"] == "x"

    def test_handles_prose_around_json(self) -> None:
        out = _parse_facts_json('Sure, here it is: {"facts": [{"text": "y"}]} done.')
        assert out and out[0]["text"] == "y"

    def test_returns_empty_on_garbage(self) -> None:
        assert _parse_facts_json("nope") == []
        assert _parse_facts_json("") == []

    def test_salvages_truncated_reply(self) -> None:
        """Small models often run out of tokens mid-array; we still want
        to recover the well-formed fact objects that DID complete."""

        truncated = (
            '{"facts": [\n'
            '  {"text": "A works in Bangalore", "tags": ["loc"], "confidence": 0.9},\n'
            '  {"text": "A prefers terse replies", "tags": ["pref"], "confidence":'
        )
        out = _parse_facts_json(truncated)
        assert len(out) == 1
        assert out[0]["text"] == "A works in Bangalore"


# ---------------------------------------------------------------------------
# Cortex integration — episodes + facts come into the system prompt
# ---------------------------------------------------------------------------


def _stim(text: str = "hello", *, channel: str = "tui:local") -> Stimulus:
    return Stimulus(channel=channel, sender="anurag", text=text)


@pytest.mark.asyncio
async def test_cortex_writes_episode_after_reflect(tmp_path: Path) -> None:
    lang = ScriptedLanguage(["hi back"])
    episodes = EpisodeStore(tmp_path / "ep")
    facts = FactStore(tmp_path / "fa")
    cortex = Cortex(
        language=lang,
        conversations=ConversationStore(tmp_path / "conv"),
        episodes=episodes,
        facts=facts,
    )
    await cortex.reflect(_stim("I am amazing!"), peer_key="anurag")
    eps = episodes.recent(channel="tui", peer="anurag", n=10)
    assert len(eps) == 1
    assert eps[0].user_text == "I am amazing!"
    assert eps[0].assistant_text == "hi back"
    assert eps[0].affect.salience > 0.0  # affect was scored


@pytest.mark.asyncio
async def test_cortex_injects_facts_into_system_prompt(tmp_path: Path) -> None:
    lang = ScriptedLanguage(["ok"])
    facts = FactStore(tmp_path / "fa")
    facts.upsert("anurag", text="prefers terse replies", confidence=0.9)
    facts.upsert("anurag", text="lives in Bangalore", confidence=0.85)
    cortex = Cortex(
        language=lang,
        episodes=EpisodeStore(tmp_path / "ep"),
        facts=facts,
    )
    await cortex.reflect(_stim("whats up"), peer_key="anurag")
    sys_msg = lang.calls and None  # noqa: F841 — for clarity below
    sent_messages = lang._replies  # already consumed; inspect via call log instead
    # Redo with call recording
    lang2 = ScriptedLanguage(["ok"])
    cortex2 = Cortex(
        language=lang2,
        episodes=EpisodeStore(tmp_path / "ep2"),
        facts=facts,
    )
    await cortex2.reflect(_stim("whats up"), peer_key="anurag")
    # ScriptedLanguage in our integration test stub doesn't store calls;
    # inspect the system prompt by re-running through _build_messages.
    thought = await cortex2.hold(_stim("whats up"))
    msgs = cortex2._build_messages(thought, sandboxed=False, peer_key="anurag")
    sys_text = msgs[0]["content"]
    assert "prefers terse replies" in sys_text
    assert "lives in Bangalore" in sys_text


@pytest.mark.asyncio
async def test_cortex_injects_salient_episode_block(tmp_path: Path) -> None:
    lang = ScriptedLanguage(["ok"])
    episodes = EpisodeStore(tmp_path / "ep")
    # Seed with one strongly emotional past episode.
    episodes.append(
        channel="tui",
        peer="anurag",
        user_text="I am ABSOLUTELY FURIOUS about this terrible bug!!!",
        assistant_text="acknowledged",
        affect=score_text("I am ABSOLUTELY FURIOUS about this terrible bug!!!"),
    )
    cortex = Cortex(
        language=lang,
        episodes=episodes,
        facts=FactStore(tmp_path / "fa"),
        recall_episodes_top_k=2,
    )
    thought = await cortex.hold(_stim("morning"))
    msgs = cortex._build_messages(thought, sandboxed=False, peer_key="anurag")
    sys_text = msgs[0]["content"]
    assert "Salient past episodes" in sys_text


@pytest.mark.asyncio
async def test_cortex_episode_records_tools_used(tmp_path: Path) -> None:
    """When the deliberation arc invokes a tool, the episode log captures it."""

    from cortex.bus import ActionResult, Intent
    from cortex.tool_protocol import ToolSpec

    class FakeHand:
        async def act(self, intent: Intent) -> ActionResult:
            return ActionResult(ok=True, artifact={"tool": "bash", "output": {"stdout": "ok"}})

    lang = ScriptedLanguage(
        [
            '<tool name="bash">{"command":"date"}</tool>',
            "I checked and it's Tuesday.",
        ]
    )
    episodes = EpisodeStore(tmp_path / "ep")
    cortex = Cortex(
        language=lang,
        episodes=episodes,
        facts=FactStore(tmp_path / "fa"),
        hand=FakeHand(),
        tool_specs=(ToolSpec(name="bash", signature="command"),),
        max_actions=2,
    )
    await cortex.reflect(_stim("what day is it?"), peer_key="anurag")
    eps = episodes.recent(channel="tui", peer="anurag", n=10)
    assert len(eps) == 1
    assert "bash" in eps[0].tools_used


@pytest.mark.asyncio
async def test_cortex_no_episodes_when_unwired() -> None:
    """Backward compatible: no episodes/facts wired -> no episode write."""

    lang = ScriptedLanguage(["ok"])
    cortex = Cortex(language=lang)
    # Would crash if cortex tried to call .append on None.
    await cortex.reflect(_stim("hi"), peer_key="anurag")
