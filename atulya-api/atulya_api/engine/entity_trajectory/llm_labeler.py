"""LLM proposes discrete states and labels each observation."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from atulya_api.engine.entity_trajectory.models import LLMTrajectoryLabelResponse, TrajectoryObservation

if TYPE_CHECKING:
    from atulya_api.engine.llm_wrapper import LLMConfig

logger = logging.getLogger(__name__)

_PROMPT_VERSION = "v1"


def _build_messages(
    *,
    entity_name: str,
    observations: list[TrajectoryObservation],
    prior_vocabulary: list[str] | None,
) -> tuple[str, str]:
    lines = []
    for i, obs in enumerate(observations, start=1):
        lines.append(f"{i}. [{obs.fact_type}] {obs.fact_text[:1200]}")

    prior_block = ""
    if prior_vocabulary:
        prior_block = (
            "Previously used state names for this entity (reuse when still appropriate, "
            "or extend the set if the narrative clearly needs new states):\n"
            f"{json.dumps(prior_vocabulary)}\n\n"
        )

    system = (
        "You label a temporal progression of memory facts about ONE entity. "
        "Propose a small ordered set of discrete hidden states (2–12 short SCREAMING_SNAKE tokens) "
        "that describe how the entity's situation evolves (e.g. DISCOVERY, IMPLEMENTATION, MAINTENANCE). "
        "Then assign exactly one state from that vocabulary to each numbered fact, in order, "
        "from the perspective of that entity only. "
        "States must be consistent with plausible real-world progression; avoid absurd jumps in the labels. "
        "Respond as JSON with keys state_vocabulary (array of strings) and labels (array of strings, "
        "same length as the number of facts)."
    )

    user = (
        f"Entity canonical name: {entity_name}\n\n"
        f"{prior_block}"
        f"Facts in chronological order ({len(observations)} items):\n" + "\n".join(lines)
    )
    return system, user


async def label_trajectory_with_llm(
    *,
    llm_config: "LLMConfig",
    config: Any,
    entity_name: str,
    observations: list[TrajectoryObservation],
    prior_vocabulary: list[str] | None,
) -> tuple[LLMTrajectoryLabelResponse, str]:
    """Returns validated labels and model name string used."""
    if not observations:
        raise ValueError("observations must be non-empty")

    system, user = _build_messages(
        entity_name=entity_name,
        observations=observations,
        prior_vocabulary=prior_vocabulary,
    )

    raw, _usage = await llm_config.call(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format=LLMTrajectoryLabelResponse,
        scope="entity_trajectory_label",
        temperature=0.2,
        max_completion_tokens=min(4096, getattr(config, "retain_max_completion_tokens", 8192)),
        skip_validation=True,
        return_usage=True,
    )

    if isinstance(raw, dict):
        raw = LLMTrajectoryLabelResponse.model_validate(raw)
    elif not isinstance(raw, LLMTrajectoryLabelResponse):
        raw = LLMTrajectoryLabelResponse.model_validate(raw)

    vocab = [str(s).strip().upper().replace(" ", "_") for s in raw.state_vocabulary if str(s).strip()]
    labels = [str(s).strip().upper().replace(" ", "_") for s in raw.labels]

    # Align length to observations
    n = len(observations)
    if len(labels) > n:
        labels = labels[:n]
    elif len(labels) < n:
        fill = labels[-1] if labels else (vocab[0] if vocab else "UNKNOWN")
        labels.extend([fill] * (n - len(labels)))

    # Map unknown labels to nearest vocabulary token (fallback first state)
    vset = set(vocab)
    fallback = vocab[0] if vocab else "STATE"
    fixed_labels = [lab if lab in vset else fallback for lab in labels]
    if not vocab:
        vocab = sorted(set(fixed_labels))

    normalized = LLMTrajectoryLabelResponse(state_vocabulary=vocab, labels=fixed_labels)
    model_name = f"{getattr(llm_config, 'provider', '')}/{getattr(llm_config, 'model', '')}"
    return normalized, model_name
