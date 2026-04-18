"""Code metrics via the `lizard` library.

lizard is a multi-language complexity analyzer that gives us a real
"this function is dense / risky" signal. Pure in-process Python; no
subprocess. Cached per content_hash to amortize across snapshots.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class FunctionMetrics:
    """Per-function metrics extracted by lizard."""

    name: str
    start_line: int
    end_line: int
    nloc: int
    cyclomatic_complexity: int
    parameter_count: int


_CACHE: dict[str, list[FunctionMetrics]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 5000


def analyze_file(*, path: str, text: str, content_hash: str) -> list[FunctionMetrics]:
    """Run lizard on a source file and return per-function metrics.

    Cache key is `content_hash` so we re-use results across snapshots.
    Returns an empty list on any failure (degrades gracefully)."""

    with _CACHE_LOCK:
        cached = _CACHE.get(content_hash)
        if cached is not None:
            return cached

    try:
        import lizard  # type: ignore[import-untyped]
    except Exception:
        return []

    try:
        analyzer = lizard.analyze_file.analyze_source_code(path, text)
    except Exception:
        return []

    out: list[FunctionMetrics] = []
    for func in getattr(analyzer, "function_list", []) or []:
        try:
            out.append(
                FunctionMetrics(
                    name=str(func.name),
                    start_line=int(func.start_line or 0),
                    end_line=int(func.end_line or 0),
                    nloc=int(func.nloc or 0),
                    cyclomatic_complexity=int(func.cyclomatic_complexity or 0),
                    parameter_count=int(func.parameter_count or 0),
                )
            )
        except Exception:
            continue

    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        _CACHE[content_hash] = out

    return out


def metrics_for_chunk(
    *,
    chunk_start_line: int,
    chunk_end_line: int,
    file_metrics: list[FunctionMetrics],
) -> FunctionMetrics | None:
    """Pick the function metric that best matches a chunk's line range.

    A chunk often wraps exactly one function, but it may overlap many
    (region chunks). We pick the one with maximum line-overlap; ties
    are broken by highest cyclomatic complexity so that "interesting"
    functions surface."""

    if not file_metrics:
        return None

    best: FunctionMetrics | None = None
    best_overlap = 0
    for fm in file_metrics:
        overlap = max(0, min(chunk_end_line, fm.end_line) - max(chunk_start_line, fm.start_line) + 1)
        if overlap <= 0:
            continue
        if overlap > best_overlap or (
            overlap == best_overlap and best is not None and fm.cyclomatic_complexity > best.cyclomatic_complexity
        ):
            best = fm
            best_overlap = overlap
    return best


def complexity_density(metrics: FunctionMetrics | None) -> float:
    """Normalize cyclomatic complexity to 0..1 for use in the
    significance score. log-scaled so that CC=10 -> ~0.5, CC=30 -> ~0.85."""

    if metrics is None or metrics.cyclomatic_complexity <= 1:
        return 0.0
    import math

    return min(1.0, math.log(metrics.cyclomatic_complexity, 2) / 6.0)
