"""conversation.py — per-channel, per-peer conversation transcripts on disk.

The cortex was previously stateless: every inbound stimulus was treated as
turn-zero, which is why a WhatsApp peer asking "what's my name?" got
hallucinated answers — the model genuinely had no memory of the previous
turn. This module gives the brain a working memory.

Each (channel, peer) pair gets its own JSONL transcript. We append on every
turn (atomic POSIX append, one line per record) and read a bounded slice
back into the LLM system prompt on the next turn. No background workers,
no queues, no async I/O — the whole point is that this is cheap enough to
run synchronously inside `Cortex.reflect`.

Layout
------

    <root>/
      tui/local.jsonl
      whatsapp/919999@s.whatsapp.net.jsonl
      telegram/12345.jsonl

Wire format (one JSON object per line; UTF-8, newline-delimited)::

    {"ts": "2026-04-19T20:07:27Z",
     "role": "user" | "assistant" | "system" | "tool",
     "content": "the message text",
     "meta": {...}}                       # optional, free-form

Budgets
-------

`Conversation.recent(turns=8, char_budget=1500)` returns the most recent
exchanges, trimmed from the *front* (oldest) so the model always keeps the
last few turns. This is deliberately small for the kind of 4B-parameter
local models the cortex targets (gemma-4-e2b, qwen-2.5-3b, llama-3.2-3b).
Crank it higher only when you know your model can spend the context.

Naming voice: `ConversationStore.open(channel, peer)` returns a
`Conversation`. `Conversation.append`, `Conversation.recent`, and
`Conversation.clear` are the load-bearing verbs.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)

# Roles we know how to render back to the LLM. Anything else is dropped on
# read so a stale or experimental row never poisons the prompt.
_LLM_ROLES = frozenset({"user", "assistant", "system", "tool"})

# Sanitiser for peer keys -> filesystem-safe stems. WhatsApp JIDs contain
# `@`, `:` (`@lid` participants), `.`, `+` etc. We keep alnum, dash, dot,
# underscore; everything else becomes `_`. Long stems are hashed once so
# we never blow PATH_MAX on a misbehaving channel.
_SAFE_STEM_RE = re.compile(r"[^A-Za-z0-9._@-]+")
_MAX_STEM_LEN = 96


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_stem(peer_key: str) -> str:
    """Turn a free-form peer key (jid, telegram id, ...) into a safe stem.

    We avoid the temptation to base64/hash everything: a human reading the
    transcripts directory should still be able to recognise their own peers
    (`919999@s.whatsapp.net.jsonl` is much more useful than a sha256). For
    pathologically long ids we suffix the original with a short hash.
    """

    cleaned = _SAFE_STEM_RE.sub("_", peer_key.strip()) or "_"
    if len(cleaned) <= _MAX_STEM_LEN:
        return cleaned
    import hashlib

    digest = hashlib.sha256(peer_key.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned[: _MAX_STEM_LEN - 9]}_{digest}"


@dataclass(frozen=True)
class Turn:
    """A single line in the transcript, decoded back from JSONL.

    Frozen so callers can hand them around safely; renderers don't need to
    worry about mutation between calls.
    """

    role: str
    content: str
    ts: str
    meta: Mapping[str, Any]

    def to_message(self) -> dict[str, str]:
        """Render this turn as an OpenAI-style chat message."""

        return {"role": self.role, "content": self.content}


class Conversation:
    """An append-only JSONL transcript for one (channel, peer) pair.

    Cheap to construct, cheap to read; one tiny lock per file guards
    against two coroutines (or two threads) interleaving partial JSON
    writes. We do *not* hold the file open between calls — the OS page
    cache handles the rest, and this keeps us safe across forks.
    """

    def __init__(self, path: Path, *, channel: str, peer_key: str) -> None:
        self._path = path
        self._channel = channel
        self._peer_key = peer_key
        # Per-instance lock; the store reuses Conversation objects so the
        # same lock guards every writer to the same file in this process.
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def channel(self) -> str:
        return self._channel

    @property
    def peer_key(self) -> str:
        return self._peer_key

    @property
    def exists(self) -> bool:
        return self._path.exists()

    def append(self, role: str, content: str, *, meta: Mapping[str, Any] | None = None) -> None:
        """Append a single turn to the JSONL transcript.

        Silently no-ops on empty content (so we don't log "" placeholders)
        and on unknown roles (so a future role we don't support yet doesn't
        end up persisted in a way that confuses old readers).
        """

        if not content or not content.strip():
            return
        if role not in _LLM_ROLES:
            logger.debug("conversation %s: dropping unknown role %r", self._path, role)
            return

        record: dict[str, Any] = {
            "ts": _now_iso(),
            "role": role,
            "content": content,
        }
        if meta:
            record["meta"] = dict(meta)
        line = json.dumps(record, ensure_ascii=False) + "\n"

        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Open with O_APPEND for atomic single-line appends across
            # threads. We don't fsync on every line — this is chat history,
            # not a bank ledger; losing a tail row on a kernel panic is
            # an acceptable trade for the latency.
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)

    def recent(
        self,
        *,
        turns: int = 8,
        char_budget: int = 1500,
        roles: Iterable[str] = ("user", "assistant"),
        include_tool_scratchpad: bool = False,
    ) -> list[Turn]:
        """Return the most recent turns, bounded by both turn count and chars.

        We trim from the *front* (oldest) so the model always sees the most
        recent exchange. `roles` filters which lines to surface — by default
        only user/assistant chat (system/tool stays in the file but doesn't
        re-enter the prompt automatically).

        `include_tool_scratchpad` defaults to False: intermediate assistant
        turns written by the deliberation arc (the `<tool name=...>` calls
        tagged with `meta.phase in {"act", "observe"}`) are NOT replayed.
        The final user-facing assistant reply already summarises what the
        brain did, and surfacing the raw tool-call XML back into the next
        system prompt would (a) double the turn-count consumption of the
        bounded replay window — which is how "I'm Anurag" gets silently
        evicted by two bash calls — and (b) confuse small models which
        then try to re-invoke the tool verbatim.
        """

        if turns <= 0 or char_budget <= 0:
            return []
        if not self._path.exists():
            return []

        wanted = frozenset(roles)
        # Read once, parse lazily. Transcripts are short (months of WhatsApp
        # under typical usage easily fit), so a full read is fine and lets
        # us get away without an index. Keep an eye on this if a single
        # peer ever crosses ~10MB; at that point a reverse line-by-line
        # reader becomes worthwhile.
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("could not read transcript %s: %s", self._path, exc)
            return []

        out: list[Turn] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                # A truncated/corrupt line shouldn't kill the loop; skip it
                # and keep going. We log at debug to avoid noisy operators.
                logger.debug("conversation %s: skipping malformed line", self._path)
                continue
            role = rec.get("role")
            content = rec.get("content")
            if role not in wanted or not isinstance(content, str):
                continue
            meta = rec.get("meta") or {}
            # Intermediate deliberation turns (`phase=act` is the tool call,
            # `phase=observe` is the tool result rendered as an assistant
            # message) are scratchpad, not dialogue. Skipping them keeps
            # the replay window focused on real exchanges.
            if not include_tool_scratchpad and isinstance(meta, Mapping):
                phase = meta.get("phase")
                if phase in ("act", "observe"):
                    continue
            out.append(
                Turn(
                    role=role,
                    content=content,
                    ts=str(rec.get("ts", "")),
                    meta=meta,
                )
            )

        # Trim from the front by turn count first, then by char budget. This
        # ordering matters: turn count protects "how many exchanges does the
        # model see" (semantic), char budget protects "how many tokens".
        if len(out) > turns:
            out = out[-turns:]
        # Char budget pass — drop oldest until we fit.
        while out and sum(len(t.content) for t in out) > char_budget:
            out.pop(0)
        return out

    def clear(self) -> int:
        """Wipe this transcript. Returns the byte size we deleted (0 if empty).

        Used by `/forget` and by `cortex conversation forget <peer>`. We
        unlink rather than truncate so an overwrite never produces a
        half-empty file.
        """

        with self._lock:
            if not self._path.exists():
                return 0
            try:
                size = self._path.stat().st_size
            except OSError:
                size = 0
            try:
                self._path.unlink()
            except OSError as exc:
                logger.warning("could not unlink %s: %s", self._path, exc)
                return 0
            return size

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Conversation(channel={self._channel!r}, peer={self._peer_key!r}, path={self._path})"


class ConversationStore:
    """Factory for `Conversation` handles, rooted at one directory.

    The store keeps a small in-memory map from (channel, peer_key) to
    `Conversation` so the same per-instance lock guards every writer
    targeting the same file in this process. Drop / re-pair a peer and
    the next `open` will reuse the on-disk file (we never delete from
    inside `open`).
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._cache: dict[tuple[str, str], Conversation] = {}
        self._cache_lock = threading.Lock()

    @property
    def root(self) -> Path:
        return self._root

    def open(self, channel: str, peer_key: str) -> Conversation:
        """Get or create a `Conversation` handle for this (channel, peer)."""

        key = (channel, peer_key)
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            path = self._root / _safe_stem(channel) / f"{_safe_stem(peer_key)}.jsonl"
            conv = Conversation(path, channel=channel, peer_key=peer_key)
            self._cache[key] = conv
            return conv

    def list_peers(self, channel: str) -> list[str]:
        """List peer keys (decoded from filenames) we have transcripts for.

        Note: lossy when a peer key required hashing in `_safe_stem`. Use
        for diagnostics / `/forget` interactive listing, not for routing.
        """

        ch_dir = self._root / _safe_stem(channel)
        if not ch_dir.exists():
            return []
        return sorted(p.stem for p in ch_dir.glob("*.jsonl"))

    def __repr__(self) -> str:  # pragma: no cover
        return f"ConversationStore(root={self._root})"


def render_history_block(turns: list[Turn], *, label: str = "Recent conversation") -> str:
    """Format a list of turns as a single string block for the system prompt.

    We render in `User: ...` / `Atulya: ...` style instead of injecting raw
    chat messages because small models trained on instruction tuning often
    follow plain text dialogue more reliably than a long replayed message
    array. The block stays in the *system* slot so it doesn't get confused
    with the new user turn.
    """

    if not turns:
        return ""
    lines: list[str] = [f"{label} (oldest first):"]
    for t in turns:
        if t.role == "assistant":
            speaker = "You"
        elif t.role == "user":
            speaker = "User"
        else:
            speaker = t.role.capitalize()
        # One-line preview per turn — the model tracks the gist; full
        # paragraphs blow the small-model context budget for no benefit.
        body = t.content.strip().replace("\n", " ")
        if len(body) > 240:
            body = body[:237] + "..."
        lines.append(f"  {speaker}: {body}")
    return "\n".join(lines)


__all__ = [
    "Conversation",
    "ConversationStore",
    "Turn",
    "render_history_block",
]
