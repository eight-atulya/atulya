"""Identity transform."""

from __future__ import annotations

from typing import Any

from .base import BaseTasteTransform, TasteTransformContext, TransformResult


class RawTransform(BaseTasteTransform):
    op_id = "raw"

    async def run(self, ctx: TasteTransformContext, taste_set: Any, params: dict[str, Any]) -> TransformResult:
        return TransformResult(payload=dict(taste_set.working_payload))
