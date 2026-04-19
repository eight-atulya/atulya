"""skill_distill.py — distill successful runs into lesson markdown files.

When the cortex completes a non-trivial task (a multi-step delegation, a
debugged tool failure, a long conversation that resolved cleanly), the
`SkillDistill` dreamer writes a short markdown lesson into
`atulya-cortex/life/40_knowledge/17_lessons_learned/`. The next time the
brain boots, those lessons are picked up by `cortex/skills.py` and surfaced
in the system prompt — the brain literally learns from itself.

Inputs the cortex feeds the dreamer:
- `record(stimulus_text, intent_text, motor_artifact, *, succeeded, tags)`

Each record is buffered. On every `dream()` pulse we:
1. Pull all buffered records.
2. For each successful one, write a `<timestamp>-<slug>.md` file with a
   YAML frontmatter (`tags`, `created_at`) and a body that mirrors the
   `cortex/skills.py` parser shape: H1 title + first-paragraph description.

If a `Language` is supplied, lesson titles and descriptions are LLM-summarized;
otherwise we fall back to a deterministic truncation. This keeps the dreamer
useful even with no LLM around.

Naming voice: `SkillDistill.dream` is the Dreamer verb; `record` is how the
cortex feeds it raw experiences.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_LESSONS_SUBDIR = "40_knowledge/17_lessons_learned"


def _slug(text: str, *, max_len: int = 48) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return (text[:max_len] or "lesson").rstrip("-")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _Record:
    stimulus_text: str
    intent_text: str
    motor_artifact: dict[str, Any]
    succeeded: bool
    tags: list[str] = field(default_factory=list)
    recorded_at: float = field(default_factory=time.monotonic)


@dataclass
class DistillStats:
    pulses: int = 0
    records_buffered: int = 0
    lessons_written: int = 0
    failed_writes: int = 0
    last_error: str | None = None


class SkillDistill:
    """Buffer experience records; write lesson markdown on each pulse."""

    def __init__(
        self,
        *,
        life_root: str | Path,
        subdir: str = DEFAULT_LESSONS_SUBDIR,
        language: Any | None = None,
        provider: str | None = None,
        max_records_per_pulse: int = 5,
        max_buffer: int = 200,
    ) -> None:
        self._root = Path(life_root) / subdir
        self._root.mkdir(parents=True, exist_ok=True)
        self._buffer: list[_Record] = []
        self._language = language
        self._provider = provider
        self._max_per_pulse = max(1, int(max_records_per_pulse))
        self._max_buffer = max(1, int(max_buffer))
        self.stats = DistillStats()

    @property
    def lessons_dir(self) -> Path:
        return self._root

    @property
    def buffered(self) -> int:
        return len(self._buffer)

    def record(
        self,
        *,
        stimulus_text: str,
        intent_text: str,
        motor_artifact: dict[str, Any] | None = None,
        succeeded: bool,
        tags: list[str] | None = None,
    ) -> None:
        rec = _Record(
            stimulus_text=stimulus_text or "",
            intent_text=intent_text or "",
            motor_artifact=dict(motor_artifact or {}),
            succeeded=bool(succeeded),
            tags=list(tags or []),
        )
        self._buffer.append(rec)
        self.stats.records_buffered += 1
        if len(self._buffer) > self._max_buffer:
            drop = len(self._buffer) - self._max_buffer
            self._buffer = self._buffer[drop:]

    async def dream(self) -> None:
        self.stats.pulses += 1
        if not self._buffer:
            return
        batch = self._buffer[: self._max_per_pulse]
        self._buffer = self._buffer[self._max_per_pulse :]

        for rec in batch:
            if not rec.succeeded:
                continue
            try:
                title, description = await self._render(rec)
                self._write_lesson(rec, title=title, description=description)
                self.stats.lessons_written += 1
            except Exception as exc:
                self.stats.failed_writes += 1
                self.stats.last_error = f"{type(exc).__name__}: {exc}"

    async def _render(self, rec: _Record) -> tuple[str, str]:
        if self._language is None:
            return self._heuristic_render(rec)
        prompt = (
            "Summarize this conversation turn as a one-sentence lesson title and a "
            "one-paragraph description. Output exactly two lines, the first being "
            "the title, the second being the description. Be terse.\n\n"
            f"User said: {rec.stimulus_text!r}\n"
            f"Brain replied: {rec.intent_text!r}\n"
            f"Outcome artifact: {rec.motor_artifact!r}\n"
        )
        try:
            utt = await asyncio.wait_for(
                self._language.think(
                    [{"role": "user", "content": prompt}],
                    provider=self._provider,
                    temperature=0.3,
                    max_tokens=200,
                ),
                timeout=60.0,
            )
        except Exception:
            return self._heuristic_render(rec)
        text = (utt.text or "").strip()
        if not text:
            return self._heuristic_render(rec)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = lines[0][:120] if lines else self._heuristic_render(rec)[0]
        description = (lines[1] if len(lines) > 1 else lines[0])[:600]
        return title, description

    def _heuristic_render(self, rec: _Record) -> tuple[str, str]:
        first_line = rec.stimulus_text.strip().splitlines()[0] if rec.stimulus_text.strip() else "lesson"
        title = first_line[:80] if first_line else "lesson"
        description = (
            f"User asked: {rec.stimulus_text.strip()[:240]}\nBrain answered: {rec.intent_text.strip()[:240]}"
        ).strip()
        return title, description

    def _write_lesson(self, rec: _Record, *, title: str, description: str) -> Path:
        ts = _utcnow().strftime("%Y%m%dT%H%M%SZ")
        fname = f"{ts}-{_slug(title)}.md"
        path = self._root / fname
        body = self._render_markdown(rec, title=title, description=description)
        path.write_text(body, encoding="utf-8")
        return path

    @staticmethod
    def _render_markdown(rec: _Record, *, title: str, description: str) -> str:
        tags = rec.tags
        tag_line = f"tags: {', '.join(tags)}" if tags else ""
        frontmatter = ["---", f"created_at: {_utcnow().isoformat()}"]
        if tag_line:
            frontmatter.append(tag_line)
        frontmatter.append("---")
        return (
            "\n".join(frontmatter)
            + f"\n\n# {title}\n\n{description}\n"
            + (
                f"\n## Conversation\n\n- user: {rec.stimulus_text}\n- brain: {rec.intent_text}\n"
                if rec.stimulus_text or rec.intent_text
                else ""
            )
        )


__all__ = ["DistillStats", "DEFAULT_LESSONS_SUBDIR", "SkillDistill"]
