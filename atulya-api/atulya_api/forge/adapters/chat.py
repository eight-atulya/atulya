"""Normalize chat exports into retain batch payloads."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from ..models import RetainBatchItem


def _parse_datetime(value: str | None, fallback: datetime | None = None) -> datetime:
    if not value:
        return fallback or datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return fallback or datetime.now(timezone.utc)


def _normalize_turn(turn: dict[str, Any]) -> dict[str, Any]:
    if "role" in turn and "content" in turn:
        return {"role": turn["role"], "content": turn["content"]}
    if "speaker" in turn and "text" in turn:
        role = "user" if turn.get("speaker", "").lower() in {"user", "human", "customer"} else "assistant"
        return {"role": role, "content": turn["text"], "speaker": turn["speaker"]}
    if "text" in turn:
        return {"role": "user", "content": turn["text"]}
    raise ValueError(f"Unsupported turn shape: {turn}")


class ForgeChatAdapter:
    """Convert chat/session JSON into retain batch items."""

    adapter_id = "chat"

    def normalize(self, payload: dict[str, Any]) -> list[RetainBatchItem]:
        """Accept sessions list or a single conversation with session_N keys."""
        tags = list(payload.get("tags") or [])
        default_context = payload.get("context", "forge chat ingest")
        items: list[RetainBatchItem] = []

        if "sessions" in payload:
            for idx, session in enumerate(payload["sessions"]):
                items.append(self._session_to_retain(session, idx, tags, default_context))
            return items

        conversation = payload.get("conversation") or {}
        if conversation:
            session_idx = 1
            while True:
                key = f"session_{session_idx}"
                if key not in conversation:
                    break
                date_key = f"session_{session_idx}_date_time"
                session = {
                    "session_id": f"session_{session_idx}",
                    "event_date": conversation.get(date_key),
                    "turns": conversation[key],
                    "context": payload.get("context") or f"Session {session_idx}",
                }
                items.append(self._session_to_retain(session, session_idx - 1, tags, default_context))
                session_idx += 1
            if items:
                return items

        if "turns" in payload:
            items.append(self._session_to_retain(payload, 0, tags, default_context))
            return items

        raise ValueError("chat payload must include sessions, conversation, or turns")

    def _session_to_retain(
        self,
        session: dict[str, Any],
        idx: int,
        tags: list[str],
        default_context: str,
    ) -> RetainBatchItem:
        turns_raw = session.get("turns") or session.get("messages") or []
        turns = [_normalize_turn(t) for t in turns_raw]
        event_date = _parse_datetime(session.get("event_date"))
        session_id = session.get("session_id") or f"session_{idx + 1}"
        document_id = session.get("document_id") or f"forge_chat_{session_id}_{uuid.uuid4().hex[:8]}"
        session_tags = list(tags) + list(session.get("tags") or [])
        return {
            "content": json.dumps(turns),
            "context": session.get("context") or default_context,
            "event_date": event_date,
            "document_id": document_id,
            "tags": session_tags,
        }
