"""tests/test_conversation.py — working-memory transcripts (Phase 1).

Covers `cortex/conversation.py` standalone and its integration with
`Cortex.reflect(peer_key=...)`:

- `ConversationStore.open` returns a stable handle per (channel, peer)
- `Conversation.append` writes JSONL atomically and round-trips via .recent
- `.recent` honors both `turns` and `char_budget` from the front
- `.clear` removes the file and reports bytes wiped
- `.recent` skips malformed lines (corruption resilience)
- `_safe_stem` keeps WhatsApp-style ids readable; hashes pathological ones
- `Cortex.reflect(peer_key=...)` injects history into the system prompt and
  appends both halves of the new exchange after the LLM call
- `peer_key=None` keeps the original stateless behaviour (regression guard)
- Per-peer identity hint fires for non-tui channels and stays out of the
  prompt for the local TUI
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cortex import Cortex, Stimulus, Utterance
from cortex.conversation import (
    Conversation,
    ConversationStore,
    Turn,
    _safe_stem,
    render_history_block,
)

# ---------------------------------------------------------------------------
# ConversationStore + Conversation
# ---------------------------------------------------------------------------


class TestSafeStem:
    def test_keeps_alnum_and_at(self) -> None:
        assert _safe_stem("919999@s.whatsapp.net") == "919999@s.whatsapp.net"

    def test_replaces_unsafe_chars(self) -> None:
        assert _safe_stem("a/b\\c d") == "a_b_c_d"

    def test_lid_jids_are_safe(self) -> None:
        # Baileys @lid jids contain a colon; we collapse it to underscore
        assert _safe_stem("255400280637643@lid") == "255400280637643@lid"

    def test_hashes_when_too_long(self) -> None:
        # Sha-suffixed when over the cap; deterministic.
        long_id = "x" * 200
        out = _safe_stem(long_id)
        assert len(out) <= 96
        assert out == _safe_stem(long_id)

    def test_empty_falls_back(self) -> None:
        assert _safe_stem("") == "_"


class TestConversationRoundTrip:
    def test_append_and_recent_round_trip(self, tmp_path: Path) -> None:
        store = ConversationStore(tmp_path)
        conv = store.open("whatsapp", "919999@s.whatsapp.net")
        conv.append("user", "hello")
        conv.append("assistant", "hi there")
        conv.append("user", "what's my name?")
        conv.append("assistant", "you didn't tell me yet")

        recent = conv.recent(turns=10, char_budget=10_000)
        roles = [t.role for t in recent]
        contents = [t.content for t in recent]
        assert roles == ["user", "assistant", "user", "assistant"]
        assert contents == ["hello", "hi there", "what's my name?", "you didn't tell me yet"]
        # File lands under <root>/whatsapp/<sanitised_jid>.jsonl
        assert conv.path.exists()
        assert conv.path.parent.name == "whatsapp"

    def test_recent_trims_by_turn_count(self, tmp_path: Path) -> None:
        store = ConversationStore(tmp_path)
        conv = store.open("tui", "local")
        for i in range(20):
            conv.append("user", f"msg{i}")
        recent = conv.recent(turns=5, char_budget=10_000)
        # We keep the most recent 5 turns and drop the older ones.
        assert [t.content for t in recent] == [f"msg{i}" for i in range(15, 20)]

    def test_recent_trims_by_char_budget(self, tmp_path: Path) -> None:
        store = ConversationStore(tmp_path)
        conv = store.open("tui", "local")
        # 10 turns of 200 chars each = 2000 chars total; budget=500 keeps ~3
        long = "x" * 200
        for _ in range(10):
            conv.append("user", long)
        recent = conv.recent(turns=100, char_budget=500)
        # Two or three turns survive; the exact count depends on whether the
        # last accepted turn brings us *exactly* to the budget. Either is OK.
        assert 2 <= len(recent) <= 3
        assert all(t.content == long for t in recent)

    def test_tool_scratchpad_does_not_evict_identity_turn(self, tmp_path: Path) -> None:
        """Regression: on WhatsApp, two bash calls used to silently halve
        the replay window, pushing "I'm Anurag" out of scope before the
        model could recall the peer's name. The default recent() path
        must skip phase=act/observe rows so the bounded window stays
        populated with real dialogue."""

        store = ConversationStore(tmp_path)
        conv = store.open("whatsapp", "919999@s.whatsapp.net")
        # The original exchange that *should* be remembered.
        conv.append("user", "I'm Anurag")
        conv.append("assistant", "Well hello Anurag!")
        # Two bash-backed turns, each adding an act + observe pair on
        # top of the user-facing exchange. Without the fix this blows
        # through a turns=8 budget and evicts the "I'm Anurag" pair.
        for i in range(2):
            conv.append("user", f"run diag {i}")
            conv.append(
                "assistant",
                '<tool name="bash">{"command":"ip a"}</tool>',
                meta={"phase": "act", "iteration": 0, "tool": "bash"},
            )
            conv.append(
                "tool",
                "<tool_result>...big ip a output...</tool_result>",
                meta={"phase": "observe", "iteration": 0, "tool": "bash"},
            )
            conv.append("assistant", f"Here are the results for diag {i}.")

        recent = conv.recent(turns=8, char_budget=10_000)
        contents = [t.content for t in recent]
        assert "I'm Anurag" in contents, (
            "identity turn was evicted by tool-call scratchpad — "
            "the bug this test guards against"
        )
        assert "Well hello Anurag!" in contents
        # And none of the intermediate scratchpad leaks into the replay.
        assert not any(c.startswith('<tool name="bash"') for c in contents)
        assert not any(c.startswith("<tool_result") for c in contents)

    def test_recent_filters_roles(self, tmp_path: Path) -> None:
        store = ConversationStore(tmp_path)
        conv = store.open("tui", "local")
        conv.append("user", "u1")
        conv.append("system", "s1")  # system stays in file but filtered out
        conv.append("assistant", "a1")
        recent = conv.recent(turns=10, char_budget=1_000)
        assert [t.role for t in recent] == ["user", "assistant"]
        # Including system explicitly works.
        recent_with_sys = conv.recent(turns=10, char_budget=1_000, roles=("user", "assistant", "system"))
        assert [t.role for t in recent_with_sys] == ["user", "system", "assistant"]

    def test_empty_or_unknown_role_is_dropped(self, tmp_path: Path) -> None:
        store = ConversationStore(tmp_path)
        conv = store.open("tui", "local")
        conv.append("user", "")  # empty content => no-op
        conv.append("user", "   ")  # whitespace only => no-op
        conv.append("weird", "bad role")  # unknown role => no-op
        conv.append("user", "real")
        recent = conv.recent(turns=10, char_budget=1_000)
        assert [t.content for t in recent] == ["real"]

    def test_corrupt_line_does_not_kill_loop(self, tmp_path: Path) -> None:
        store = ConversationStore(tmp_path)
        conv = store.open("tui", "local")
        conv.append("user", "good 1")
        # Sneak in a bad line directly to disk to simulate a partial write.
        with conv.path.open("a", encoding="utf-8") as fh:
            fh.write("{not valid json}\n")
        conv.append("user", "good 2")
        recent = conv.recent(turns=10, char_budget=1_000)
        assert [t.content for t in recent] == ["good 1", "good 2"]

    def test_clear_removes_file(self, tmp_path: Path) -> None:
        store = ConversationStore(tmp_path)
        conv = store.open("tui", "local")
        conv.append("user", "hello")
        assert conv.exists
        wiped = conv.clear()
        assert wiped > 0
        assert not conv.exists
        # Subsequent .recent on a missing file returns empty without error.
        assert conv.recent() == []

    def test_clear_when_missing_returns_zero(self, tmp_path: Path) -> None:
        store = ConversationStore(tmp_path)
        conv = store.open("tui", "local")
        assert conv.clear() == 0

    def test_open_returns_same_handle_per_peer(self, tmp_path: Path) -> None:
        store = ConversationStore(tmp_path)
        a = store.open("whatsapp", "1@s.whatsapp.net")
        b = store.open("whatsapp", "1@s.whatsapp.net")
        assert a is b  # cached for stable per-file lock

    def test_list_peers(self, tmp_path: Path) -> None:
        store = ConversationStore(tmp_path)
        store.open("whatsapp", "1@s.whatsapp.net").append("user", "hi")
        store.open("whatsapp", "2@s.whatsapp.net").append("user", "hi")
        store.open("telegram", "999").append("user", "hi")
        peers = store.list_peers("whatsapp")
        assert peers == ["1@s.whatsapp.net", "2@s.whatsapp.net"]
        assert store.list_peers("telegram") == ["999"]
        assert store.list_peers("nope") == []


class TestRenderHistoryBlock:
    def test_renders_with_speaker_labels(self) -> None:
        turns = [
            Turn(role="user", content="hi", ts="t1", meta={}),
            Turn(role="assistant", content="hello", ts="t2", meta={}),
        ]
        block = render_history_block(turns)
        assert "User: hi" in block
        assert "You: hello" in block
        assert "oldest first" in block

    def test_empty_returns_empty(self) -> None:
        assert render_history_block([]) == ""

    def test_truncates_long_lines(self) -> None:
        long = "z" * 500
        turns = [Turn(role="user", content=long, ts="t", meta={})]
        block = render_history_block(turns)
        # Truncation happens at 240 chars + ellipsis suffix
        assert "..." in block
        assert "z" * 500 not in block


# ---------------------------------------------------------------------------
# Cortex integration: peer_key, history injection, identity note
# ---------------------------------------------------------------------------


class _StubLanguage:
    """Records the messages it was asked to think about; returns canned text."""

    def __init__(self, reply: str = "stub-reply") -> None:
        self.reply = reply
        self.last_messages: list[dict[str, Any]] | None = None

    async def think(self, messages: list[dict[str, Any]], **kwargs: Any) -> Utterance:
        self.last_messages = list(messages)
        return Utterance(
            text=self.reply,
            provider="stub",
            model="stub-model",
            elapsed_ms=1.0,
            usage={"total_tokens": 0},
            raw={},
        )


class TestCortexWorkingMemory:
    @pytest.mark.asyncio
    async def test_history_appended_after_reflect(self, tmp_path: Path) -> None:
        lang = _StubLanguage(reply="reply-1")
        store = ConversationStore(tmp_path)
        cortex = Cortex(language=lang, conversations=store)

        await cortex.reflect(
            Stimulus(channel="whatsapp:1@s.whatsapp.net", sender="1@s.whatsapp.net", text="hello"),
            peer_key="1@s.whatsapp.net",
        )
        conv = store.open("whatsapp", "1@s.whatsapp.net")
        recent = conv.recent(turns=10, char_budget=10_000)
        assert [t.role for t in recent] == ["user", "assistant"]
        assert recent[0].content == "hello"
        assert recent[1].content == "reply-1"

    @pytest.mark.asyncio
    async def test_history_replayed_on_next_turn(self, tmp_path: Path) -> None:
        lang = _StubLanguage(reply="reply-2")
        store = ConversationStore(tmp_path)
        # Pre-seed history so we can inspect what the second call sees.
        seed = store.open("whatsapp", "peer-1")
        seed.append("user", "my name is Vikram")
        seed.append("assistant", "nice to meet you, Vikram")

        cortex = Cortex(language=lang, conversations=store)
        await cortex.reflect(
            Stimulus(channel="whatsapp:peer-1", sender="peer-1", text="what's my name?"),
            peer_key="peer-1",
        )
        sys_msg = lang.last_messages[0]["content"]  # type: ignore[index]
        # Seeded turns must be visible in the system prompt of THIS call.
        assert "my name is Vikram" in sys_msg
        assert "nice to meet you, Vikram" in sys_msg
        assert "Recent conversation with this peer" in sys_msg

    @pytest.mark.asyncio
    async def test_peer_key_none_is_stateless(self, tmp_path: Path) -> None:
        lang = _StubLanguage(reply="reply-x")
        store = ConversationStore(tmp_path)
        cortex = Cortex(language=lang, conversations=store)
        # Two reflects WITHOUT peer_key should leave no transcript on disk.
        await cortex.reflect(Stimulus(channel="tui:local", sender="local", text="one"))
        await cortex.reflect(Stimulus(channel="tui:local", sender="local", text="two"))
        # No file written, no history block injected on the second call.
        assert list(tmp_path.rglob("*.jsonl")) == []
        sys_msg = lang.last_messages[0]["content"]  # type: ignore[index]
        assert "Recent conversation with this peer" not in sys_msg

    @pytest.mark.asyncio
    async def test_identity_note_for_non_tui_channels(self, tmp_path: Path) -> None:
        lang = _StubLanguage()
        store = ConversationStore(tmp_path)
        cortex = Cortex(language=lang, conversations=store, operator_label="Anurag")
        await cortex.reflect(
            Stimulus(channel="whatsapp:peer-2", sender="peer-2", text="hi"),
            peer_key="peer-2",
        )
        sys_msg = lang.last_messages[0]["content"]  # type: ignore[index]
        assert "remote contact" in sys_msg
        assert "NOT Anurag" in sys_msg
        assert "peer-2" in sys_msg

    @pytest.mark.asyncio
    async def test_identity_note_omitted_for_tui(self, tmp_path: Path) -> None:
        lang = _StubLanguage()
        store = ConversationStore(tmp_path)
        cortex = Cortex(language=lang, conversations=store, operator_label="Anurag")
        await cortex.reflect(
            Stimulus(channel="tui:local", sender="local", text="hi"),
            peer_key="local",
        )
        sys_msg = lang.last_messages[0]["content"]  # type: ignore[index]
        assert "remote contact" not in sys_msg
        assert "NOT Anurag" not in sys_msg

    @pytest.mark.asyncio
    async def test_history_disabled_via_history_turns_zero(self, tmp_path: Path) -> None:
        lang = _StubLanguage(reply="r")
        store = ConversationStore(tmp_path)
        seed = store.open("whatsapp", "peer-3")
        seed.append("user", "old turn")
        seed.append("assistant", "old reply")
        cortex = Cortex(language=lang, conversations=store, history_turns=0)
        await cortex.reflect(
            Stimulus(channel="whatsapp:peer-3", sender="peer-3", text="now"),
            peer_key="peer-3",
        )
        sys_msg = lang.last_messages[0]["content"]  # type: ignore[index]
        assert "Recent conversation with this peer" not in sys_msg

    @pytest.mark.asyncio
    async def test_existing_test_compat_no_conversations(self) -> None:
        # Belt-and-braces regression: cortex without `conversations` set must
        # never write to disk, never inject history, never crash on peer_key.
        lang = _StubLanguage(reply="r")
        cortex = Cortex(language=lang)  # no conversations store
        intent = await cortex.reflect(
            Stimulus(channel="whatsapp:peer-4", sender="peer-4", text="hi"),
            peer_key="peer-4",
        )
        assert intent.action.payload["text"] == "r"
        sys_msg = lang.last_messages[0]["content"]  # type: ignore[index]
        assert "Recent conversation with this peer" not in sys_msg


# ---------------------------------------------------------------------------
# CortexHome wiring
# ---------------------------------------------------------------------------


class TestHomeConversationsDir:
    def test_default_profile_lives_in_home_root(self, tmp_path: Path) -> None:
        from cortex.home import CortexHome

        home = CortexHome(root=tmp_path).bootstrap()
        assert home.conversations_dir == tmp_path / "conversations"
        assert home.conversations_dir.exists()

    def test_named_profile_lives_in_profile_root(self, tmp_path: Path) -> None:
        from cortex.home import CortexHome

        home = CortexHome(root=tmp_path, profile_name="work").bootstrap()
        assert home.conversations_dir == tmp_path / "profiles" / "work" / "conversations"
        assert home.conversations_dir.exists()
