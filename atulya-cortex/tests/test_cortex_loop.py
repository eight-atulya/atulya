"""tests/test_cortex_loop.py — Batch 4 tests.

Covers `cortex/personality.py`, `cortex/skills.py`, `cortex/language.py`,
and the upgraded `cortex/cortex.py` real-loop. The real loop is tested
with a stub `Language` (mocked HTTP) so no LLM is required. A gated
integration test calls a live LM Studio at port 1234 if the env flag is
set.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from cortex import (
    Cortex,
    Language,
    LanguageError,
    Personality,
    Provider,
    Recollection,
    Reflex,
    Skills,
    Stimulus,
    Utterance,
)

# ---------------------------------------------------------------------------
# Personality
# ---------------------------------------------------------------------------


class TestPersonality:
    def test_default_when_file_missing(self, tmp_path: Path) -> None:
        p = Personality.load(tmp_path / "nope.md")
        assert "Atulya" in p.bio
        assert p.voice  # non-empty default
        assert "Voice:" in p.system_prompt_block()

    def test_loads_frontmatter_and_body(self, tmp_path: Path) -> None:
        path = tmp_path / "persona.md"
        path.write_text(
            "---\n"
            'voice: "warm and curious"\n'
            'traits: kind, terse, honest\n'
            'bio: "I am a v2 brain."\n'
            "---\n\n"
            "Notes about how I work.\n",
            encoding="utf-8",
        )
        p = Personality.load(path)
        assert p.voice == "warm and curious"
        assert p.bio == "I am a v2 brain."
        assert p.traits == ["kind", "terse", "honest"]
        assert "Notes about how I work" in p.body
        block = p.system_prompt_block()
        assert "warm and curious" in block
        assert "kind, terse, honest" in block

    def test_no_frontmatter_uses_first_paragraph_as_bio(self, tmp_path: Path) -> None:
        path = tmp_path / "persona.md"
        path.write_text("First line bio.\n\nSecond paragraph.\n", encoding="utf-8")
        p = Personality.load(path)
        assert p.bio == "First line bio."


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


class TestSkills:
    def test_discovers_markdown_files_with_h1_and_first_para(
        self, tmp_path: Path
    ) -> None:
        sk_dir = tmp_path / "skills"
        sk_dir.mkdir()
        (sk_dir / "summarize.md").write_text(
            "# Summarize\n\nSummarize a chunk of text in 3 lines.\n",
            encoding="utf-8",
        )
        (sk_dir / "translate.md").write_text(
            "# Translate\n\nTranslate from any language to English.\nMore detail.",
            encoding="utf-8",
        )
        (sk_dir / "skip.txt").write_text("not a skill", encoding="utf-8")

        skills = Skills([sk_dir])
        out = skills.discover()
        names = sorted(s.name for s in out)
        assert names == ["Summarize", "Translate"]
        for s in out:
            assert s.description and len(s.description) > 0

    def test_falls_back_to_filename_without_h1(self, tmp_path: Path) -> None:
        sk_dir = tmp_path / "skills"
        sk_dir.mkdir()
        (sk_dir / "tweet.md").write_text("Just a body.", encoding="utf-8")
        out = Skills([sk_dir]).discover()
        assert out[0].name == "tweet"

    def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        out = Skills([tmp_path / "ghost"]).discover()
        assert out == []


# ---------------------------------------------------------------------------
# Language (mocked HTTP)
# ---------------------------------------------------------------------------


def _mock_chat_response(text: str = "ok") -> dict[str, Any]:
    return {
        "id": "chatcmpl-x",
        "object": "chat.completion",
        "model": "google/gemma-3-4b",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
    }


class TestLanguage:
    def test_provider_factories(self) -> None:
        p = Provider.lm_studio()
        assert p.name == "lm-studio"
        assert "1234" in p.base_url
        assert Provider.openai(api_key="k").name == "openai"
        assert Provider.groq(api_key="k").name == "groq"

    @pytest.mark.asyncio
    async def test_think_calls_first_provider_and_returns_utterance(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = request.content.decode("utf-8")
            return httpx.Response(200, json=_mock_chat_response("hello back"))

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        lang = Language([Provider.lm_studio()], client=client)
        try:
            utt = await lang.think([{"role": "user", "content": "hi"}])
            assert utt.text == "hello back"
            assert utt.provider == "lm-studio"
            assert "/chat/completions" in captured["url"]
            assert '"hi"' in captured["body"]
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_falls_back_to_second_provider_on_5xx(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            host = request.url.host
            seen.append(host)
            if host == "first.local":
                return httpx.Response(500, json={"error": "boom"})
            return httpx.Response(200, json=_mock_chat_response("from-second"))

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        first = Provider(name="first", base_url="http://first.local/v1", api_key="x", default_model="m1")
        second = Provider(name="second", base_url="http://second.local/v1", api_key="x", default_model="m2")
        lang = Language([first, second], client=client)
        try:
            utt = await lang.think([{"role": "user", "content": "hi"}])
            assert utt.text == "from-second"
            assert utt.provider == "second"
            assert seen[0] == "first.local"
            assert seen[-1] == "second.local"
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_raises_when_all_providers_fail(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "down"})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        lang = Language(
            [
                Provider(name="a", base_url="http://a.local/v1", default_model="m"),
                Provider(name="b", base_url="http://b.local/v1", default_model="m"),
            ],
            client=client,
        )
        try:
            with pytest.raises(LanguageError):
                await lang.think([{"role": "user", "content": "hi"}])
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_disposition_routing_picks_mapped_provider(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.host)
            return httpx.Response(200, json=_mock_chat_response("ok"))

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        lang = Language(
            [
                Provider(name="local", base_url="http://local.host/v1", default_model="m"),
                Provider(name="cloud", base_url="http://cloud.host/v1", default_model="m"),
            ],
            disposition_map={"careful": "cloud"},
            client=client,
        )
        try:
            await lang.think([{"role": "user", "content": "hi"}], disposition="careful")
            assert seen[0] == "cloud.host"
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_explicit_provider_arg_overrides_default(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.host)
            return httpx.Response(200, json=_mock_chat_response("ok"))

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        lang = Language(
            [
                Provider(name="a", base_url="http://a.host/v1", default_model="m"),
                Provider(name="b", base_url="http://b.host/v1", default_model="m"),
            ],
            client=client,
        )
        try:
            await lang.think([{"role": "user", "content": "hi"}], provider="b")
            assert seen[0] == "b.host"
        finally:
            await client.aclose()


# ---------------------------------------------------------------------------
# Cortex real loop (with stub Language)
# ---------------------------------------------------------------------------


class _StubLanguage:
    """Records the messages it was asked to think about; returns canned text."""

    def __init__(self, reply: str = "stub-reply") -> None:
        self.reply = reply
        self.last_messages: list[dict[str, Any]] | None = None
        self.last_kwargs: dict[str, Any] | None = None

    async def think(self, messages: list[dict[str, Any]], **kwargs: Any) -> Utterance:
        self.last_messages = list(messages)
        self.last_kwargs = dict(kwargs)
        return Utterance(
            text=self.reply,
            provider="stub",
            model="stub-model",
            elapsed_ms=1.0,
            usage={"total_tokens": 0},
            raw={},
        )


class TestCortexRealLoop:
    @pytest.mark.asyncio
    async def test_echo_mode_when_no_language(self) -> None:
        cortex = Cortex()
        intent = await cortex.reflect(Stimulus(channel="tui:a", sender="a", text="ping"))
        assert intent.action.kind == "reply"
        assert intent.action.payload["text"] == "hello back: ping"

    @pytest.mark.asyncio
    async def test_uses_language_when_provided(self) -> None:
        lang = _StubLanguage(reply="from-llm")
        cortex = Cortex(language=lang)
        intent = await cortex.reflect(Stimulus(channel="tui:a", sender="a", text="hello"))
        assert intent.action.payload["text"] == "from-llm"
        assert lang.last_messages is not None
        assert lang.last_messages[-1]["content"] == "hello"
        assert "Voice:" in lang.last_messages[0]["content"]

    @pytest.mark.asyncio
    async def test_recall_recollections_appear_in_system_prompt(self) -> None:
        async def recall(query: str, kind: str, bank: str | None = None):
            return [
                Recollection(kind=kind, text=f"remembered {query}", score=0.9, source="bank:test"),
            ]

        lang = _StubLanguage(reply="ok")
        cortex = Cortex(language=lang, recall=recall, recall_kinds=("episodic",))
        await cortex.reflect(Stimulus(channel="tui:a", sender="a", text="dragons"))
        sys_msg = lang.last_messages[0]["content"]  # type: ignore[index]
        assert "remembered dragons" in sys_msg
        assert "[episodic]" in sys_msg

    @pytest.mark.asyncio
    async def test_skills_block_appears_in_system_prompt(self, tmp_path: Path) -> None:
        sk_dir = tmp_path / "sk"
        sk_dir.mkdir()
        (sk_dir / "summarize.md").write_text("# Summarize\n\nShorten any text.", encoding="utf-8")
        lang = _StubLanguage()
        cortex = Cortex(language=lang, skills=Skills([sk_dir]))
        await cortex.reflect(Stimulus(channel="tui:a", sender="a", text="x"))
        sys_msg = lang.last_messages[0]["content"]  # type: ignore[index]
        assert "Skills available:" in sys_msg
        assert "Summarize" in sys_msg

    @pytest.mark.asyncio
    async def test_personality_voice_in_system_prompt(self, tmp_path: Path) -> None:
        path = tmp_path / "persona.md"
        path.write_text("---\nvoice: snappy\n---\nbio body", encoding="utf-8")
        persona = Personality.load(path)
        lang = _StubLanguage()
        cortex = Cortex(language=lang, personality=persona)
        await cortex.reflect(Stimulus(channel="tui:a", sender="a", text="x"))
        sys_msg = lang.last_messages[0]["content"]  # type: ignore[index]
        assert "snappy" in sys_msg

    @pytest.mark.asyncio
    async def test_sandbox_reflex_adds_warning(self) -> None:
        lang = _StubLanguage()
        cortex = Cortex(language=lang)
        await cortex.reflect(
            Stimulus(channel="tui:a", sender="a", text="x"),
            reflex=Reflex(decision="sandbox", reason="new"),
        )
        sys_msg = lang.last_messages[0]["content"]  # type: ignore[index]
        assert "sandboxed" in sys_msg

    @pytest.mark.asyncio
    async def test_deny_reflex_returns_noop(self) -> None:
        lang = _StubLanguage()
        cortex = Cortex(language=lang)
        intent = await cortex.reflect(
            Stimulus(channel="tui:a", sender="a", text="x"),
            reflex=Reflex(decision="deny", reason="blocked"),
        )
        assert intent.action.kind == "noop"
        assert lang.last_messages is None

    @pytest.mark.asyncio
    async def test_reflect_text_returns_string(self) -> None:
        lang = _StubLanguage(reply="just text")
        cortex = Cortex(language=lang)
        text = await cortex.reflect_text(Stimulus(channel="tui:a", sender="a", text="x"))
        assert text == "just text"


# ---------------------------------------------------------------------------
# Gated: live LM Studio integration
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("CORTEX_LM_STUDIO_E2E") != "1",
    reason="set CORTEX_LM_STUDIO_E2E=1 to run live LM Studio test",
)
@pytest.mark.asyncio
async def test_lm_studio_live() -> None:
    lang = Language.with_lm_studio()
    try:
        utt = await lang.think(
            [
                {"role": "system", "content": "You answer in one word."},
                {"role": "user", "content": "Capital of France?"},
            ],
            max_tokens=8,
            temperature=0.1,
        )
        assert "paris" in utt.text.lower()
    finally:
        await lang.aclose()
