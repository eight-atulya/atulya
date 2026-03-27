"""
Dream/Trance helpers for async knowledge synthesis.
"""

from __future__ import annotations

import html
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

DEFAULT_DREAM_CONFIG: dict[str, Any] = {
    "enabled": False,
    "trance_enabled": False,
    "trigger_mode": "hybrid",
    "cron_interval_minutes": 180,
    "cooldown_minutes": 60,
    "top_k": 4,
    "max_input_tokens": 900,
    "max_output_tokens": 300,
    "model_preference": "local-first",
    "worker_prompt": (
        "Use an Assumption -> Audit -> Train -> What-if -> Value chain. "
        "Be plain-language, concise, and causal. Show why the pattern happened, what evidence supports it, "
        "how confidence can be improved next cycle, and the likely impact on time saved, money, and happiness."
    ),
    "write_distilled_summary": False,
    "distillation_mode": "off",  # off | summary | fragments
    "distillation_max_fragments": 3,
    "quality_threshold": 0.65,
    "min_recall_results": 2,
    "max_artifact_bytes": 24_000,
    "language_tone": "plain-layman",
    "enforce_layman": True,
    "value_focus": {"money": 1.0, "time": 1.0, "happiness": 1.0},
    "prompt_template_version": "v2-causal-chain",
    "preset": "balanced_org",
}

MAX_HTML_BYTES = 24_000

PRESET_OVERRIDES: dict[str, dict[str, Any]] = {
    # Best default for most organizations: stable signal quality and practical outputs.
    "balanced_org": {
        "top_k": 4,
        "min_recall_results": 2,
        "max_input_tokens": 900,
        "max_output_tokens": 320,
        "cooldown_minutes": 60,
        "quality_threshold": 0.65,
        "distillation_mode": "summary",
        "distillation_max_fragments": 3,
        "value_focus": {"money": 1.0, "time": 1.0, "happiness": 1.0},
    },
    # Designed for small/local models and constrained hardware.
    "lean_local": {
        "top_k": 3,
        "min_recall_results": 2,
        "max_input_tokens": 640,
        "max_output_tokens": 220,
        "cooldown_minutes": 90,
        "quality_threshold": 0.7,
        "distillation_mode": "fragments",
        "distillation_max_fragments": 2,
        "enforce_layman": True,
        "value_focus": {"money": 0.8, "time": 1.4, "happiness": 0.8},
    },
    # High-confidence mode for compliance/risk-sensitive domains.
    "risk_guard": {
        "top_k": 5,
        "min_recall_results": 3,
        "max_input_tokens": 1100,
        "max_output_tokens": 300,
        "cooldown_minutes": 120,
        "quality_threshold": 0.78,
        "distillation_mode": "off",
        "enforce_layman": True,
        "value_focus": {"money": 0.9, "time": 0.9, "happiness": 1.2},
    },
    # Executive mode: concise strategy/value-centric summaries.
    "exec_strategy": {
        "top_k": 4,
        "min_recall_results": 2,
        "max_input_tokens": 1000,
        "max_output_tokens": 260,
        "cooldown_minutes": 45,
        "quality_threshold": 0.68,
        "distillation_mode": "summary",
        "distillation_max_fragments": 3,
        "language_tone": "executive-plain",
        "value_focus": {"money": 1.5, "time": 1.2, "happiness": 0.7},
    },
}


def _apply_preset(cfg: dict[str, Any]) -> dict[str, Any]:
    preset = str(cfg.get("preset", "balanced_org")).strip().lower()
    if preset not in PRESET_OVERRIDES:
        preset = "balanced_org"
    merged = deepcopy(cfg)
    merged["preset"] = preset
    merged.update(deepcopy(PRESET_OVERRIDES[preset]))
    # Allow explicit user overrides to win if provided in raw config.
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
    cfg["max_output_tokens"] = max(96, min(int(cfg.get("max_output_tokens", 300)), 1200))
    cfg["cooldown_minutes"] = max(5, min(int(cfg.get("cooldown_minutes", 60)), 24 * 60))
    cfg["cron_interval_minutes"] = max(5, min(int(cfg.get("cron_interval_minutes", 180)), 24 * 60))
    cfg["quality_threshold"] = max(0.0, min(float(cfg.get("quality_threshold", 0.65)), 1.0))
    cfg["min_recall_results"] = max(1, min(int(cfg.get("min_recall_results", 2)), 8))
    cfg["distillation_max_fragments"] = max(1, min(int(cfg.get("distillation_max_fragments", 3)), 10))
    cfg["max_artifact_bytes"] = max(4_000, min(int(cfg.get("max_artifact_bytes", MAX_HTML_BYTES)), 120_000))
    cfg["trigger_mode"] = str(cfg.get("trigger_mode", "hybrid")).lower()
    cfg["distillation_mode"] = str(cfg.get("distillation_mode", "off")).lower()
    if cfg["distillation_mode"] not in ("off", "summary", "fragments"):
        cfg["distillation_mode"] = "off"
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
    cfg["prompt_template_version"] = str(cfg.get("prompt_template_version", "v2-causal-chain"))
    cfg.pop("_raw_overrides", None)
    return cfg


def score_dream_quality(text: str, top_k: int) -> float:
    stripped = (text or "").strip()
    if not stripped:
        return 0.0
    words = stripped.split()
    length_score = min(len(words) / 140.0, 1.0)
    structure_hits = 0
    lowered = stripped.lower()
    for hint in ("next", "if", "because", "pattern", "signal", "risk", "opportunity"):
        if hint in lowered:
            structure_hits += 1
    structure_score = min(structure_hits / 4.0, 1.0)
    density_score = 1.0 if len(words) <= 260 else max(0.2, 260 / max(len(words), 1))
    recall_anchor_score = 1.0 if top_k >= 3 else 0.7
    return round(
        (0.35 * length_score) + (0.3 * structure_score) + (0.25 * density_score) + (0.1 * recall_anchor_score), 3
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
