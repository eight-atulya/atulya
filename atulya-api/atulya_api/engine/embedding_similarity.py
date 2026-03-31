"""
Helpers for working with stored embedding vectors.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def parse_embedding_text(value: str | None) -> list[float] | None:
    """Parse a pgvector text value like ``"[0.1,0.2]"`` into a float list."""
    if not value:
        return None

    stripped = value.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        stripped = stripped[1:-1]

    if not stripped:
        return None

    try:
        return [float(item) for item in stripped.split(",")]
    except ValueError:
        return None


def cosine_similarity(left: Sequence[float] | None, right: Sequence[float] | None) -> float | None:
    """Return cosine similarity for two vectors, or ``None`` if unavailable."""
    if left is None or right is None or len(left) != len(right) or not left:
        return None

    numerator = sum(left_value * right_value for left_value, right_value in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(left_value * left_value for left_value in left))
    right_norm = math.sqrt(sum(right_value * right_value for right_value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return None
    return numerator / (left_norm * right_norm)
