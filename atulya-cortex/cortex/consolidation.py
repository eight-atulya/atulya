"""consolidation.py — sleep. Episodes -> Facts.

In a real brain, the hippocampus is a fast learner and the neocortex is
a slow generaliser. During sleep (and quiet wake states), the
hippocampus replays recent experiences and the neocortex extracts the
durable structure — preferences, identities, constraints, lessons —
into long-term semantic memory. This is system-level consolidation
(Marr 1971; McClelland & O'Reilly 1995).

This module is the brain's sleep cycle, scoped per peer. One pass:

1. Read new episodes since the last consolidation cursor.
2. Skip if too few or too low-affect to warrant LLM cost.
3. Ask the LLM to extract durable facts as JSON.
4. Upsert each fact into `FactStore` (it dedupes & reinforces).
5. Mark the consumed episodes `consolidated=True`.
6. Advance the cursor to the latest episode timestamp.

Cost discipline
---------------

Every consolidation pass is one LLM call. We gate it with three layers:
- `min_episodes` (don't bother with one new turn)
- `min_total_salience` (don't bother with low-affect chitchat)
- `cooldown_s` per peer (no faster than every N seconds even on demand)

Failures are absorbed quietly — the next pass tries again with the
same episodes, since the cursor only advances after a successful
distillation.

Naming voice: `Sleep` is the noun you instantiate; `consolidate` is
the verb you call. We deliberately did NOT call this class
`Consolidation` because there is already a `dream/consolidation.py`
that handles the *external* atulya-api mental-model refresh — that one
is HTTP-shaped, this one is LLM-shaped, and the names need to stay
distinct to avoid confusion in the dream loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from cortex.episodes import Episode, EpisodeStore
from cortex.semantic_facts import FactStore

logger = logging.getLogger(__name__)


# Prompt is short on purpose: small models drift on long instructions
# and we want the JSON output to dominate the token budget.
_SLEEP_PROMPT = """\
You are the brain's consolidation routine. You are reading {n} recent
turns of conversation between yourself ("assistant") and a peer ("{peer}").
Your job: extract DURABLE FACTS about the peer — things that will still
be true next week. Examples of durable facts:

- preferences ("prefers terse replies", "uses tabs not spaces")
- identity ("works at X", "lives in Y", "their daughter's name is Z")
- skills / domains ("is a Python engineer", "studies kannada")
- constraints / rules ("never message before 9am", "do not call them on Mondays")
- lessons learned ("explaining bash is too verbose for them — be brief")

Do NOT extract:
- ephemeral facts ("they are tired today", "they just got coffee")
- restatements of the assistant's own persona
- generic facts about the world (capital of France etc.)

Output JSON ONLY in this exact shape, no prose, no fences:
{{"facts": [
  {{"text": "<one short sentence>", "tags": ["<tag1>", ...], "confidence": <0.0..1.0>}}
]}}

Empty list `{{"facts": []}}` is a valid answer. Aim for QUALITY: 0-5
facts is normal, never more than 8 per pass.

Recent turns:
{episodes_block}
"""


@dataclass
class SleepStats:
    runs: int = 0
    skipped_no_episodes: int = 0
    skipped_low_salience: int = 0
    skipped_cooldown: int = 0
    facts_upserted: int = 0
    episodes_consumed: int = 0
    last_run_at: float | None = None
    last_error: str | None = None


@dataclass
class _Cursor:
    """In-memory + on-disk consolidation pointer per (channel, peer)."""

    last_ts_by_key: dict[str, str] = field(default_factory=dict)
    last_run_at_by_key: dict[str, float] = field(default_factory=dict)


def _key(channel: str, peer: str) -> str:
    return f"{channel}:{peer}"


@dataclass
class Sleep:
    """The consolidation pass. One instance per cortex; many calls per uptime.

    `language` is the LLM driver (must implement `.think(messages, ...) -> Utterance`).
    `episodes` and `facts` are the two stores. `state_path` is where the
    cursor JSON lives so consolidation survives restarts without
    re-distilling the same turns.
    """

    language: Any
    episodes: EpisodeStore
    facts: FactStore
    state_path: Path
    min_episodes: int = 4
    min_total_salience: float = 0.6
    cooldown_s: float = 60.0
    max_episodes_per_pass: int = 30
    provider: str | None = None
    model: str | None = None
    temperature: float = 0.2
    max_tokens: int = 1024  # JSON facts list can be longer than 512 once tags + confidences land
    stats: SleepStats = field(default_factory=SleepStats)
    _cursor: _Cursor = field(default_factory=_Cursor, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_cursor()

    # ---- public ----------------------------------------------------------

    async def consolidate(
        self,
        *,
        channel: str,
        peer: str,
        force: bool = False,
    ) -> dict[str, Any]:
        """Run one consolidation pass for the given (channel, peer).

        Returns a small dict describing the outcome — useful for the
        TUI's `/sleep` slash command and for tests. The dict's `status`
        is one of: `ok`, `skipped_no_episodes`, `skipped_low_salience`,
        `skipped_cooldown`, `error`.
        """

        async with self._lock:
            self.stats.runs += 1
            key = _key(channel, peer)
            now = asyncio.get_event_loop().time()
            last_ts = self._cursor.last_ts_by_key.get(key)
            last_run = self._cursor.last_run_at_by_key.get(key, 0.0)

            if not force and now - last_run < self.cooldown_s:
                self.stats.skipped_cooldown += 1
                return {"status": "skipped_cooldown", "channel": channel, "peer": peer}

            new_eps = list(self.episodes.iter_since(channel=channel, peer=peer, ts=last_ts))
            new_eps = [ep for ep in new_eps if not ep.consolidated]
            if not force and len(new_eps) < self.min_episodes:
                self.stats.skipped_no_episodes += 1
                return {
                    "status": "skipped_no_episodes",
                    "channel": channel,
                    "peer": peer,
                    "have": len(new_eps),
                    "need": self.min_episodes,
                }
            if not new_eps:
                self.stats.skipped_no_episodes += 1
                return {"status": "skipped_no_episodes", "channel": channel, "peer": peer, "have": 0}

            total_salience = sum(ep.affect.salience for ep in new_eps)
            if not force and total_salience < self.min_total_salience:
                self.stats.skipped_low_salience += 1
                return {
                    "status": "skipped_low_salience",
                    "channel": channel,
                    "peer": peer,
                    "salience": round(total_salience, 3),
                    "min": self.min_total_salience,
                }

            batch = new_eps[: self.max_episodes_per_pass]
            try:
                facts_extracted = await self._distill(peer=peer, episodes=batch)
            except Exception as exc:
                self.stats.last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("consolidation: distill failed for %s: %s", key, exc)
                return {"status": "error", "channel": channel, "peer": peer, "error": str(exc)}

            upserted = 0
            for raw in facts_extracted:
                f = self.facts.upsert(
                    peer,
                    text=str(raw.get("text") or "").strip(),
                    tags=tuple(raw.get("tags") or ()),
                    source_episodes=tuple(ep.id for ep in batch),
                    confidence=float(raw.get("confidence") or 0.7),
                )
                if f is not None:
                    upserted += 1

            self.episodes.mark_consolidated(
                channel=channel, peer=peer, episode_ids=[ep.id for ep in batch]
            )

            advanced_to = max((ep.ts for ep in batch), default=last_ts) or last_ts
            self._cursor.last_ts_by_key[key] = advanced_to or ""
            self._cursor.last_run_at_by_key[key] = now
            self._save_cursor()

            self.stats.facts_upserted += upserted
            self.stats.episodes_consumed += len(batch)
            self.stats.last_run_at = now

            return {
                "status": "ok",
                "channel": channel,
                "peer": peer,
                "facts_upserted": upserted,
                "episodes_consumed": len(batch),
                "salience": round(total_salience, 3),
            }

    # ---- internal --------------------------------------------------------

    async def _distill(self, *, peer: str, episodes: list[Episode]) -> list[Mapping[str, Any]]:
        """Send episodes to the LLM, parse JSON facts back."""

        block = _render_episodes_for_prompt(episodes)
        prompt = _SLEEP_PROMPT.format(n=len(episodes), peer=peer, episodes_block=block)
        utt = await self.language.think(
            [{"role": "user", "content": prompt}],
            provider=self.provider,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        text = (getattr(utt, "text", "") or "").strip()
        return _parse_facts_json(text)

    # ---- cursor io -------------------------------------------------------

    def _load_cursor(self) -> None:
        if not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug("consolidation: ignoring unreadable cursor %s: %s", self.state_path, exc)
            return
        if not isinstance(raw, dict):
            return
        last_ts = raw.get("last_ts_by_key") or {}
        last_run = raw.get("last_run_at_by_key") or {}
        if isinstance(last_ts, dict):
            self._cursor.last_ts_by_key = {str(k): str(v) for k, v in last_ts.items()}
        if isinstance(last_run, dict):
            self._cursor.last_run_at_by_key = {str(k): float(v) for k, v in last_run.items()}

    def _save_cursor(self) -> None:
        payload = {
            "last_ts_by_key": self._cursor.last_ts_by_key,
            "last_run_at_by_key": self._cursor.last_run_at_by_key,
        }
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self.state_path)
        except OSError as exc:
            logger.warning("consolidation: failed to save cursor %s: %s", self.state_path, exc)


# ---------------------------------------------------------------------------
# Prompt + parsing helpers (pure)
# ---------------------------------------------------------------------------


def _render_episodes_for_prompt(episodes: list[Episode], *, max_chars_per_turn: int = 360) -> str:
    """Compact representation: one stanza per episode, oldest first."""

    chunks: list[str] = []
    for ep in episodes:
        u = ep.user_text.strip().replace("\n", " ")[:max_chars_per_turn]
        a = ep.assistant_text.strip().replace("\n", " ")[:max_chars_per_turn]
        marker = f"[salience={ep.affect.salience:.2f}]"
        chunks.append(f"--- {ep.ts} {marker}\nuser: {u}\nassistant: {a}")
    return "\n".join(chunks)


_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?|\n?```$", flags=re.MULTILINE)


def _parse_facts_json(text: str) -> list[Mapping[str, Any]]:
    """Tolerant JSON parser for the consolidation reply.

    Small models often wrap JSON in ```json fences, prepend a sentence
    like "Sure, here's the JSON:", or get cut off mid-stream when
    `max_tokens` is too tight. We try increasingly forgiving strategies:

    1. Strip fences, parse the outermost `{...}` blob normally.
    2. If that fails, scrape every well-formed `{...}` object that
       looks like a fact (has a "text" key) directly from the stream —
       this rescues partial replies where the outer array never closed.

    On any failure we return an empty list — the caller treats "no
    facts" as a valid (and safe) outcome and the consolidation cursor
    will not advance, so the next sleep retries the same episodes.
    """

    if not text:
        return []
    cleaned = _FENCE_RE.sub("", text).strip()

    # Strategy 1: well-formed outer object.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        blob = cleaned[start : end + 1]
        try:
            data = json.loads(blob)
            facts = data.get("facts") if isinstance(data, dict) else None
            if isinstance(facts, list):
                out: list[Mapping[str, Any]] = []
                for entry in facts:
                    if isinstance(entry, Mapping) and entry.get("text"):
                        out.append(entry)
                if out:
                    return out
        except json.JSONDecodeError as exc:
            logger.debug("consolidation: malformed outer JSON: %s", exc)

    # Strategy 2: salvage individual fact objects from a truncated reply.
    # Scan for `{ ... }` blobs that have a "text" key and attempt each.
    salvaged: list[Mapping[str, Any]] = []
    for blob in _scan_balanced_objects(cleaned):
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, Mapping) and isinstance(obj.get("text"), str) and obj["text"].strip():
            salvaged.append(obj)
    if salvaged:
        logger.debug("consolidation: salvaged %d facts from truncated reply", len(salvaged))
    return salvaged


def _scan_balanced_objects(text: str) -> list[str]:
    """Yield every balanced `{...}` substring at any nesting depth.

    Maintains a stack of open-brace positions; every `}` pops the
    nearest `{` and emits the substring between them. This way we catch
    the inner fact objects even when the surrounding `{"facts": [...]}`
    wrapper was truncated and never closed.

    Naive about strings — but our schema's "text" values do not contain
    raw `{` or `}` characters in practice, and the worst case is a
    spurious garbage candidate that `json.loads` will reject downstream.
    """

    out: list[str] = []
    stack: list[int] = []
    for i, ch in enumerate(text):
        if ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            start = stack.pop()
            out.append(text[start : i + 1])
    return out


__all__ = [
    "Sleep",
    "SleepStats",
]
