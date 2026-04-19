"""hippocampus.py — encodes new memories into the durable substrate.

The Hippocampus is the brain's encoder. It takes a Stimulus and writes it
to atulya-embed via `aretain`. Cortex's `MemoryKind` is encoded as a
substrate tag (`cortex:kind:<kind>`) so Recall can filter on it later.

The hippocampus is intentionally thin — it is a stateless adapter between
the cortex bus and the atulya-embed retain API. All structural logic
(scoring, ranking, budget) lives in `recall.py`; all in-process storage
(LRU, conversation buffer) lives in `working_memory.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cortex.bus import MemoryKind, Stimulus

if TYPE_CHECKING:  # pragma: no cover - typing only
    from atulya import AtulyaEmbedded


CORTEX_KIND_TAG_PREFIX = "cortex:kind:"
CORTEX_CHANNEL_TAG_PREFIX = "cortex:channel:"
CORTEX_SENDER_TAG_PREFIX = "cortex:sender:"
DEFAULT_BANK = "atulya-cortex"


def kind_tag(kind: MemoryKind) -> str:
    """Return the canonical substrate tag for a cortex memory kind."""

    return f"{CORTEX_KIND_TAG_PREFIX}{kind}"


def channel_tag(channel: str) -> str:
    return f"{CORTEX_CHANNEL_TAG_PREFIX}{channel}"


def sender_tag(sender: str) -> str:
    return f"{CORTEX_SENDER_TAG_PREFIX}{sender}"


class Hippocampus:
    """Encodes stimuli into the durable substrate via atulya-embed."""

    def __init__(self, embedded: "AtulyaEmbedded", *, default_bank: str = DEFAULT_BANK) -> None:
        self._embedded = embedded
        self._default_bank = default_bank

    @property
    def default_bank(self) -> str:
        return self._default_bank

    def _build_tags(
        self,
        *,
        kind: MemoryKind,
        stimulus: Stimulus | None,
        extra_tags: list[str] | None,
    ) -> list[str]:
        tags = [kind_tag(kind)]
        if stimulus is not None:
            tags.append(channel_tag(stimulus.channel))
            tags.append(sender_tag(stimulus.sender))
        if extra_tags:
            for t in extra_tags:
                if t and t not in tags:
                    tags.append(t)
        return tags

    async def encode(
        self,
        stimulus: Stimulus,
        *,
        kind: MemoryKind,
        bank: str | None = None,
        extra_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Persist a stimulus as a memory of the given kind. Returns the substrate receipt."""

        if stimulus.text is None or not stimulus.text.strip():
            return {"skipped": True, "reason": "empty stimulus text"}

        target_bank = bank or self._default_bank
        tags = self._build_tags(kind=kind, stimulus=stimulus, extra_tags=extra_tags)

        response = await self._embedded.aretain(
            bank_id=target_bank,
            content=stimulus.text,
            timestamp=stimulus.received_at,
            context=f"channel={stimulus.channel} sender={stimulus.sender}",
            metadata={"channel": stimulus.channel, "sender": stimulus.sender},
            tags=tags,
        )

        return {
            "ok": True,
            "bank_id": target_bank,
            "kind": kind,
            "tags": tags,
            "raw": _try_to_dict(response),
        }

    async def encode_text(
        self,
        text: str,
        *,
        kind: MemoryKind,
        bank: str | None = None,
        extra_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Convenience: encode a raw text body without a Stimulus envelope.

        Used by `dream/skill_distill.py` which writes lessons that did not
        originate from a single inbound stimulus.
        """

        if not text or not text.strip():
            return {"skipped": True, "reason": "empty text"}

        target_bank = bank or self._default_bank
        tags = self._build_tags(kind=kind, stimulus=None, extra_tags=extra_tags)

        response = await self._embedded.aretain(
            bank_id=target_bank,
            content=text,
            tags=tags,
        )
        return {
            "ok": True,
            "bank_id": target_bank,
            "kind": kind,
            "tags": tags,
            "raw": _try_to_dict(response),
        }


def _try_to_dict(obj: Any) -> Any:
    """Best-effort conversion of an atulya-client response to a plain dict."""

    if obj is None:
        return None
    for attr in ("model_dump", "to_dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:  # pragma: no cover - defensive
                continue
    if isinstance(obj, dict):
        return obj
    return repr(obj)


__all__ = [
    "CORTEX_CHANNEL_TAG_PREFIX",
    "CORTEX_KIND_TAG_PREFIX",
    "CORTEX_SENDER_TAG_PREFIX",
    "DEFAULT_BANK",
    "Hippocampus",
    "channel_tag",
    "kind_tag",
    "sender_tag",
]
