"""
Deterministic influence analytics for Brain Intelligence.

This module intentionally avoids heavyweight online training in request paths.
It uses proven statistical methods (bounded scoring, EWMA trend, robust z-score)
for stable production behavior across model/provider setups.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import exp
from statistics import mean, median, pstdev
from typing import Any


@dataclass(slots=True)
class InfluenceFeatures:
    recency_days: float
    access_freq: float
    graph_signal: float
    rerank_signal: float
    dream_signal: float


def _bounded(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(v, hi))


def recency_decay_score(recency_days: float, half_life_days: float = 7.0) -> float:
    """Exponential recency decay score in [0,1]."""
    if recency_days <= 0:
        return 1.0
    return _bounded(exp(-recency_days / max(half_life_days, 0.1)))


def influence_score(
    features: InfluenceFeatures,
    weights: dict[str, float] | None = None,
) -> tuple[float, dict[str, float]]:
    """
    Compute bounded weighted influence score with factor decomposition.
    """
    w = {
        "recency": 0.28,
        "freq": 0.26,
        "graph": 0.18,
        "rerank": 0.14,
        "dream": 0.14,
    }
    if weights:
        w.update({k: float(v) for k, v in weights.items() if k in w})
    norm = sum(max(v, 0.0) for v in w.values()) or 1.0
    for k in w:
        w[k] = max(w[k], 0.0) / norm

    recency = recency_decay_score(features.recency_days)
    freq = _bounded(features.access_freq)
    graph = _bounded(features.graph_signal)
    rerank = _bounded(features.rerank_signal)
    dream = _bounded(features.dream_signal)
    parts = {
        "recency": w["recency"] * recency,
        "freq": w["freq"] * freq,
        "graph": w["graph"] * graph,
        "rerank": w["rerank"] * rerank,
        "dream": w["dream"] * dream,
    }
    return round(sum(parts.values()), 6), {k: round(v, 6) for k, v in parts.items()}


def ewma(values: list[float], alpha: float = 0.35) -> list[float]:
    if not values:
        return []
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def robust_zscore(value: float, series: list[float]) -> float:
    if not series:
        return 0.0
    med = median(series)
    mad = median([abs(x - med) for x in series]) or 1e-9
    return 0.6745 * (value - med) / mad


def confidence_bands(series: list[float], sigma: float = 1.645) -> list[dict[str, float]]:
    """
    Return point-wise confidence bands around EWMA trend.
    Uses population std on available history per index.
    """
    bands: list[dict[str, float]] = []
    for i, v in enumerate(series):
        window = series[: i + 1]
        mu = mean(window) if window else 0.0
        std = pstdev(window) if len(window) > 1 else 0.0
        lo = max(0.0, mu - sigma * std)
        hi = min(1.0, mu + sigma * std)
        bands.append({"value": round(v, 6), "lower": round(lo, 6), "upper": round(hi, 6)})
    return bands


def iqr_anomaly_flags(series: list[float]) -> list[bool]:
    """
    Tukey IQR anomaly flags for non-Gaussian robust outlier detection.
    """
    if len(series) < 4:
        return [abs(robust_zscore(v, series)) >= 3.5 for v in series]
    ordered = sorted(series)
    mid = len(ordered) // 2
    lower = ordered[:mid]
    upper = ordered[mid:] if len(ordered) % 2 == 0 else ordered[mid + 1 :]
    q1 = median(lower) if lower else ordered[0]
    q3 = median(upper) if upper else ordered[-1]
    iqr = q3 - q1
    lo = q1 - 1.5 * iqr
    hi = q3 + 1.5 * iqr
    return [(v < lo or v > hi) or abs(robust_zscore(v, series)) >= 3.5 for v in series]


def hour_weekday_heatmap(
    timestamps: list[datetime],
) -> list[dict[str, Any]]:
    """
    Build 7x24 heatmap matrix flattened as rows.
    """
    grid = [[0 for _ in range(24)] for _ in range(7)]
    for ts in timestamps:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        ts_utc = ts.astimezone(UTC)
        grid[ts_utc.weekday()][ts_utc.hour] += 1
    rows: list[dict[str, Any]] = []
    max_v = max((max(r) for r in grid), default=1) or 1
    for day in range(7):
        for hour in range(24):
            count = grid[day][hour]
            rows.append(
                {
                    "weekday": day,
                    "hour_utc": hour,
                    "count": count,
                    "score": round(count / max_v, 6),
                }
            )
    return rows
