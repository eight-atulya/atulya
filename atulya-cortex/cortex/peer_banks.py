"""peer_banks.py — stable atulya-embed bank ids per cortex profile + remote peer.

Each (cortex profile, peer) pair maps to one `bank_id` string. Banks are
created lazily via the client's `acreate_bank` (HTTP PUT — idempotent).

Naming voice: `peer_bank_id` is the noun phrase; channel roots like
``whatsapp`` / ``telegram`` are checked elsewhere against
``memory.peer_banks_channels`` in config.
"""

from __future__ import annotations

import hashlib
import re


def _slug(s: str, *, max_len: int) -> str:
    s = (s or "anon").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_") or "anon"
    return s[:max_len]


def peer_bank_id(cortex_profile: str, peer_key: str) -> str:
    """Return a filesystem- and URL-safe bank id for this profile + peer.

    Format: ``cortex_<profile>_<peer>`` with aggressive shortening if the
    combined id would exceed ~120 characters (embed / API limits).
    """

    prof = _slug(cortex_profile, max_len=32)
    peer_s = _slug(peer_key, max_len=80)
    prefix = f"cortex_{prof}_"
    cand = prefix + peer_s
    if len(cand) <= 120:
        return cand
    digest = hashlib.sha256(peer_key.encode("utf-8")).hexdigest()[:28]
    return f"{prefix}{digest}"


__all__ = ["peer_bank_id"]
