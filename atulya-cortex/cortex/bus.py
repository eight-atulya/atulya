"""bus.py — the only types passed between cortex modules.

If a value crosses a module boundary in `atulya-cortex/`, it MUST be one of
the Pydantic models defined here. No ad-hoc dicts, no per-module shapes.

The bus types are intentionally narrow:
- `Stimulus`   — what a Sensor perceived. Always carries enough envelope to
                 route a reply back through the matching Motor.
- `Recollection` — one memory the Hippocampus surfaced for the Cortex.
- `Thought`    — the in-flight scratchpad the Cortex holds while reflecting.
- `Action`     — discriminated union of "what the Cortex decided to do".
- `Intent`     — `Action` + envelope, ready for a Motor.
- `Reflex`     — a Brainstem pre-Cortex decision (allow / deny / pair / sandbox).

Any new bus type lands in this file. Per the biomimetic charter, peripheral
modules MUST NOT define their own cross-boundary types.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

# Channel ids are opaque strings in the form "<channel>:<peer_id>".
# Examples: "tui:local", "telegram:123456", "whatsapp:5511999..."
ChannelId = str
SenderId = str

# Memory kinds correspond to the brain.md taxonomy.
MemoryKind = Literal["episodic", "semantic", "procedural", "emotional"]

# Recall budget — maps to atulya-embed budget enum.
Budget = Literal["small", "mid", "large"]

# Reflex decisions.
ReflexDecision = Literal["allow", "deny", "pair", "sandbox"]

# Action kinds — the discriminated union the Cortex produces.
# - "reply"     : send `payload["text"]` back through the inbound channel.
# - "speak"     : voice the `payload["text"]` through the Mouth motor (TTS).
# - "tool_call" : run tool `payload["name"]` with `payload["arguments"]` via Hand.
# - "delegate"  : spawn a subagent on `payload["goal"]` via Body.
# - "noop"      : do nothing (used for breath / dream / silent acks).
ActionKind = Literal["reply", "speak", "tool_call", "delegate", "noop"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MediaRef(BaseModel):
    """A reference to non-text content attached to a stimulus."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["image", "audio", "video", "file"]
    uri: str
    mime: str | None = None
    bytes_len: int | None = None


class Stimulus(BaseModel):
    """Anything a sensor perceived. The thing the brain reacts to."""

    model_config = ConfigDict(extra="forbid")

    channel: ChannelId
    sender: SenderId
    text: str | None = None
    media: list[MediaRef] = Field(default_factory=list)
    received_at: datetime = Field(default_factory=_now)
    raw: dict[str, Any] = Field(default_factory=dict)


class Recollection(BaseModel):
    """A single memory the hippocampus surfaced."""

    model_config = ConfigDict(extra="forbid")

    kind: MemoryKind
    text: str
    score: float
    source: str


class SkillRef(BaseModel):
    """A pointer to a skill discovered on disk under atulya-cortex/life/."""

    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    description: str | None = None


class Thought(BaseModel):
    """An intermediate state the cortex holds while reflecting on a stimulus."""

    model_config = ConfigDict(extra="forbid")

    stimulus: Stimulus
    recollections: list[Recollection] = Field(default_factory=list)
    persona: str = ""
    skills: list[SkillRef] = Field(default_factory=list)
    drafted_action: "Action | None" = None


class Action(BaseModel):
    """Discriminated union: what the cortex decided to do.

    The shape of `payload` depends on `kind`:
    - kind="reply":     {"text": str}
    - kind="tool_call": {"name": str, "arguments": dict}
    - kind="delegate":  {"goal": str, "tools": list[str]}
    - kind="noop":      {}
    """

    model_config = ConfigDict(extra="forbid")

    kind: ActionKind
    payload: dict[str, Any] = Field(default_factory=dict)


class Intent(BaseModel):
    """An Action plus the channel envelope, ready for a Motor."""

    model_config = ConfigDict(extra="forbid")

    action: Action
    channel: ChannelId
    sender: SenderId


class Reflex(BaseModel):
    """Brainstem pre-cortex decision."""

    model_config = ConfigDict(extra="forbid")

    decision: ReflexDecision
    reason: str
    expires_at: datetime | None = None


class ActionResult(BaseModel):
    """The outcome of a Motor.act call. Returned by every Motor."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    detail: str | None = None
    artifact: dict[str, Any] = Field(default_factory=dict)


class Disposition(BaseModel):
    """Affective state attached to a memory bank.

    Read-only adapter onto atulya-embed bank disposition. `mood` and `arousal`
    are bounded floats; `traits` is free-form for future extension.
    """

    model_config = ConfigDict(extra="forbid")

    mood: float = 0.0
    arousal: float = 0.0
    traits: dict[str, Any] = Field(default_factory=dict)


# Resolve forward reference for Thought.drafted_action.
Thought.model_rebuild()


__all__ = [
    "Action",
    "ActionKind",
    "ActionResult",
    "Budget",
    "ChannelId",
    "Disposition",
    "Intent",
    "MediaRef",
    "MemoryKind",
    "Recollection",
    "Reflex",
    "ReflexDecision",
    "SenderId",
    "SkillRef",
    "Stimulus",
    "Thought",
]
