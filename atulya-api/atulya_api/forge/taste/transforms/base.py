"""Base types for Taste transform operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atulya_api.engine.llm_wrapper import ConfiguredLLMProvider
    from atulya_api.forge.taste.models import TasteSet


@dataclass
class TasteTransformContext:
    bank_id: str
    schema_type: str
    llm_config: "ConfiguredLLMProvider"
    model_name: str | None = None


@dataclass
class TransformResult:
    payload: dict[str, Any]
    model: str | None = None


class BaseTasteTransform:
    op_id: str = "raw"

    async def run(
        self,
        ctx: TasteTransformContext,
        taste_set: "TasteSet",
        params: dict[str, Any],
    ) -> TransformResult:
        raise NotImplementedError
