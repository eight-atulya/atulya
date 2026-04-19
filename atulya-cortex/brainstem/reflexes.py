"""reflexes.py — pre-cortex guards.

Every `Stimulus` passes through a stack of `Reflex` evaluators before the
cortex sees it. Reflexes are fast, side-effect-light, and return one of:

- `allow`   : pass through to the cortex unchanged.
- `deny`    : drop the stimulus (with a logged reason).
- `pair`    : the channel is unknown; need a human-in-the-loop pairing step.
- `sandbox` : pass through but downgrade trust (no tool_call / delegate).

In v1 we ship two reflexes:

- `Allowlist`     — declarative allow/deny by channel id (with prefix
                    wildcards) and a `default_decision`.
- `DMPairing`     — file-backed pairing store; first message from a new
                    channel returns `pair`, the operator approves out of
                    band, and subsequent messages are `allow`ed.

`ReflexChain` runs reflexes in order; first non-`allow` wins.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence, get_args

from cortex.bus import Reflex, ReflexDecision, Stimulus


def _now() -> datetime:
    return datetime.now(timezone.utc)


_VALID_DECISIONS: frozenset[str] = frozenset(get_args(ReflexDecision))


class Allowlist:
    """Declarative allow/deny by channel id with prefix wildcards."""

    def __init__(
        self,
        *,
        allow: Sequence[str] = (),
        deny: Sequence[str] = (),
        default_decision: ReflexDecision = "pair",
        sandbox: Sequence[str] = (),
    ) -> None:
        if default_decision not in _VALID_DECISIONS:
            raise ValueError(
                f"unknown default_decision={default_decision!r}; expected one of {sorted(_VALID_DECISIONS)}"
            )
        self._allow = tuple(allow)
        self._deny = tuple(deny)
        self._sandbox = tuple(sandbox)
        self._default: ReflexDecision = default_decision

    @staticmethod
    def _matches(channel: str, patterns: Iterable[str]) -> bool:
        for pat in patterns:
            if pat == channel:
                return True
            if pat.endswith("*") and channel.startswith(pat[:-1]):
                return True
        return False

    async def evaluate(self, stimulus: Stimulus) -> Reflex:
        channel = stimulus.channel
        if self._matches(channel, self._deny):
            return Reflex(decision="deny", reason=f"deny-list match for {channel}")
        if self._matches(channel, self._allow):
            return Reflex(decision="allow", reason=f"allow-list match for {channel}")
        if self._matches(channel, self._sandbox):
            return Reflex(decision="sandbox", reason=f"sandbox-list match for {channel}")
        return Reflex(decision=self._default, reason=f"default for {channel}")


class DMPairing:
    """File-backed pairing store.

    The store is a JSON file mapping `channel_id -> {status, paired_at}`.
    Status values: `"pending" | "approved" | "rejected"`.

    First message from a never-seen channel: persists `pending`, returns
    `pair`. Subsequent messages while pending: keep returning `pair`
    (the cortex/Reply layer renders a "waiting on operator" reply).
    Approved channels return `allow`. Rejected returns `deny`.

    The operator approves a channel out of band: `pairing.approve(channel)`.
    """

    def __init__(self, store_path: str | Path) -> None:
        self._path = Path(store_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    def _load(self) -> dict[str, dict]:
        if not self._path.exists():
            return {}
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return {}
        if not text.strip():
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            channel: dict(entry)
            for channel, entry in data.items()
            if isinstance(channel, str) and isinstance(entry, dict)
        }

    def _save(self) -> None:
        # Atomic write so a crash mid-write never corrupts the pairing store.
        d = self._path.parent
        d.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(d), prefix=".pairings-", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._state, fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def list(self) -> list[dict]:
        """Return current pairings as a list of `{channel, status, paired_at}`
        dicts, sorted by channel id. Used by the future `pairing list` CLI."""

        return [{"channel": channel, **entry} for channel, entry in sorted(self._state.items())]

    def pending(self) -> list[str]:
        """Return channel ids currently awaiting operator approval."""

        return sorted(channel for channel, entry in self._state.items() if entry.get("status") == "pending")

    def status(self, channel: str) -> str | None:
        entry = self._state.get(channel)
        return entry.get("status") if entry else None

    def approve(self, channel: str) -> None:
        self._state[channel] = {"status": "approved", "paired_at": _now().isoformat()}
        self._save()

    def reject(self, channel: str) -> None:
        self._state[channel] = {"status": "rejected", "paired_at": _now().isoformat()}
        self._save()

    def revoke(self, channel: str) -> None:
        self._state.pop(channel, None)
        self._save()

    async def evaluate(self, stimulus: Stimulus) -> Reflex:
        st = self.status(stimulus.channel)
        if st == "approved":
            return Reflex(decision="allow", reason="paired")
        if st == "rejected":
            return Reflex(decision="deny", reason="pairing rejected")
        if st is None:
            self._state[stimulus.channel] = {
                "status": "pending",
                "paired_at": _now().isoformat(),
            }
            self._save()
            return Reflex(
                decision="pair",
                reason="new channel; awaiting operator approval",
                expires_at=_now() + timedelta(days=7),
            )
        return Reflex(decision="pair", reason="pairing pending")


class ReflexChain:
    """Run reflexes in order; first non-`allow` wins."""

    def __init__(self, reflexes: Sequence[object]) -> None:
        self._reflexes = list(reflexes)

    async def evaluate(self, stimulus: Stimulus) -> Reflex:
        if not self._reflexes:
            return Reflex(decision="allow", reason="empty reflex chain")
        last: Reflex | None = None
        for r in self._reflexes:
            decision: Reflex = await r.evaluate(stimulus)  # type: ignore[union-attr]
            if decision.decision != "allow":
                return decision
            last = decision
        return last or Reflex(decision="allow", reason="all reflexes allowed")


__all__ = ["Allowlist", "DMPairing", "ReflexChain"]
