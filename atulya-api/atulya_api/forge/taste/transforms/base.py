"""Base types for Taste transform operations.

Purpose
    Plugin contract for Taste Studio transforms (``raw``, ``spellfix_llm``,
    ``tone_shift``). Each transform reads a set's ``working_payload`` and
    returns an updated payload without touching persistence.

Trigger path
    - ``engine._apply_ops_to_set`` resolves ops via ``registry.get_transform``
      and calls ``transform.run`` for each step in the chain.

Inputs
    - ``TasteTransformContext``: bank id, schema type, resolved LLM config.
    - ``TasteSet``: current working payload (and metadata for context).
    - ``params``: op-specific dict from ``TransformOpSpec``.

Outputs
    - ``TransformResult`` with new payload dict and optional model name for audit log.

Side effects
    - LLM transforms may call external APIs via ``llm_config``; no DB writes here.

Mutability
    Transforms must treat ``taste_set`` as read-only; return new payload in result.
    Engine handles persist vs preview.

Impact radius
    - New transforms register in ``transforms/registry.py`` and appear in catalog.
    - Schema-aware transforms must respect ``ctx.schema_type`` message shape.

Core logic
    - ``BaseTasteTransform.run`` is the extension point; ``op_id`` identifies the op.

Failure modes
    - Unimplemented ``run`` raises ``NotImplementedError``.
    - Invalid params should raise ``TasteValidationError`` from concrete transforms.

Maintenance notes
    - Good: subclass ``BaseTasteTransform``, set ``op_id``, register in registry.
    - Bad: mutate ``taste_set.working_payload`` in place — breaks preview mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atulya_api.engine.llm_wrapper import ConfiguredLLMProvider
    from atulya_api.forge.taste.models import TasteSet


@dataclass
class TasteTransformContext:
    """Runtime context passed to every transform op in a chain."""

    bank_id: str
    schema_type: str
    llm_config: "ConfiguredLLMProvider"
    model_name: str | None = None


@dataclass
class TransformResult:
    """Output of one transform op; engine persists or previews this payload."""

    payload: dict[str, Any]
    model: str | None = None


class BaseTasteTransform:
    """Abstract transform plugin; concrete ops live in sibling modules."""

    op_id: str = "raw"

    async def run(
        self,
        ctx: TasteTransformContext,
        taste_set: "TasteSet",
        params: dict[str, Any],
    ) -> TransformResult:
        raise NotImplementedError
