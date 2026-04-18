"""Significance scorer + auto-route policy.

Pure function over a chunk's structured signals -> a score in [0..1]
with explainable component breakdown and a deterministic route hint
(`dismiss` | `memory` | `review`).

The explanation is a first-class output: every routed chunk knows
*why* it was routed, which is what makes the auto-triage trustworthy
to coders skimming the gray zone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .file_role import FileRole, is_dismiss_role, is_high_value_role, role_weight
from .metrics import FunctionMetrics, complexity_density
from .safety import safety_priority

RouteHint = Literal["dismiss", "memory", "review"]

_SYMBOL_KINDS = {"function", "method", "class", "interface", "type"}

_PYTHON_PUBLIC_RE = re.compile(r"^(?:[A-Z]|[a-z])")
_TS_EXPORT_RE = re.compile(r"\bexport\b")


@dataclass(slots=True)
class SignificanceComponents:
    """Each component is a normalized 0..1 contribution -- this is the
    explanation surface coders see in the 'Why?' popover."""

    role_weight: float = 0.0
    symbol_kind_weight: float = 0.0
    exportness: float = 0.0
    pagerank_centrality: float = 0.0
    fanin: float = 0.0
    complexity_density: float = 0.0
    safety_priority: float = 0.0
    cluster_representativeness: float = 0.0
    change_boost: float = 0.0
    parse_confidence: float = 0.0


@dataclass(slots=True)
class SignificanceScore:
    score: float
    components: SignificanceComponents
    route_hint: RouteHint
    reason: str
    safety_tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SignificanceThresholds:
    high: float = 0.62
    centrality: float = 0.35
    safety: float = 0.25


_WEIGHTS = {
    "role_weight": 0.18,
    "symbol_kind_weight": 0.12,
    "exportness": 0.10,
    "pagerank_centrality": 0.20,
    "fanin": 0.08,
    "complexity_density": 0.06,
    "safety_priority": 0.10,
    "cluster_representativeness": 0.06,
    "change_boost": 0.05,
    "parse_confidence": 0.05,
}


def compute_significance(
    *,
    chunk_kind: str,
    chunk_text: str,
    chunk_label: str,
    parent_fq_name: str | None,
    file_role: FileRole,
    pagerank_for_symbol: float,
    pagerank_for_file: float,
    fanin_count: int,
    complexity: FunctionMetrics | None,
    safety_tags: list[str],
    is_cluster_representative: bool,
    change_kind: str | None,
    parse_confidence: float,
    chunk_lines: int,
    language: str | None,
    thresholds: SignificanceThresholds | None = None,
) -> SignificanceScore:
    """Score a single chunk and decide its route hint."""

    thresholds = thresholds or SignificanceThresholds()

    components = SignificanceComponents(
        role_weight=role_weight(file_role),
        symbol_kind_weight=_symbol_kind_weight(chunk_kind, chunk_lines),
        exportness=_exportness(chunk_label, chunk_text, language),
        pagerank_centrality=max(pagerank_for_symbol, pagerank_for_file * 0.6),
        fanin=_fanin_score(fanin_count),
        complexity_density=complexity_density(complexity),
        safety_priority=safety_priority(safety_tags),
        cluster_representativeness=1.0 if is_cluster_representative else 0.4,
        change_boost=_change_boost(change_kind),
        parse_confidence=max(0.0, min(1.0, parse_confidence)),
    )

    weighted = (
        _WEIGHTS["role_weight"] * components.role_weight
        + _WEIGHTS["symbol_kind_weight"] * components.symbol_kind_weight
        + _WEIGHTS["exportness"] * components.exportness
        + _WEIGHTS["pagerank_centrality"] * components.pagerank_centrality
        + _WEIGHTS["fanin"] * components.fanin
        + _WEIGHTS["complexity_density"] * components.complexity_density
        + _WEIGHTS["safety_priority"] * components.safety_priority
        + _WEIGHTS["cluster_representativeness"] * components.cluster_representativeness
        + _WEIGHTS["change_boost"] * components.change_boost
        + _WEIGHTS["parse_confidence"] * components.parse_confidence
    )
    score = max(0.0, min(1.0, weighted))

    route_hint, reason = _decide_route(
        chunk_kind=chunk_kind,
        chunk_lines=chunk_lines,
        chunk_label=chunk_label,
        chunk_text=chunk_text,
        file_role=file_role,
        components=components,
        score=score,
        safety_tags=safety_tags,
        thresholds=thresholds,
        language=language,
    )

    return SignificanceScore(
        score=round(score, 4),
        components=components,
        route_hint=route_hint,
        reason=reason,
        safety_tags=safety_tags,
    )


def _decide_route(
    *,
    chunk_kind: str,
    chunk_lines: int,
    chunk_label: str,
    chunk_text: str,
    file_role: FileRole,
    components: SignificanceComponents,
    score: float,
    safety_tags: list[str],
    thresholds: SignificanceThresholds,
    language: str | None,
) -> tuple[RouteHint, str]:
    if is_dismiss_role(file_role):
        return "dismiss", f"auto-dismiss: {file_role.value}"

    if file_role == FileRole.TEST:
        if components.exportness < 0.6:
            return "dismiss", "auto-dismiss: test body"

    if file_role == FileRole.FIXTURE:
        return "dismiss", "auto-dismiss: fixture"

    if chunk_kind == "region" and chunk_lines < 3:
        return "dismiss", "auto-dismiss: trivial region"

    if safety_tags and components.pagerank_centrality >= thresholds.safety:
        return "memory", f"auto-memory: safety-critical ({', '.join(safety_tags[:2])}) + central"

    if is_high_value_role(file_role) and chunk_kind in _SYMBOL_KINDS and score >= thresholds.high:
        return "memory", f"auto-memory: high-value role ({file_role.value}) + symbol"

    if (
        score >= thresholds.high
        and components.exportness >= 0.6
        and components.pagerank_centrality >= thresholds.centrality
    ):
        return "memory", "auto-memory: exported + central"

    return "review", "gray zone: human decides"


def _symbol_kind_weight(chunk_kind: str, chunk_lines: int) -> float:
    if chunk_kind in {"class", "interface"}:
        return 0.95
    if chunk_kind in {"function", "method"}:
        return 0.9
    if chunk_kind == "type":
        return 0.7
    if chunk_kind == "variable":
        return 0.45
    if chunk_kind == "region":
        if chunk_lines < 3:
            return 0.05
        if chunk_lines < 8:
            return 0.2
        if chunk_lines < 30:
            return 0.4
        return 0.5
    return 0.5


def _exportness(label: str, text: str, language: str | None) -> float:
    """Heuristic exportness from the symbol name + first line of text.

    - Python: leading underscore -> 0.0; uppercase first char or lowercase
      function -> 0.7; presence of `__all__` mention -> 1.0.
    - TS/JS: presence of `export ` token -> 1.0; default export -> 1.0.
    - Default: 0.5 (unknown).
    """

    if not label:
        return 0.0
    short_name = label.rsplit(".", 1)[-1]
    if language == "python":
        if short_name.startswith("_") and not short_name.startswith("__"):
            return 0.0
        if short_name.startswith("__") and short_name.endswith("__"):
            return 0.7
        if "__all__" in text:
            return 1.0
        if _PYTHON_PUBLIC_RE.match(short_name):
            return 0.75
        return 0.5
    if language in {"typescript", "tsx", "javascript", "jsx"}:
        if _TS_EXPORT_RE.search(text):
            return 1.0
        if short_name and short_name[0].isupper():
            return 0.7
        return 0.5
    if not short_name:
        return 0.0
    if short_name.startswith("_"):
        return 0.2
    return 0.5


def _fanin_score(fanin_count: int) -> float:
    """Log-scale fanin to 0..1; fanin=10 -> ~0.7, fanin=50 -> ~1.0."""

    if fanin_count <= 0:
        return 0.0
    import math

    return min(1.0, math.log1p(fanin_count) / math.log(50))


def _change_boost(change_kind: str | None) -> float:
    if change_kind == "added":
        return 1.0
    if change_kind == "modified":
        return 0.8
    return 0.0
