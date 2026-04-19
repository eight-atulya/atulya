"""episodes.py — episodic memory. The hippocampus, on disk.

Working memory (cortex/conversation.py) is a *verbatim* replay buffer:
last N turns, sent back into the system prompt so the model has
short-term continuity. Episodic memory is the *richer* layer beneath
it: every turn becomes one structured `Episode` with affect, tool-use
trace, and a free-form digest, persisted forever (or until the operator
forgets it). The consolidation pass reads from this layer to build
durable semantic facts.

Why a separate store from `conversation.py`
-------------------------------------------

Working memory is optimised for *immediate replay* (load fast, slice
to N turns, forget detail). Episodes are optimised for *retrospective
analysis* — we keep affect tags, the list of tools the brain invoked,
and an optional one-line digest so a future consolidation pass or a
`/episodes` command can show "what happened with this peer recently"
without re-deserialising the full conversation. Same data, different
projection; collapsing them would either bloat working memory or
strip episodes of their analytic surface.

Local-first storage
-------------------

One JSONL file per (channel, peer):
`<root>/<channel>/<safe_peer>.jsonl`

Append-only, line-per-episode. Path layout matches `conversation.py`'s
on purpose so any tool that walks one can walk the other. atulya-embed
integration is a *future* additive layer — episodes here are the canonical
local truth so the brain remembers even when the substrate daemon is down.

Naming voice: `EpisodeStore.append`, `recent`, `iter_since`, `top_salient`.
The store is the noun; verbs are short and direct.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from cortex.affect import Affect

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_stem(peer_key: str) -> str:
    """Sanitize an arbitrary peer id into a safe file stem.

    Same shape as `cortex/conversation.py`'s sanitiser — kept as a private
    duplicate (rather than imported) so neither module owns the other.
    Contract: lowercase ASCII alphanumerics plus `_-.+`.
    """

    s = (peer_key or "anon").strip().lower()
    s = re.sub(r"[^a-z0-9_.+-]+", "_", s)
    s = s.strip("._-") or "anon"
    return s[:96]


@dataclass(frozen=True)
class Episode:
    """One stored experience.

    The dataclass is the wire format too — `to_dict` round-trips through
    JSON so the JSONL can be replayed by any tool that knows the schema.
    `digest` is empty until consolidation writes a one-line summary; we
    keep it on the record (rather than in a side file) so a single
    `iter_since` is enough to reconstruct everything.
    """

    id: str
    ts: str  # ISO-8601 UTC
    channel: str
    peer: str
    user_text: str
    assistant_text: str
    tools_used: tuple[str, ...]
    affect: Affect
    surprise: float = 0.0  # 0..1, future hook (prediction-error gating)
    digest: str = ""  # set by consolidation
    consolidated: bool = False  # True once distillation has read this episode

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "channel": self.channel,
            "peer": self.peer,
            "user_text": self.user_text,
            "assistant_text": self.assistant_text,
            "tools_used": list(self.tools_used),
            "affect": self.affect.to_dict(),
            "surprise": round(self.surprise, 4),
            "digest": self.digest,
            "consolidated": self.consolidated,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Episode":
        affect_raw = raw.get("affect") or {}
        affect = Affect(
            valence=float(affect_raw.get("valence", 0.0)),
            arousal=float(affect_raw.get("arousal", 0.0)),
            salience=float(affect_raw.get("salience", 0.0)),
            triggers=tuple(affect_raw.get("triggers") or ()),
        )
        return cls(
            id=str(raw.get("id") or _new_id()),
            ts=str(raw.get("ts") or _now_iso()),
            channel=str(raw.get("channel") or "unknown"),
            peer=str(raw.get("peer") or "anon"),
            user_text=str(raw.get("user_text") or ""),
            assistant_text=str(raw.get("assistant_text") or ""),
            tools_used=tuple(raw.get("tools_used") or ()),
            affect=affect,
            surprise=float(raw.get("surprise") or 0.0),
            digest=str(raw.get("digest") or ""),
            consolidated=bool(raw.get("consolidated") or False),
        )


def _new_id() -> str:
    """Episode id: ts-prefixed UUID4 fragment.

    Sortable-by-id ≈ sortable-by-time, which matters for `iter_since`
    when the JSONL has not been re-sorted on disk.
    """

    return f"{int(time.time() * 1000):013d}-{uuid.uuid4().hex[:8]}"


@dataclass
class EpisodeStore:
    """File-backed episodic memory rooted at a directory.

    One subdirectory per channel; one JSONL per peer inside it. Append
    is locked per-handle; reads do not block writes (we read the whole
    file then return, so a concurrent append might or might not appear
    in the snapshot — acceptable for an in-process store).
    """

    root: Path
    _locks: dict[tuple[str, str], threading.Lock] = field(default_factory=dict, init=False, repr=False)
    _global_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _lock(self, channel: str, peer: str) -> threading.Lock:
        key = (channel, peer)
        with self._global_lock:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
        return lock

    def _path(self, channel: str, peer_key: str) -> Path:
        chan_dir = self.root / _safe_stem(channel)
        chan_dir.mkdir(parents=True, exist_ok=True)
        return chan_dir / f"{_safe_stem(peer_key)}.jsonl"

    # ---- write -----------------------------------------------------------

    def append(
        self,
        *,
        channel: str,
        peer: str,
        user_text: str,
        assistant_text: str,
        tools_used: Iterable[str] = (),
        affect: Affect | None = None,
        surprise: float = 0.0,
    ) -> Episode | None:
        """Persist one new episode. Returns None for empty turns (no signal).

        Both halves of the turn must be empty to skip; an assistant
        emitting an empty reply to a non-empty user message is itself a
        meaningful event (likely a model error) and worth remembering.
        """

        utext = (user_text or "").strip()
        atext = (assistant_text or "").strip()
        if not utext and not atext:
            return None

        ep = Episode(
            id=_new_id(),
            ts=_now_iso(),
            channel=channel,
            peer=peer,
            user_text=utext,
            assistant_text=atext,
            tools_used=tuple(t for t in tools_used if t),
            affect=affect or Affect.neutral(),
            surprise=float(surprise),
        )
        path = self._path(channel, peer)
        line = json.dumps(ep.to_dict(), ensure_ascii=False)
        with self._lock(channel, peer):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return ep

    def mark_consolidated(self, *, channel: str, peer: str, episode_ids: Iterable[str]) -> int:
        """Set `consolidated=True` on the listed episodes.

        Implementation rewrites the file atomically — JSONL doesn't have
        in-place edits, but per-peer transcripts are small enough (KB to
        low MB) that rewriting is cheap and avoids a sidecar index. Returns
        the number of episodes actually mutated (not the count requested).
        """

        ids_set = set(episode_ids)
        if not ids_set:
            return 0
        path = self._path(channel, peer)
        if not path.exists():
            return 0
        mutated = 0
        with self._lock(channel, peer):
            episodes = list(self._iter_path(path))
            new_episodes = []
            for ep in episodes:
                if ep.id in ids_set and not ep.consolidated:
                    ep = Episode(**{**ep.__dict__, "consolidated": True})  # type: ignore[arg-type]
                    mutated += 1
                new_episodes.append(ep)
            tmp = path.with_suffix(path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                for ep in new_episodes:
                    fh.write(json.dumps(ep.to_dict(), ensure_ascii=False) + "\n")
            tmp.replace(path)
        return mutated

    def set_digest(self, *, channel: str, peer: str, episode_id: str, digest: str) -> bool:
        """Attach a one-line digest to a single episode. Returns True if found."""

        path = self._path(channel, peer)
        if not path.exists():
            return False
        with self._lock(channel, peer):
            episodes = list(self._iter_path(path))
            found = False
            for i, ep in enumerate(episodes):
                if ep.id == episode_id:
                    episodes[i] = Episode(**{**ep.__dict__, "digest": digest})  # type: ignore[arg-type]
                    found = True
                    break
            if not found:
                return False
            tmp = path.with_suffix(path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                for ep in episodes:
                    fh.write(json.dumps(ep.to_dict(), ensure_ascii=False) + "\n")
            tmp.replace(path)
        return True

    # ---- read ------------------------------------------------------------

    def recent(self, *, channel: str, peer: str, n: int = 20) -> list[Episode]:
        """The most recent `n` episodes, oldest-first within the slice."""

        path = self._path(channel, peer)
        if not path.exists():
            return []
        all_eps = list(self._iter_path(path))
        return all_eps[-max(0, n) :]

    def iter_since(self, *, channel: str, peer: str, ts: str | None) -> Iterator[Episode]:
        """Yield episodes with `ts > given`. Pass `None` for "everything".

        Used by the consolidation pass to advance one peer at a time; the
        caller stores the cursor and passes it back next sleep.
        """

        path = self._path(channel, peer)
        if not path.exists():
            return iter(())
        episodes = self._iter_path(path)
        if ts is None:
            return episodes
        return (ep for ep in episodes if ep.ts > ts)

    def top_salient(
        self,
        *,
        channel: str,
        peer: str,
        n: int = 3,
        recency_weight: float = 0.4,
    ) -> list[Episode]:
        """Pick the most "memorable" recent episodes for prompt injection.

        Score = `(1 - recency_weight) * affect.salience + recency_weight * recency`.
        `recency` is a [0,1] linear ramp where the most recent episode
        scores 1.0. Without the recency term the brain would keep
        re-surfacing one emotionally charged turn from weeks ago and
        ignore yesterday's calmer but relevant context.
        """

        episodes = self.recent(channel=channel, peer=peer, n=200)
        if not episodes:
            return []
        n = max(0, n)
        if n == 0:
            return []
        m = len(episodes)
        scored: list[tuple[float, Episode]] = []
        for idx, ep in enumerate(episodes):
            recency = (idx + 1) / m  # newest -> 1.0
            score = (1.0 - recency_weight) * ep.affect.salience + recency_weight * recency
            scored.append((score, ep))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [ep for _, ep in scored[:n]]

    def list_peers(self, channel: str) -> list[str]:
        chan_dir = self.root / _safe_stem(channel)
        if not chan_dir.exists():
            return []
        return sorted(p.stem for p in chan_dir.glob("*.jsonl"))

    def list_channels(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(d.name for d in self.root.iterdir() if d.is_dir())

    def clear(self, *, channel: str, peer: str) -> int:
        """Wipe one peer's episodes. Returns bytes erased; 0 if nothing existed."""

        path = self._path(channel, peer)
        if not path.exists():
            return 0
        size = path.stat().st_size
        with self._lock(channel, peer):
            try:
                path.unlink()
            except FileNotFoundError:
                return 0
        return size

    # ---- internal --------------------------------------------------------

    def _iter_path(self, path: Path) -> list[Episode]:
        """Read a JSONL file fully; tolerate corrupt lines.

        Episodic memory is meant to survive a partial write or a manual
        edit gone wrong. Bad lines are logged at DEBUG and skipped rather
        than poisoning the whole peer's history.
        """

        out: list[Episode] = []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(Episode.from_dict(json.loads(line)))
                    except (json.JSONDecodeError, TypeError, ValueError) as exc:
                        logger.debug("episodes: skipping malformed line in %s: %s", path, exc)
                        continue
        except FileNotFoundError:
            return []
        return out


def render_episode_block(episodes: list[Episode], *, label: str = "Salient past episodes") -> str:
    """Format episodes for the system prompt — one short line each.

    Token-conservative: digest if present, else first 80 chars of the
    user_text. Salience as a small bracketed marker so the model sees
    which memories are weighty (a real brain remembers WITH affect).
    """

    if not episodes:
        return ""
    lines = [f"{label}:"]
    for ep in episodes:
        line_body = ep.digest.strip() or ep.user_text.strip().splitlines()[0] if ep.user_text else ""
        if not line_body:
            line_body = ep.assistant_text.strip().splitlines()[0] if ep.assistant_text else ""
        line_body = line_body[:160]
        marker = ""
        if ep.affect.salience >= 0.6:
            marker = " [strong]"
        elif ep.affect.salience >= 0.3:
            marker = " [notable]"
        lines.append(f"- ({ep.ts[:10]}{marker}) {line_body}")
    return "\n".join(lines)


__all__ = [
    "Episode",
    "EpisodeStore",
    "render_episode_block",
]
