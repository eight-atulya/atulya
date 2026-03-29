"""
Dream/Trance helpers for evidence-grounded foresight generation.
"""

from __future__ import annotations

import html
import math
import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

DreamRunStatus = Literal["success", "low_signal", "duplicate_low_novelty", "failed_llm", "failed_validation"]
DreamMaturityTier = Literal["sparse", "emerging", "mature"]
DreamPredictionStatus = Literal["pending", "confirmed", "contradicted", "unresolved"]
DreamProposalReviewStatus = Literal["proposed", "approved", "rejected", "needs_more_evidence"]
DreamProposalType = Literal["observation", "mental_model", "prediction_candidate", "growth_candidate"]
DreamPredictionHorizon = Literal["near_term", "mid_term", "long_term"]

DEFAULT_DREAM_CONFIG: dict[str, Any] = {
    "enabled": False,
    "trance_enabled": False,
    "trigger_mode": "hybrid",
    "cron_interval_minutes": 180,
    "cooldown_minutes": 60,
    "top_k": 4,
    "max_input_tokens": 900,
    "max_output_tokens": 500,
    "model_preference": "local-first",
    "dream_experience": "hybrid",
    "prediction_horizon": "mixed",
    "auto_write_posture": "aggressive_proposals",
    "promotion_gate": "human_review",
    "worker_prompt": (
        "Generate evidence-grounded foresight. Explain what appears stable, what may change next, "
        "what growth path is forming, and what validations would improve confidence."
    ),
    "write_distilled_summary": False,
    "distillation_mode": "off",  # legacy compatibility, no longer used for dream promotion.
    "distillation_max_fragments": 3,
    "quality_threshold": 0.65,
    "min_recall_results": 2,
    "novelty_threshold": 0.58,
    "validation_lookback_days": 45,
    "max_pending_predictions": 24,
    "max_artifact_bytes": 24_000,
    "language_tone": "plain-layman",
    "enforce_layman": True,
    "value_focus": {"money": 1.0, "time": 1.0, "happiness": 1.0},
    "prompt_template_version": "v3-evidence-foresight",
    "preset": "balanced_org",
}

MAX_HTML_BYTES = 24_000

PRESET_OVERRIDES: dict[str, dict[str, Any]] = {
    "balanced_org": {
        "top_k": 4,
        "min_recall_results": 2,
        "max_input_tokens": 900,
        "max_output_tokens": 520,
        "cooldown_minutes": 60,
        "quality_threshold": 0.66,
        "novelty_threshold": 0.58,
        "validation_lookback_days": 45,
        "value_focus": {"money": 1.0, "time": 1.0, "happiness": 1.0},
    },
    "lean_local": {
        "top_k": 3,
        "min_recall_results": 2,
        "max_input_tokens": 640,
        "max_output_tokens": 420,
        "cooldown_minutes": 90,
        "quality_threshold": 0.7,
        "novelty_threshold": 0.64,
        "validation_lookback_days": 30,
        "enforce_layman": True,
        "value_focus": {"money": 0.8, "time": 1.4, "happiness": 0.8},
    },
    "risk_guard": {
        "top_k": 5,
        "min_recall_results": 3,
        "max_input_tokens": 1100,
        "max_output_tokens": 480,
        "cooldown_minutes": 120,
        "quality_threshold": 0.78,
        "novelty_threshold": 0.66,
        "validation_lookback_days": 60,
        "enforce_layman": True,
        "value_focus": {"money": 0.9, "time": 0.9, "happiness": 1.2},
    },
    "exec_strategy": {
        "top_k": 4,
        "min_recall_results": 2,
        "max_input_tokens": 1000,
        "max_output_tokens": 440,
        "cooldown_minutes": 45,
        "quality_threshold": 0.68,
        "novelty_threshold": 0.6,
        "validation_lookback_days": 45,
        "language_tone": "executive-plain",
        "value_focus": {"money": 1.5, "time": 1.2, "happiness": 0.7},
    },
}


class DreamEvidenceBasis(BaseModel):
    evidence_count: int = 0
    recall_memory_ids: list[str] = Field(default_factory=list)
    recurring_entities: list[str] = Field(default_factory=list)
    recurring_themes: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    graph_signals: list[str] = Field(default_factory=list)
    recency_distribution: dict[str, int] = Field(default_factory=dict)
    unresolved_prediction_backlog: int = 0
    maturity_reason: str | None = None


class DreamClaimConfidence(BaseModel):
    claim: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    basis: str


class DreamConfidenceModel(BaseModel):
    overall: float = Field(default=0.0, ge=0.0, le=1.0)
    calibration_score: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_richness: float = Field(default=0.0, ge=0.0, le=1.0)
    contradiction_pressure: float = Field(default=0.0, ge=0.0, le=1.0)
    prediction_specificity: float = Field(default=0.0, ge=0.0, le=1.0)
    novelty_score: float = Field(default=0.0, ge=0.0, le=1.0)
    per_claim: list[DreamClaimConfidence] = Field(default_factory=list)


class DreamPrediction(BaseModel):
    prediction_id: str | None = None
    title: str
    description: str
    target_ref: str | None = None
    target_kind: Literal["entity", "topic", "bank", "theme", "memory"] = "theme"
    horizon: DreamPredictionHorizon = "near_term"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    success_criteria: list[str] = Field(default_factory=list)
    expiration_window_days: int = Field(default=14, ge=1, le=365)
    status: DreamPredictionStatus = "pending"
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    validation_notes: str | None = None


class DreamGrowthHypothesis(BaseModel):
    title: str
    description: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    signals: list[str] = Field(default_factory=list)
    blind_spot: str | None = None
    opportunity: str | None = None


class DreamPromotionProposal(BaseModel):
    proposal_id: str | None = None
    proposal_type: DreamProposalType
    title: str
    content: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    review_status: DreamProposalReviewStatus = "proposed"
    rationale: str | None = None


class DreamValidationOutcome(BaseModel):
    outcome_id: str | None = None
    prediction_id: str
    status: Literal["confirmed", "contradicted", "request_more_evidence"]
    note: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: str | None = None


class DreamSignals(BaseModel):
    hypotheses: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    recommended_validations: list[str] = Field(default_factory=list)
    candidate_state_changes: list[str] = Field(default_factory=list)


class DreamLLMOutput(BaseModel):
    summary: str
    hypotheses: list[str] = Field(default_factory=list)
    predicted_next_events: list[DreamPrediction] = Field(default_factory=list)
    predicted_state_changes: list[str] = Field(default_factory=list)
    growth_hypotheses: list[DreamGrowthHypothesis] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    recommended_validations: list[str] = Field(default_factory=list)
    promotion_proposals: list[DreamPromotionProposal] = Field(default_factory=list)
    narrative: str


class DreamRunRecord(BaseModel):
    run_id: str
    bank_id: str
    status: DreamRunStatus
    run_type: str
    trigger_source: str
    created_at: str
    updated_at: str | None = None
    narrative_html: str | None = None
    summary: str | None = None
    evidence_basis: DreamEvidenceBasis = Field(default_factory=DreamEvidenceBasis)
    signals: DreamSignals = Field(default_factory=DreamSignals)
    predictions: list[DreamPrediction] = Field(default_factory=list)
    growth_hypotheses: list[DreamGrowthHypothesis] = Field(default_factory=list)
    promotion_proposals: list[DreamPromotionProposal] = Field(default_factory=list)
    validation_outcomes: list[DreamValidationOutcome] = Field(default_factory=list)
    confidence: DreamConfidenceModel = Field(default_factory=DreamConfidenceModel)
    novelty_score: float = Field(default=0.0, ge=0.0, le=1.0)
    maturity_tier: DreamMaturityTier = "sparse"
    failure_reason: str | None = None
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    legacy_run: bool = False
    source_artifact_id: str | None = None


def _apply_preset(cfg: dict[str, Any]) -> dict[str, Any]:
    preset = str(cfg.get("preset", "balanced_org")).strip().lower()
    if preset not in PRESET_OVERRIDES:
        preset = "balanced_org"
    merged = deepcopy(cfg)
    merged["preset"] = preset
    merged.update(deepcopy(PRESET_OVERRIDES[preset]))
    raw_overrides = cfg.get("_raw_overrides")
    if isinstance(raw_overrides, dict):
        merged.update(raw_overrides)
    return merged


def normalize_dream_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    cfg = deepcopy(DEFAULT_DREAM_CONFIG)
    user_raw = raw if isinstance(raw, dict) else {}
    cfg.update(user_raw)
    cfg["_raw_overrides"] = deepcopy(user_raw)
    cfg = _apply_preset(cfg)
    cfg["top_k"] = max(1, min(int(cfg.get("top_k", 4)), 8))
    cfg["max_input_tokens"] = max(128, min(int(cfg.get("max_input_tokens", 900)), 4000))
    cfg["max_output_tokens"] = max(160, min(int(cfg.get("max_output_tokens", 500)), 1600))
    cfg["cooldown_minutes"] = max(5, min(int(cfg.get("cooldown_minutes", 60)), 24 * 60))
    cfg["cron_interval_minutes"] = max(5, min(int(cfg.get("cron_interval_minutes", 180)), 24 * 60))
    cfg["quality_threshold"] = max(0.0, min(float(cfg.get("quality_threshold", 0.65)), 1.0))
    cfg["min_recall_results"] = max(1, min(int(cfg.get("min_recall_results", 2)), 8))
    cfg["distillation_max_fragments"] = max(1, min(int(cfg.get("distillation_max_fragments", 3)), 10))
    cfg["max_artifact_bytes"] = max(4_000, min(int(cfg.get("max_artifact_bytes", MAX_HTML_BYTES)), 120_000))
    cfg["novelty_threshold"] = max(0.0, min(float(cfg.get("novelty_threshold", 0.58)), 1.0))
    cfg["validation_lookback_days"] = max(7, min(int(cfg.get("validation_lookback_days", 45)), 365))
    cfg["max_pending_predictions"] = max(1, min(int(cfg.get("max_pending_predictions", 24)), 200))
    cfg["trigger_mode"] = str(cfg.get("trigger_mode", "hybrid")).lower()
    cfg["distillation_mode"] = str(cfg.get("distillation_mode", "off")).lower()
    if cfg["distillation_mode"] not in ("off", "summary", "fragments"):
        cfg["distillation_mode"] = "off"
    cfg["dream_experience"] = str(cfg.get("dream_experience", "hybrid")).lower()
    if cfg["dream_experience"] not in ("hybrid", "structured", "narrative"):
        cfg["dream_experience"] = "hybrid"
    cfg["prediction_horizon"] = str(cfg.get("prediction_horizon", "mixed")).lower()
    if cfg["prediction_horizon"] not in ("near", "mixed", "far"):
        cfg["prediction_horizon"] = "mixed"
    cfg["auto_write_posture"] = str(cfg.get("auto_write_posture", "aggressive_proposals")).lower()
    cfg["promotion_gate"] = str(cfg.get("promotion_gate", "human_review")).lower()
    cfg["language_tone"] = str(cfg.get("language_tone", "plain-layman")).strip() or "plain-layman"
    cfg["enforce_layman"] = bool(cfg.get("enforce_layman", True))
    focus = cfg.get("value_focus", {})
    if not isinstance(focus, dict):
        focus = {}
    cfg["value_focus"] = {
        "money": max(0.0, min(float(focus.get("money", 1.0)), 3.0)),
        "time": max(0.0, min(float(focus.get("time", 1.0)), 3.0)),
        "happiness": max(0.0, min(float(focus.get("happiness", 1.0)), 3.0)),
    }
    cfg["prompt_template_version"] = str(cfg.get("prompt_template_version", "v3-evidence-foresight"))
    cfg.pop("_raw_overrides", None)
    return cfg


def _tokenize_for_similarity(text: str) -> set[str]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    return {token for token in cleaned.split() if len(token) > 2}


def compute_novelty_score(summary: str, recent_summaries: list[str]) -> float:
    base_tokens = _tokenize_for_similarity(summary)
    if not base_tokens:
        return 0.0
    if not recent_summaries:
        return 1.0
    max_similarity = 0.0
    for recent in recent_summaries:
        other_tokens = _tokenize_for_similarity(recent)
        if not other_tokens:
            continue
        union = base_tokens | other_tokens
        if not union:
            continue
        similarity = len(base_tokens & other_tokens) / len(union)
        max_similarity = max(max_similarity, similarity)
    return round(max(0.0, min(1.0, 1.0 - max_similarity)), 3)


def infer_maturity_tier(
    *,
    evidence_count: int,
    recurring_entities: int,
    contradiction_count: int,
    confirmed_predictions: int,
) -> DreamMaturityTier:
    score = evidence_count + (2 * recurring_entities) + (4 * confirmed_predictions) - contradiction_count
    if score >= 16:
        return "mature"
    if score >= 7:
        return "emerging"
    return "sparse"


def score_dream_quality(text: str, top_k: int) -> float:
    stripped = (text or "").strip()
    if not stripped:
        return 0.0
    words = stripped.split()
    length_score = min(len(words) / 160.0, 1.0)
    structure_hits = 0
    lowered = stripped.lower()
    for hint in (
        "prediction",
        "because",
        "validation",
        "risk",
        "opportunity",
        "growth",
        "next",
        "confidence",
    ):
        if hint in lowered:
            structure_hits += 1
    structure_score = min(structure_hits / 5.0, 1.0)
    density_score = 1.0 if len(words) <= 360 else max(0.2, 360 / max(len(words), 1))
    recall_anchor_score = 1.0 if top_k >= 3 else 0.7
    return round(
        (0.3 * length_score) + (0.3 * structure_score) + (0.25 * density_score) + (0.15 * recall_anchor_score), 3
    )


def build_dream_html(
    *,
    bank_id: str,
    run_type: str,
    generated_text: str,
    quality_score: float,
    created_at: datetime | None = None,
    max_bytes: int = MAX_HTML_BYTES,
) -> str:
    ts = (created_at or datetime.now(UTC)).isoformat()
    safe_body = html.escape(generated_text.strip() or "Insufficient signal for a meaningful dream output.")
    payload = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Atulya Dream</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; margin: 16px; line-height: 1.45; }}
    .meta {{ opacity: .75; font-size: 12px; margin-bottom: 12px; }}
    .card {{ border: 1px solid rgba(127,127,127,.35); border-radius: 10px; padding: 12px; }}
    pre {{ white-space: pre-wrap; word-break: break-word; margin: 0; font: inherit; }}
  </style>
</head>
<body>
  <div class="meta">bank={html.escape(bank_id)} | run={html.escape(run_type)} | quality={quality_score:.3f} | at={ts}</div>
  <div class="card"><pre>{safe_body}</pre></div>
</body>
</html>"""
    encoded = payload.encode("utf-8")
    if len(encoded) <= max_bytes:
        return payload
    clipped = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return clipped + "\n<!-- clipped for size -->"


def render_dream_narrative_text(
    *,
    summary: str,
    maturity_tier: DreamMaturityTier,
    hypotheses: list[str],
    predictions: list[DreamPrediction],
    growth_hypotheses: list[DreamGrowthHypothesis],
    risks: list[str],
    opportunities: list[str],
    recommended_validations: list[str],
) -> str:
    lines = [f"Dream summary ({maturity_tier} bank): {summary.strip()}"]
    if hypotheses:
        lines.append("\nHypotheses:")
        lines.extend(f"- {item}" for item in hypotheses[:3])
    if predictions:
        lines.append("\nPredictions:")
        for item in predictions[:3]:
            criteria = "; ".join(item.success_criteria[:2])
            lines.append(
                f"- [{item.horizon}] {item.title}: {item.description} "
                f"(confidence {item.confidence:.2f}; validate with {criteria or 'new evidence'})"
            )
    if growth_hypotheses:
        lines.append("\nGrowth / consciousness:")
        lines.extend(f"- {item.title}: {item.description}" for item in growth_hypotheses[:2])
    if risks:
        lines.append("\nRisks:")
        lines.extend(f"- {item}" for item in risks[:2])
    if opportunities:
        lines.append("\nOpportunities:")
        lines.extend(f"- {item}" for item in opportunities[:2])
    if recommended_validations:
        lines.append("\nRecommended validations:")
        lines.extend(f"- {item}" for item in recommended_validations[:3])
    return "\n".join(lines).strip()


def render_dream_narrative_html(
    *,
    bank_id: str,
    run_type: str,
    summary: str,
    maturity_tier: DreamMaturityTier,
    hypotheses: list[str],
    predictions: list[DreamPrediction],
    growth_hypotheses: list[DreamGrowthHypothesis],
    risks: list[str],
    opportunities: list[str],
    recommended_validations: list[str],
    quality_score: float,
    created_at: datetime | None = None,
    max_bytes: int = MAX_HTML_BYTES,
) -> str:
    narrative_text = render_dream_narrative_text(
        summary=summary,
        maturity_tier=maturity_tier,
        hypotheses=hypotheses,
        predictions=predictions,
        growth_hypotheses=growth_hypotheses,
        risks=risks,
        opportunities=opportunities,
        recommended_validations=recommended_validations,
    )
    return build_dream_html(
        bank_id=bank_id,
        run_type=run_type,
        generated_text=narrative_text,
        quality_score=quality_score,
        created_at=created_at,
        max_bytes=max_bytes,
    )


def summarize_confidence(
    *,
    evidence_count: int,
    contradiction_count: int,
    novelty_score: float,
    calibration_score: float,
    predictions: list[DreamPrediction],
    summary: str,
) -> DreamConfidenceModel:
    evidence_richness = max(0.0, min(1.0, math.log1p(max(evidence_count, 0)) / math.log(12)))
    contradiction_pressure = max(0.0, min(1.0, contradiction_count / max(evidence_count, 1)))
    specificity_hits = sum(1 for item in predictions if item.success_criteria and item.description)
    prediction_specificity = max(0.0, min(1.0, specificity_hits / max(len(predictions), 1))) if predictions else 0.2
    overall = max(
        0.0,
        min(
            1.0,
            (0.32 * evidence_richness)
            + (0.24 * calibration_score)
            + (0.18 * novelty_score)
            + (0.2 * prediction_specificity)
            - (0.18 * contradiction_pressure),
        ),
    )
    claims = [DreamClaimConfidence(claim=summary[:180], confidence=round(overall, 3), basis="bank evidence + history")]
    for prediction in predictions[:4]:
        claims.append(
            DreamClaimConfidence(
                claim=prediction.title,
                confidence=round(prediction.confidence, 3),
                basis="prediction criteria + recalled evidence",
            )
        )
    return DreamConfidenceModel(
        overall=round(overall, 3),
        calibration_score=round(calibration_score, 3),
        evidence_richness=round(evidence_richness, 3),
        contradiction_pressure=round(contradiction_pressure, 3),
        prediction_specificity=round(prediction_specificity, 3),
        novelty_score=round(novelty_score, 3),
        per_claim=claims,
    )


def to_jsonable(model: BaseModel | dict[str, Any] | list[Any] | None) -> Any:
    if model is None:
        return None
    if isinstance(model, BaseModel):
        return model.model_dump(mode="json")
    if isinstance(model, list):
        return [to_jsonable(item) for item in model]
    if isinstance(model, dict):
        return {key: to_jsonable(value) for key, value in model.items()}
    return model
