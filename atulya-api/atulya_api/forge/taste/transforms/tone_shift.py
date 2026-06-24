"""LLM tone rewrite transform."""

from __future__ import annotations

import json
from typing import Any

from atulya_api.forge.taste.errors import TasteValidationError
from atulya_api.forge.taste.validation import validate_payload_for_schema

from .base import BaseTasteTransform, TasteTransformContext, TransformResult

_TONE_HINTS = {
    "concise": "Make the text shorter and more direct while preserving facts and labels.",
    "formal": "Rewrite in a formal professional tone while preserving facts and labels.",
    "friendly": "Rewrite in a warm conversational tone while preserving facts and labels.",
}


class ToneShiftTransform(BaseTasteTransform):
    op_id = "tone_shift"

    async def run(self, ctx: TasteTransformContext, taste_set: Any, params: dict[str, Any]) -> TransformResult:
        tone = str(params.get("tone") or "concise")
        hint = _TONE_HINTS.get(tone, _TONE_HINTS["concise"])
        payload_json = json.dumps(taste_set.working_payload, ensure_ascii=False)
        prompt = f"{hint}\nKeep the same JSON structure and training labels. Return only valid JSON.\n\n{payload_json}"
        response = await ctx.llm_config.call(
            messages=[
                {"role": "system", "content": "You are a careful dataset editor. Output JSON only."},
                {"role": "user", "content": prompt},
            ],
            scope="taste_tone_shift",
            temperature=0.4,
            max_completion_tokens=4096,
        )
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
        try:
            updated = json.loads(cleaned.strip())
        except json.JSONDecodeError as exc:
            raise TasteValidationError(f"tone_shift returned invalid JSON: {exc}", field="ops") from exc
        if not isinstance(updated, dict):
            raise TasteValidationError("tone_shift must return a JSON object", field="ops")
        validate_payload_for_schema(updated, ctx.schema_type)
        return TransformResult(payload=updated, model=ctx.model_name)
