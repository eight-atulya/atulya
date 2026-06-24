"""LLM spelling and grammar correction transform."""

from __future__ import annotations

import json
from typing import Any

from atulya_api.forge.taste.errors import TasteValidationError
from atulya_api.forge.taste.validation import validate_payload_for_schema

from .base import BaseTasteTransform, TasteTransformContext, TransformResult


class SpellfixLlmTransform(BaseTasteTransform):
    op_id = "spellfix_llm"

    async def run(self, ctx: TasteTransformContext, taste_set: Any, params: dict[str, Any]) -> TransformResult:
        payload_json = json.dumps(taste_set.working_payload, ensure_ascii=False)
        prompt = (
            "Fix spelling and grammar in this training example JSON. "
            "Preserve meaning, structure, keys, and labels exactly. "
            "Return only valid JSON with the same top-level shape.\n\n"
            f"{payload_json}"
        )
        response = await ctx.llm_config.call(
            messages=[
                {"role": "system", "content": "You are a careful dataset editor. Output JSON only."},
                {"role": "user", "content": prompt},
            ],
            scope="taste_spellfix",
            temperature=0.1,
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
            raise TasteValidationError(f"spellfix_llm returned invalid JSON: {exc}", field="ops") from exc
        if not isinstance(updated, dict):
            raise TasteValidationError("spellfix_llm must return a JSON object", field="ops")
        validate_payload_for_schema(updated, ctx.schema_type)
        return TransformResult(payload=updated, model=ctx.model_name)
