"""
Shared JSONB decoding for asyncpg / PostgreSQL.

Drivers may return jsonb as dict/list, as raw JSON strings, or (if mis-typed) text.
Never call list() on an unknown value — iterate character-wise for str.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def decode_jsonb(raw_value: Any, default: Any) -> Any:
    """Decode asyncpg JSONB values that may already be deserialized or still be JSON text."""
    if raw_value is None:
        return default
    if isinstance(raw_value, (dict, list)):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            return default
    return default
