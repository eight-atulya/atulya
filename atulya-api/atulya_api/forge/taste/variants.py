"""Generate similar taste set variants via LLM."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .models import TasteSchemaType, TasteSet
from .validation import validate_payload_for_schema

if TYPE_CHECKING:
    from atulya_api.engine.llm_wrapper import ConfiguredLLMProvider


async def generate_similar_payloads(
    *,
    llm_config: "ConfiguredLLMProvider",
    schema_type: TasteSchemaType,
    seed_payload: dict[str, Any],
    count: int,
    options: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    opts = options or {}
    payload_json = json.dumps(seed_payload, ensure_ascii=False)
    prompt = (
        f"Generate {count} paraphrased variants of this training example. "
        "Preserve intent, labels, roles, and JSON structure. "
        "Return a JSON array of objects only.\n\n"
        f"Seed example:\n{payload_json}"
    )
    if opts.get("instruction"):
        prompt += f"\n\nExtra instruction: {opts['instruction']}"

    response = await llm_config.call(
        messages=[
            {
                "role": "system",
                "content": "You create high-quality fine-tuning dataset variants. Output JSON array only.",
            },
            {"role": "user", "content": prompt},
        ],
        scope="taste_generate_variants",
        temperature=0.7,
        max_completion_tokens=8192,
    )
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
    variants_raw = json.loads(cleaned.strip())
    if not isinstance(variants_raw, list):
        raise ValueError("Variant generator must return a JSON array")

    variants: list[dict[str, Any]] = []
    for item in variants_raw[:count]:
        if not isinstance(item, dict):
            continue
        validate_payload_for_schema(item, schema_type)
        variants.append(item)
    if not variants:
        raise ValueError("Variant generator returned no valid objects")
    return variants


async def generate_variants_for_set(
    *,
    llm_config: "ConfiguredLLMProvider",
    schema_type: TasteSchemaType,
    taste_set: TasteSet,
    count: int,
    options: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    seed = taste_set.working_payload or taste_set.source_payload
    return await generate_similar_payloads(
        llm_config=llm_config,
        schema_type=schema_type,
        seed_payload=seed,
        count=count,
        options=options,
    )
