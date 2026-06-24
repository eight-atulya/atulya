"""Transform operation registry for Taste Studio."""

from __future__ import annotations

from typing import Any

from atulya_api.forge.taste.errors import TasteValidationError

from .raw import RawTransform
from .spellfix_llm import SpellfixLlmTransform
from .tone_shift import ToneShiftTransform

_TRANSFORMS: dict[str, Any] = {
    "raw": RawTransform,
    "spellfix_llm": SpellfixLlmTransform,
    "tone_shift": ToneShiftTransform,
}

TRANSFORM_METADATA: dict[str, dict[str, str]] = {
    "raw": {"title": "No change", "description": "Identity transform for chain baselines."},
    "spellfix_llm": {
        "title": "Spellfix",
        "description": "Fix spelling and grammar while preserving meaning.",
    },
    "tone_shift": {
        "title": "Tone shift",
        "description": "Rewrite tone (concise, formal, friendly).",
    },
}


def get_transform(op_id: str) -> Any:
    cls = _TRANSFORMS.get(op_id)
    if not cls:
        raise TasteValidationError(f"Unknown taste transform: {op_id}", field="ops")
    return cls()


def list_transform_ops() -> list[dict[str, str]]:
    return [{"op_id": op_id, **meta} for op_id, meta in TRANSFORM_METADATA.items() if op_id != "raw"]
