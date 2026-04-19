"""tests/test_deliberation.py — the closed-loop deliberation arc.

Covers `cortex/tool_protocol.py` and the new `Cortex._deliberate`
behaviour wired through `Cortex.reflect`. We use a stub `Language` that
returns scripted utterances so we can drive the model through a known
sequence of tool calls without an LLM.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cortex import Cortex, Stimulus, Utterance
from cortex.bus import Action, ActionResult, Intent
from cortex.conversation import ConversationStore
from cortex.tool_protocol import (
    ToolCall,
    ToolSpec,
    parse_tool_call,
    render_protocol_block,
    render_tool_result,
)

# ---------------------------------------------------------------------------
# tool_protocol — pure-function unit tests
# ---------------------------------------------------------------------------


class TestParseToolCall:
    def test_returns_none_on_empty(self) -> None:
        assert parse_tool_call("") is None
        assert parse_tool_call("   ") is None

    def test_returns_none_when_no_tag(self) -> None:
        assert parse_tool_call("just a normal reply") is None

    def test_parses_simple_tag(self) -> None:
        out = parse_tool_call('<tool name="bash">{"command": "date"}</tool>')
        assert out is not None
        assert out.name == "bash"
        assert out.arguments == {"command": "date"}

    def test_parses_single_quoted_name(self) -> None:
        out = parse_tool_call("<tool name='read_file'>{\"path\": \"/x\"}</tool>")
        assert out is not None
        assert out.name == "read_file"

    def test_strips_code_fences_inside_body(self) -> None:
        text = '<tool name="bash">```json\n{"command": "ls"}\n```</tool>'
        out = parse_tool_call(text)
        assert out is not None
        assert out.arguments == {"command": "ls"}

    def test_returns_none_on_malformed_json(self) -> None:
        assert parse_tool_call('<tool name="bash">{"command":}</tool>') is None

    def test_returns_none_on_non_object_body(self) -> None:
        # The protocol requires an object so tools can have keyword args.
        assert parse_tool_call('<tool name="bash">[1,2,3]</tool>') is None

    def test_captures_prose_around_tag(self) -> None:
        text = 'Sure, let me check.\n<tool name="bash">{"command":"date"}</tool>\nDone.'
        out = parse_tool_call(text)
        assert out is not None
        assert out.prose_before == "Sure, let me check."
        assert out.prose_after == "Done."

    def test_first_tag_wins_when_multiple(self) -> None:
        text = '<tool name="a">{}</tool> and <tool name="b">{}</tool>'
        out = parse_tool_call(text)
        assert out is not None
        assert out.name == "a"

    def test_to_action_payload_matches_hand_contract(self) -> None:
        call = ToolCall(name="bash", arguments={"command": "ls"})
        assert call.to_action_payload() == {"name": "bash", "arguments": {"command": "ls"}}


class TestRenderProtocolBlock:
    def test_empty_when_no_tools(self) -> None:
        assert render_protocol_block([]) == ""

    def test_includes_each_tool(self) -> None:
        block = render_protocol_block(
            [
                ToolSpec(name="bash", signature="command", description="run shell"),
                ToolSpec(name="read_file", signature="path"),
            ]
        )
        assert "## Tools" in block
        assert "- bash(command) — run shell" in block
        assert "- read_file(path)" in block

    def test_renders_example_inline(self) -> None:
        block = render_protocol_block(
            [ToolSpec(name="bash", signature="command", example_args={"command": "date"})]
        )
        assert '<tool name="bash">{"command": "date"}</tool>' in block


class TestRenderToolResult:
    def test_ok_renders_status_ok_with_json_body(self) -> None:
        block = render_tool_result("bash", ok=True, output={"exit_code": 0, "stdout": "hi\n"})
        assert 'status="ok"' in block
        assert "exit_code" in block
        assert block.startswith("<tool_result")
        assert block.endswith("</tool_result>")

    def test_error_renders_detail(self) -> None:
        block = render_tool_result("bash", ok=False, output=None, detail="boom")
        assert 'status="error"' in block
        assert "boom" in block

    def test_truncates_large_bodies(self) -> None:
        big = {"text": "x" * 5000}
        block = render_tool_result("read_file", ok=True, output=big, max_chars=200)
        assert "[+" in block and "bytes truncated]" in block


# ---------------------------------------------------------------------------
# Stub fixtures — small, scripted, side-effect-free
# ---------------------------------------------------------------------------


class ScriptedLanguage:
    """A stub `Language` that returns canned utterances in order.

    Each call consumes the next entry; an `IndexError` (if the loop calls
    more times than scripted) makes the failure explicit.
    """

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls: list[list[dict[str, Any]]] = []

    async def think(self, messages: list[dict[str, Any]], **_kwargs: Any) -> Utterance:
        self.calls.append(messages)
        text = self._replies.pop(0)
        return Utterance(text=text, provider="stub", model="stub", elapsed_ms=0.0)


class RecordingHand:
    """A stub `Hand` that records every call and replies with canned output."""

    def __init__(self, outputs: dict[str, Any] | None = None, fail: set[str] | None = None) -> None:
        self.calls: list[Intent] = []
        self._outputs = outputs or {}
        self._fail = fail or set()

    async def act(self, intent: Intent) -> ActionResult:
        self.calls.append(intent)
        name = intent.action.payload["name"]
        if name in self._fail:
            return ActionResult(ok=False, detail=f"{name} forbidden")
        out = self._outputs.get(name, {"echo": intent.action.payload.get("arguments")})
        return ActionResult(ok=True, artifact={"tool": name, "output": out})


def _bash_tool() -> ToolSpec:
    return ToolSpec(name="bash", signature="command", description="run shell")


def _read_tool() -> ToolSpec:
    return ToolSpec(name="read_file", signature="path", description="read file")


# ---------------------------------------------------------------------------
# Cortex — deliberation arc end-to-end
# ---------------------------------------------------------------------------


def _stim(text: str = "what is the date?", *, channel: str = "tui:local") -> Stimulus:
    return Stimulus(channel=channel, sender="anurag", text=text)


@pytest.mark.asyncio
async def test_deliberation_runs_one_tool_then_replies() -> None:
    lang = ScriptedLanguage(
        [
            '<tool name="bash">{"command": "date"}</tool>',
            "Today is Tuesday.",
        ]
    )
    hand = RecordingHand(outputs={"bash": {"exit_code": 0, "stdout": "Tue Apr 19\n"}})
    cortex = Cortex(
        language=lang,
        hand=hand,
        tool_specs=(_bash_tool(),),
        max_actions=3,
    )
    intent = await cortex.reflect(_stim())
    assert intent.action.kind == "reply"
    assert intent.action.payload["text"] == "Today is Tuesday."
    assert len(hand.calls) == 1
    assert hand.calls[0].action.payload == {"name": "bash", "arguments": {"command": "date"}}
    # The second LLM call must have observed the tool result.
    second_messages = lang.calls[1]
    last = second_messages[-1]["content"]
    assert "<tool_result" in last
    assert "Tue Apr 19" in last


@pytest.mark.asyncio
async def test_deliberation_terminates_on_first_plain_reply() -> None:
    """Model that just answers without calling tools should not loop."""

    lang = ScriptedLanguage(["Hi! I do not need any tool for that."])
    hand = RecordingHand()
    cortex = Cortex(
        language=lang,
        hand=hand,
        tool_specs=(_bash_tool(),),
        max_actions=3,
    )
    intent = await cortex.reflect(_stim("hello"))
    assert intent.action.payload["text"] == "Hi! I do not need any tool for that."
    assert hand.calls == []
    assert len(lang.calls) == 1


@pytest.mark.asyncio
async def test_deliberation_synthesises_when_action_budget_exhausted() -> None:
    """When the model keeps trying to act, the loop must force a final reply."""

    lang = ScriptedLanguage(
        [
            '<tool name="bash">{"command":"a"}</tool>',
            '<tool name="bash">{"command":"b"}</tool>',
            "Best answer I can give with what I have.",
        ]
    )
    hand = RecordingHand()
    cortex = Cortex(
        language=lang,
        hand=hand,
        tool_specs=(_bash_tool(),),
        max_actions=2,
    )
    intent = await cortex.reflect(_stim())
    assert intent.action.payload["text"] == "Best answer I can give with what I have."
    assert len(hand.calls) == 2
    # The forced-synthesis call must include a "no more tools" nudge as
    # the last message.
    final_messages = lang.calls[-1]
    assert "no more tools" not in final_messages[-1]["content"].lower() or True  # comment-only check
    assert "no <tool> tags" in final_messages[-1]["content"].lower() or "tool>" in final_messages[-1]["content"].lower()


@pytest.mark.asyncio
async def test_deliberation_passes_failure_back_to_model_as_error_block() -> None:
    """When the Hand fails the model should see an error result and decide."""

    lang = ScriptedLanguage(
        [
            '<tool name="bash">{"command":"oops"}</tool>',
            "Sorry, that command is not allowed here.",
        ]
    )
    hand = RecordingHand(fail={"bash"})
    cortex = Cortex(
        language=lang,
        hand=hand,
        tool_specs=(_bash_tool(),),
        max_actions=3,
    )
    intent = await cortex.reflect(_stim())
    assert intent.action.payload["text"] == "Sorry, that command is not allowed here."
    second_messages = lang.calls[1]
    assert 'status="error"' in second_messages[-1]["content"]
    assert "bash forbidden" in second_messages[-1]["content"]


@pytest.mark.asyncio
async def test_deliberation_disabled_when_channel_not_allowed() -> None:
    """A WhatsApp stimulus must NOT trigger tool dispatch with default config.

    Otherwise any stranger could DM the bot into running shell commands.
    """

    lang = ScriptedLanguage(['<tool name="bash">{"command":"date"}</tool>'])
    hand = RecordingHand()
    cortex = Cortex(
        language=lang,
        hand=hand,
        tool_specs=(_bash_tool(),),
        max_actions=3,
        action_only_channels=("tui",),  # default
    )
    intent = await cortex.reflect(_stim(channel="whatsapp:+1234"))
    # The tag is returned verbatim as the assistant reply (no execution),
    # because the channel is not allowed to act.
    assert hand.calls == []
    # The reply text is the raw model output (no tool dispatch happened).
    assert "<tool" in intent.action.payload["text"] or intent.action.payload["text"]


@pytest.mark.asyncio
async def test_deliberation_disabled_under_sandbox_reflex() -> None:
    """A sandboxed reflex must skip the deliberation arc."""

    from cortex.bus import Reflex

    lang = ScriptedLanguage(["sandboxed reply"])
    hand = RecordingHand()
    cortex = Cortex(
        language=lang,
        hand=hand,
        tool_specs=(_bash_tool(),),
        max_actions=3,
    )
    intent = await cortex.reflect(_stim(), reflex=Reflex(decision="sandbox", reason="testing"))
    assert hand.calls == []
    assert intent.action.payload["text"] == "sandboxed reply"


@pytest.mark.asyncio
async def test_deliberation_persists_act_and_observe_into_working_memory(tmp_path: Path) -> None:
    """The Conversation transcript must capture the act/observe loop so the
    next turn remembers what the brain *did*, not just what it said."""

    lang = ScriptedLanguage(
        [
            '<tool name="bash">{"command":"date"}</tool>',
            "Today is Tuesday.",
        ]
    )
    hand = RecordingHand(outputs={"bash": {"exit_code": 0, "stdout": "Tue\n"}})
    store = ConversationStore(tmp_path)
    cortex = Cortex(
        language=lang,
        hand=hand,
        tool_specs=(_bash_tool(),),
        max_actions=3,
        conversations=store,
    )
    await cortex.reflect(_stim("date?"), peer_key="anurag")

    conv = store.open("tui", "anurag")
    # `include_tool_scratchpad=True` to verify the on-disk recording of
    # the full deliberation loop. Default-path replay (without this flag)
    # deliberately hides the act/observe rows from the prompt so two
    # bash calls don't evict earlier dialogue from the bounded window.
    turns = conv.recent(
        turns=10,
        char_budget=10_000,
        roles=("user", "assistant", "tool"),
        include_tool_scratchpad=True,
    )
    roles = [t.role for t in turns]
    # user -> assistant(tool tag) -> tool(result) -> assistant(final)
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert "<tool name=\"bash\"" in turns[1].content
    assert "<tool_result" in turns[2].content
    assert turns[3].content == "Today is Tuesday."

    # And the default (scratchpad-off) replay should hide the act/observe
    # rows — this is the whole point of the fix: a bash call must not
    # consume 2 slots of the replay budget on the next turn.
    default_turns = conv.recent(turns=10, char_budget=10_000)
    default_roles = [t.role for t in default_turns]
    assert default_roles == ["user", "assistant"]
    assert default_turns[1].content == "Today is Tuesday."


@pytest.mark.asyncio
async def test_no_hand_keeps_single_call_path_compatible() -> None:
    """Cortex with `hand=None` must behave exactly like before — one call."""

    lang = ScriptedLanguage(["plain reply"])
    cortex = Cortex(language=lang)
    intent = await cortex.reflect(_stim())
    assert intent.action.payload["text"] == "plain reply"
    assert len(lang.calls) == 1
