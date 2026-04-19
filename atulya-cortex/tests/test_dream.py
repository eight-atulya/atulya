"""tests/test_dream.py — Batch 6 dream tests.

Covers:
- Consolidation: pulses call refresh; cooldown skips; per-pulse cap honored;
  failures recorded in stats but do not crash.
- SkillDistill: successful records become lesson markdown files in the
  expected layout; the lessons are picked up by `cortex/skills.py` on the
  next discover() call; failures are buffered and recoverable.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from cortex.skills import Skills
from dream import Consolidation, SkillDistill

# ---------------------------------------------------------------------------
# Consolidation
# ---------------------------------------------------------------------------


class TestConsolidation:
    @pytest.mark.asyncio
    async def test_dream_calls_refresh_for_each_id(self) -> None:
        seen: list[tuple[str, str]] = []

        async def refresh(bank: str, model_id: str) -> dict[str, Any]:
            seen.append((bank, model_id))
            return {"ok": True}

        c = Consolidation(
            bank_id="bank-a",
            mental_model_ids=["m1", "m2", "m3"],
            min_interval_s=0.0,
            per_pulse_cap=10,
            refresh=refresh,
        )
        await c.dream()
        assert seen == [("bank-a", "m1"), ("bank-a", "m2"), ("bank-a", "m3")]
        assert c.stats.refreshes_ok == 3

    @pytest.mark.asyncio
    async def test_per_pulse_cap_limits_attempts(self) -> None:
        seen: list[str] = []

        async def refresh(bank: str, model_id: str) -> dict[str, Any]:
            seen.append(model_id)
            return {"ok": True}

        c = Consolidation(
            bank_id="b",
            mental_model_ids=["m1", "m2", "m3", "m4", "m5"],
            min_interval_s=0.0,
            per_pulse_cap=2,
            refresh=refresh,
        )
        await c.dream()
        assert seen == ["m1", "m2"]
        assert c.stats.refreshes_attempted == 2

    @pytest.mark.asyncio
    async def test_cooldown_skips_recent_models(self) -> None:
        seen: list[str] = []

        async def refresh(bank: str, model_id: str) -> dict[str, Any]:
            seen.append(model_id)
            return {"ok": True}

        c = Consolidation(
            bank_id="b",
            mental_model_ids=["m1"],
            min_interval_s=10.0,
            per_pulse_cap=10,
            refresh=refresh,
        )
        await c.dream()
        await c.dream()
        assert seen == ["m1"]
        assert c.stats.skipped_cooldown == 1

    @pytest.mark.asyncio
    async def test_failure_is_recorded_not_raised(self) -> None:
        async def refresh(bank: str, model_id: str) -> dict[str, Any]:
            raise RuntimeError("api down")

        c = Consolidation(
            bank_id="b",
            mental_model_ids=["m1"],
            min_interval_s=0.0,
            per_pulse_cap=10,
            refresh=refresh,
        )
        await c.dream()
        assert c.stats.refreshes_failed == 1
        assert "api down" in (c.stats.last_error or "")


# ---------------------------------------------------------------------------
# SkillDistill
# ---------------------------------------------------------------------------


class TestSkillDistill:
    @pytest.mark.asyncio
    async def test_successful_record_writes_lesson_markdown(self, tmp_path: Path) -> None:
        sd = SkillDistill(life_root=tmp_path)
        sd.record(
            stimulus_text="how do I summarize a long doc?",
            intent_text="Use a 3-bullet outline first, then expand.",
            succeeded=True,
            tags=["writing", "summarization"],
        )
        await sd.dream()
        lessons = sorted(sd.lessons_dir.glob("*.md"))
        assert len(lessons) == 1
        text = lessons[0].read_text(encoding="utf-8")
        assert "tags: writing, summarization" in text
        assert "# how do I summarize a long doc?" in text
        assert "Brain answered" in text
        assert sd.stats.lessons_written == 1

    @pytest.mark.asyncio
    async def test_failed_records_are_skipped(self, tmp_path: Path) -> None:
        sd = SkillDistill(life_root=tmp_path)
        sd.record(stimulus_text="x", intent_text="y", succeeded=False)
        await sd.dream()
        assert list(sd.lessons_dir.glob("*.md")) == []
        assert sd.stats.lessons_written == 0

    @pytest.mark.asyncio
    async def test_lessons_are_picked_up_by_skills_discover(self, tmp_path: Path) -> None:
        sd = SkillDistill(life_root=tmp_path)
        sd.record(
            stimulus_text="When debugging, always read the actual error first.",
            intent_text="Acknowledged. I will read the full traceback before guessing.",
            succeeded=True,
        )
        await sd.dream()
        skills = Skills([sd.lessons_dir]).discover()
        assert len(skills) == 1
        assert "debugging" in skills[0].name.lower() or "When debugging" in skills[0].name

    @pytest.mark.asyncio
    async def test_per_pulse_cap_buffers_remainder(self, tmp_path: Path) -> None:
        sd = SkillDistill(life_root=tmp_path, max_records_per_pulse=2)
        for i in range(5):
            sd.record(stimulus_text=f"q{i}", intent_text=f"a{i}", succeeded=True)
        await sd.dream()
        assert len(list(sd.lessons_dir.glob("*.md"))) == 2
        assert sd.buffered == 3
        await sd.dream()
        assert len(list(sd.lessons_dir.glob("*.md"))) == 4

    @pytest.mark.asyncio
    async def test_buffer_overflow_drops_oldest(self, tmp_path: Path) -> None:
        sd = SkillDistill(life_root=tmp_path, max_buffer=3)
        for i in range(10):
            sd.record(stimulus_text=f"q{i}", intent_text=f"a{i}", succeeded=True)
        assert sd.buffered == 3

    @pytest.mark.asyncio
    async def test_uses_language_when_provided(self, tmp_path: Path) -> None:
        class _StubLang:
            async def think(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
                from cortex.language import Utterance

                return Utterance(
                    text="Title: distilled\nLLM-described lesson body.",
                    provider="stub",
                    model="stub",
                    elapsed_ms=1.0,
                )

        sd = SkillDistill(life_root=tmp_path, language=_StubLang())
        sd.record(stimulus_text="hi", intent_text="hello", succeeded=True)
        await sd.dream()
        text = list(sd.lessons_dir.glob("*.md"))[0].read_text(encoding="utf-8")
        assert "Title: distilled" in text or "LLM-described lesson body" in text

    @pytest.mark.asyncio
    async def test_language_failure_falls_back_to_heuristic(self, tmp_path: Path) -> None:
        class _BadLang:
            async def think(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
                raise RuntimeError("LLM down")

        sd = SkillDistill(life_root=tmp_path, language=_BadLang())
        sd.record(stimulus_text="how to brew tea?", intent_text="boil water, steep", succeeded=True)
        await sd.dream()
        files = list(sd.lessons_dir.glob("*.md"))
        assert len(files) == 1
        assert "how to brew tea" in files[0].read_text(encoding="utf-8")
