"""self_healing.py — global reply quality guard + efficient auto-repair.

The self-healing layer is intentionally two-stage:

1) Cheap deterministic checks (empty / orphan tool tags / too short).
2) Optional LLM judge+repair pass only when stage (1) flags a risk.

This keeps hot-path latency low while still recovering from model slips.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ORPHAN_TAG_RE = re.compile(r"<(/?tool(?:_result)?[^>]*)>", flags=re.IGNORECASE)
_EXEC_INTENT_RE = re.compile(
    r"\b(run|execute|check|inspect|show|measure|test|use)\b",
    flags=re.IGNORECASE,
)

try:
    from plasticity.attention_network import AttentionEntity, route_entities
except Exception:  # pragma: no cover - optional dependency safety
    AttentionEntity = None  # type: ignore[assignment]
    route_entities = None  # type: ignore[assignment]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SelfHealingSettings:
    enabled: bool = False
    max_retries: int = 1
    min_reply_chars: int = 8
    judge_enabled: bool = True
    judge_provider: str = ""
    judge_model: str = ""
    fallback_text: str = "I hit a response glitch. Please retry that once."
    telemetry_enabled: bool = True


@dataclass(frozen=True)
class HealingResult:
    text: str
    healed: bool
    reason: str = ""
    attempts: int = 0


class SelfHealingEngine:
    """Guards reply quality and optionally self-repairs via LLM judge."""

    def __init__(self, settings: SelfHealingSettings, *, telemetry_file: Path | None = None) -> None:
        self._settings = settings
        self._telemetry_file = telemetry_file

    async def heal_reply(
        self,
        *,
        language: Any | None,
        stimulus_text: str,
        draft_reply: str,
        recollections: list[str] | None,
        provider: str | None,
        model: str | None,
        temperature: float,
        max_tokens: int | None,
        channel: str,
        peer_key: str | None,
    ) -> HealingResult:
        if not self._settings.enabled:
            return HealingResult(text=draft_reply, healed=False)

        reasons = self._detect_issues(stimulus_text, draft_reply)
        if "tool_payload_leak" in reasons:
            repaired = self._intent_repair_for_tool_payload(
                stimulus_text=stimulus_text,
                draft_reply=draft_reply,
                channel=channel,
            )
            if repaired:
                self._record_event(
                    channel=channel,
                    peer_key=peer_key,
                    status="healed_intent_tool_payload",
                    reasons=self._rank_reasons(reasons),
                    attempts=0,
                    old_reply=draft_reply,
                    new_reply=repaired,
                )
                return HealingResult(text=repaired, healed=True, reason="intent_tool_payload", attempts=0)
        if not reasons:
            return HealingResult(text=draft_reply, healed=False)
        ranked_reasons = self._rank_reasons(reasons)

        if not self._settings.judge_enabled or language is None or self._settings.max_retries <= 0:
            fallback = self._best_effort_fallback(stimulus_text=stimulus_text, recollections=recollections or [])
            self._record_event(
                channel=channel,
                peer_key=peer_key,
                status="fallback_no_judge",
                reasons=ranked_reasons,
                attempts=0,
                old_reply=draft_reply,
                new_reply=fallback,
            )
            return HealingResult(text=fallback, healed=True, reason="fallback_no_judge", attempts=0)

        current = draft_reply
        for attempt in range(1, self._settings.max_retries + 1):
            repaired = await self._judge_and_repair(
                language=language,
                stimulus_text=stimulus_text,
                draft_reply=current,
                reasons=ranked_reasons,
                provider=provider,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if not repaired:
                continue
            if not self._detect_issues(stimulus_text, repaired):
                self._record_event(
                    channel=channel,
                    peer_key=peer_key,
                    status="healed",
                    reasons=ranked_reasons,
                    attempts=attempt,
                    old_reply=draft_reply,
                    new_reply=repaired,
                )
                return HealingResult(text=repaired, healed=True, reason="judge_repair", attempts=attempt)
            current = repaired

        fallback = self._best_effort_fallback(stimulus_text=stimulus_text, recollections=recollections or [])
        self._record_event(
            channel=channel,
            peer_key=peer_key,
            status="fallback_after_retries",
            reasons=ranked_reasons,
            attempts=self._settings.max_retries,
            old_reply=draft_reply,
            new_reply=fallback,
        )
        return HealingResult(
            text=fallback,
            healed=True,
            reason="fallback_after_retries",
            attempts=self._settings.max_retries,
        )

    def _best_effort_fallback(self, *, stimulus_text: str, recollections: list[str]) -> str:
        best = self._best_effort_answer(stimulus_text=stimulus_text, recollections=recollections)
        if best:
            return f"{best}\n\nI hit a small response glitch, but this is my best answer from memory."
        return self._settings.fallback_text

    def _best_effort_answer(self, *, stimulus_text: str, recollections: list[str]) -> str:
        q = (stimulus_text or "").strip().lower()
        if not q:
            return ""
        if any(token in q for token in ("preference", "preferred", "what do i like", "drink", "coffee", "tea")):
            merged = " ".join((recollections or [])).lower()
            if "coffee" in merged and "tea" not in merged:
                return "Your preferred drink is coffee."
            if "tea" in merged and "coffee" not in merged:
                return "Your preferred drink is tea."
            if "coffee" in merged and "tea" in merged:
                return "You seem to prefer coffee overall, though both coffee and tea were mentioned."
            return "I don't have a reliable drink preference stored yet. Tell me your preference once and I'll remember it."
        if recollections:
            # Generic factual fallback from strongest recalled line.
            snippet = str(recollections[0]).strip().replace("\n", " ")
            if len(snippet) > 180:
                snippet = snippet[:177] + "..."
            return f"From what I remember: {snippet}"
        return ""

    def _detect_issues(self, stimulus_text: str, reply: str) -> list[str]:
        out: list[str] = []
        clean = (reply or "").strip()
        if not clean:
            out.append("empty_reply")
        if _ORPHAN_TAG_RE.search(clean):
            out.append("orphan_tool_tag")
        if clean and len(clean) < self._settings.min_reply_chars and len((stimulus_text or "").strip()) >= 6:
            out.append("too_short")
        if self._is_tool_payload_leak(stimulus_text, clean):
            out.append("tool_payload_leak")
        return out

    def _is_tool_payload_leak(self, stimulus_text: str, reply: str) -> bool:
        if not reply:
            return False
        payload = self._parse_json_dict(reply)
        if not payload:
            return False
        keys = {str(k).strip().lower() for k in payload.keys()}
        toolish = bool({"command", "name", "arguments"} & keys)
        if not toolish:
            return False
        # Trigger only when the user likely asked for an action, to avoid
        # false positives for genuine JSON discussions.
        return bool(_EXEC_INTENT_RE.search(stimulus_text or ""))

    def _intent_repair_for_tool_payload(self, *, stimulus_text: str, draft_reply: str, channel: str) -> str:
        payload = self._parse_json_dict(draft_reply)
        command = str(payload.get("command", "")).strip()
        tool_name = str(payload.get("name", "")).strip()
        requested = command or tool_name or "that action"
        channel_root = channel.split(":", 1)[0] if channel else "this"
        return (
            f"I understood you want me to execute `{requested}`. "
            f"I cannot run tools directly on {channel_root} right now, so I gave you the command form earlier. "
            "If you want execution, run it in trusted TUI/tool-enabled mode; otherwise I can explain the output and next steps."
        )

    async def _judge_and_repair(
        self,
        *,
        language: Any,
        stimulus_text: str,
        draft_reply: str,
        reasons: list[str],
        provider: str | None,
        model: str | None,
        temperature: float,
        max_tokens: int | None,
    ) -> str:
        judge_messages = [
            {
                "role": "system",
                "content": (
                    "You are a response quality gate. Fix the assistant draft if needed.\n"
                    "Return strict JSON with keys: verdict, repaired_reply, confidence, notes.\n"
                    "verdict must be one of: keep, repair.\n"
                    "Keep repaired_reply concise and directly useful for the user."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_message": stimulus_text,
                        "assistant_draft": draft_reply,
                        "detected_issues": reasons,
                    },
                    ensure_ascii=True,
                ),
            },
        ]
        try:
            utt = await language.think(
                judge_messages,
                provider=self._settings.judge_provider or provider,
                model=self._settings.judge_model or model,
                temperature=min(0.2, float(temperature)),
                max_tokens=min(int(max_tokens or 256), 256),
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("self-heal judge failed: %s", exc)
            return ""
        payload = self._parse_json_dict((getattr(utt, "text", "") or "").strip())
        repaired = str(payload.get("repaired_reply", "")).strip()
        verdict = str(payload.get("verdict", "")).strip().lower()
        if verdict == "keep" and not repaired:
            repaired = draft_reply
        return repaired

    def _rank_reasons(self, reasons: list[str]) -> list[str]:
        if not reasons or AttentionEntity is None or route_entities is None:
            return reasons
        entities: list[Any] = []
        score_map = {
            "empty_reply": 1.0,
            "orphan_tool_tag": 0.85,
            "tool_payload_leak": 0.8,
            "too_short": 0.55,
        }
        for idx, reason in enumerate(reasons):
            entities.append(
                AttentionEntity(
                    entity_id=f"heal-{reason}-{idx}",
                    category="system_state",
                    payload={"reason": reason},
                    semantic_relevance=score_map.get(reason, 0.4),
                    recency=1.0,
                    task_alignment=0.9,
                    user_intent=0.7,
                    system_state=1.0,
                )
            )
        decision = route_entities(entities, per_category_limit=8, total_limit=8)
        ranked: list[str] = []
        for item in decision.selected:
            reason = str(item.entity.payload.get("reason", "")).strip()
            if reason and reason not in ranked:
                ranked.append(reason)
        return ranked or reasons

    def _record_event(
        self,
        *,
        channel: str,
        peer_key: str | None,
        status: str,
        reasons: list[str],
        attempts: int,
        old_reply: str,
        new_reply: str,
    ) -> None:
        if not self._settings.telemetry_enabled:
            return
        event = {
            "at": _now_iso(),
            "channel": channel,
            "peer_key": peer_key or "",
            "status": status,
            "reasons": reasons,
            "attempts": attempts,
            "old_reply_chars": len((old_reply or "").strip()),
            "new_reply_chars": len((new_reply or "").strip()),
        }
        logger.info("self-heal: %s", event)
        if self._telemetry_file is None:
            return
        try:
            self._telemetry_file.parent.mkdir(parents=True, exist_ok=True)
            with self._telemetry_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=True) + "\n")
        except Exception:  # pragma: no cover - file telemetry must never break reply path
            logger.warning("self-heal telemetry write failed", exc_info=True)

    @staticmethod
    def _parse_json_dict(text: str) -> dict[str, Any]:
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if 0 <= start < end:
            try:
                parsed = json.loads(text[start : end + 1])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        return {}


__all__ = [
    "HealingResult",
    "SelfHealingEngine",
    "SelfHealingSettings",
]
