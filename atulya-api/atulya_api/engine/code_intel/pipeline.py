"""Single entry point that runs the whole code-intel pipeline.

`run_pipeline()` is what `memory_engine._build_codebase_chunk_graph`
calls per snapshot. It:

  1) Classifies each file into a FileRole.
  2) Builds the symbol-level repo-map (PageRank + fan-in/fan-out).
  3) Runs lizard for complexity per file (cached by content_hash).
  4) Runs the safety-tag scanner per chunk.
  5) Picks one cluster representative per cluster.
  6) Scores every chunk via significance.compute_significance.
  7) Builds Symbol Cards / Module Briefs / Repo Map artifacts.

The result is consumed by the memory_engine snapshot writer to
persist new chunk columns + auto-route + artifact rows.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..codebase_index import IndexedEdge, IndexedFile
from .artifacts import ModuleBrief, RepoMap, SymbolCard, build_artifacts
from .file_role import FileRole, classify_file_role
from .metrics import FunctionMetrics, analyze_file, metrics_for_chunk
from .repo_map import RepoMapMetrics, build_repo_map_metrics, normalized_file_pagerank, normalized_pagerank
from .safety import scan_text_for_safety_tags
from .significance import (
    SignificanceScore,
    SignificanceThresholds,
    compute_significance,
)


@dataclass(slots=True)
class CodeIntelResult:
    chunk_scores: dict[str, SignificanceScore] = field(default_factory=dict)
    chunk_complexity: dict[str, dict[str, Any]] = field(default_factory=dict)
    chunk_safety_tags: dict[str, list[str]] = field(default_factory=dict)
    chunk_pagerank: dict[str, float] = field(default_factory=dict)
    chunk_fanin: dict[str, int] = field(default_factory=dict)
    chunk_file_role: dict[str, str] = field(default_factory=dict)
    file_role: dict[str, str] = field(default_factory=dict)
    repo_map_metrics: RepoMapMetrics | None = None
    symbol_cards: list[SymbolCard] = field(default_factory=list)
    module_briefs: list[ModuleBrief] = field(default_factory=list)
    repo_map: RepoMap | None = None
    summary: dict[str, Any] = field(default_factory=dict)


def run_pipeline(
    *,
    indexed_files: list[IndexedFile],
    file_edges: list[IndexedEdge],
    chunk_rows: list[dict[str, Any]],
    file_text_provider: Callable[[str], str | None] | None = None,
    enable_safety_scan: bool = True,
    thresholds: SignificanceThresholds | None = None,
) -> CodeIntelResult:
    """Run the full pipeline for one snapshot."""

    thresholds = thresholds or SignificanceThresholds()

    file_roles: dict[str, FileRole] = {}
    for indexed in indexed_files:
        file_roles[indexed.path] = classify_file_role(indexed.path)

    repo_map_metrics = build_repo_map_metrics(
        indexed_files=indexed_files,
        file_edges=file_edges,
        file_text_provider=file_text_provider,
    )

    file_metrics_cache: dict[str, list[FunctionMetrics]] = {}
    if file_text_provider is not None:
        for indexed in indexed_files:
            if not indexed.should_parse_symbols and indexed.status != "indexed":
                continue
            text = file_text_provider(indexed.path)
            if not text:
                continue
            try:
                file_metrics_cache[indexed.path] = analyze_file(
                    path=indexed.path,
                    text=text,
                    content_hash=indexed.content_hash,
                )
            except Exception:
                file_metrics_cache[indexed.path] = []

    cluster_representatives = _pick_cluster_representatives(chunk_rows)

    norm_symbol_pr = normalized_pagerank(repo_map_metrics)
    norm_file_pr = normalized_file_pagerank(repo_map_metrics)
    file_change_kinds = {indexed.path: indexed.change_kind for indexed in indexed_files}

    chunk_scores: dict[str, SignificanceScore] = {}
    chunk_complexity: dict[str, dict[str, Any]] = {}
    chunk_safety_tags: dict[str, list[str]] = {}
    chunk_pagerank: dict[str, float] = {}
    chunk_fanin: dict[str, int] = {}
    chunk_file_role: dict[str, str] = {}

    for chunk in chunk_rows:
        chunk_key = chunk["chunk_key"]
        path = chunk["path"]
        role = file_roles.get(path, classify_file_role(path))
        chunk_file_role[chunk_key] = role.value

        symbol_fq = chunk.get("parent_fq_name")
        symbol_pagerank = norm_symbol_pr.get(symbol_fq, 0.0) if symbol_fq else 0.0
        file_pagerank = norm_file_pr.get(path, 0.0)
        chunk_pagerank[chunk_key] = symbol_pagerank if symbol_pagerank > 0 else file_pagerank
        fanin_count = repo_map_metrics.fanin.get(symbol_fq, 0) if symbol_fq else 0
        chunk_fanin[chunk_key] = fanin_count

        complexity_metrics = None
        if file_metrics_cache.get(path):
            complexity_metrics = metrics_for_chunk(
                chunk_start_line=chunk["start_line"],
                chunk_end_line=chunk["end_line"],
                file_metrics=file_metrics_cache[path],
            )
        if complexity_metrics is not None:
            chunk_complexity[chunk_key] = {
                "name": complexity_metrics.name,
                "cyclomatic_complexity": complexity_metrics.cyclomatic_complexity,
                "nloc": complexity_metrics.nloc,
                "parameter_count": complexity_metrics.parameter_count,
            }

        safety_tags: list[str] = []
        if enable_safety_scan:
            safety_tags = scan_text_for_safety_tags(chunk.get("content_text") or "")
        if safety_tags:
            chunk_safety_tags[chunk_key] = safety_tags

        chunk_lines = max(0, int(chunk["end_line"]) - int(chunk["start_line"]) + 1)
        cluster_id = chunk.get("cluster_id")
        is_representative = (
            cluster_representatives.get(cluster_id, chunk_key) == chunk_key if isinstance(cluster_id, str) else True
        )

        score = compute_significance(
            chunk_kind=chunk["kind"],
            chunk_text=chunk.get("content_text") or "",
            chunk_label=chunk["label"],
            parent_fq_name=symbol_fq,
            file_role=role,
            pagerank_for_symbol=symbol_pagerank,
            pagerank_for_file=file_pagerank,
            fanin_count=fanin_count,
            complexity=complexity_metrics,
            safety_tags=safety_tags,
            is_cluster_representative=is_representative,
            change_kind=file_change_kinds.get(path),
            parse_confidence=float(chunk.get("parse_confidence") or 0.0),
            chunk_lines=chunk_lines,
            language=chunk.get("language"),
            thresholds=thresholds,
        )
        chunk_scores[chunk_key] = score

    symbol_cards, module_briefs, repo_map = build_artifacts(
        indexed_files=indexed_files,
        file_edges=file_edges,
        chunk_rows=chunk_rows,
        chunk_scores=chunk_scores,
        repo_map_metrics=repo_map_metrics,
        chunk_complexity=chunk_complexity,
        chunk_safety_tags=chunk_safety_tags,
        file_text_provider=file_text_provider,
    )

    summary = _summarize(chunk_scores, file_roles)

    return CodeIntelResult(
        chunk_scores=chunk_scores,
        chunk_complexity=chunk_complexity,
        chunk_safety_tags=chunk_safety_tags,
        chunk_pagerank={key: round(value, 4) for key, value in chunk_pagerank.items()},
        chunk_fanin=chunk_fanin,
        chunk_file_role=chunk_file_role,
        file_role={path: role.value for path, role in file_roles.items()},
        repo_map_metrics=repo_map_metrics,
        symbol_cards=symbol_cards,
        module_briefs=module_briefs,
        repo_map=repo_map,
        summary=summary,
    )


def _pick_cluster_representatives(chunk_rows: list[dict[str, Any]]) -> dict[str, str]:
    """Pick one representative chunk per cluster: the chunk whose label
    sorts first within its cluster (stable, deterministic). Returns
    {cluster_id: chunk_key}."""

    by_cluster: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunk_rows:
        cluster_id = chunk.get("cluster_id")
        if not cluster_id:
            continue
        by_cluster.setdefault(cluster_id, []).append(chunk)

    out: dict[str, str] = {}
    for cluster_id, members in by_cluster.items():
        sorted_members = sorted(
            members,
            key=lambda c: (
                0 if c["kind"] in {"class", "interface", "function", "method"} else 1,
                c.get("path") or "",
                int(c.get("start_line") or 0),
            ),
        )
        out[cluster_id] = sorted_members[0]["chunk_key"]
    return out


def _summarize(
    chunk_scores: dict[str, SignificanceScore],
    file_roles: dict[str, FileRole],
) -> dict[str, Any]:
    counts: dict[str, int] = {"dismiss": 0, "memory": 0, "review": 0}
    score_values: list[float] = []
    role_counts: dict[str, int] = {}
    for score in chunk_scores.values():
        counts[score.route_hint] = counts.get(score.route_hint, 0) + 1
        score_values.append(score.score)
    for role in file_roles.values():
        role_counts[role.value] = role_counts.get(role.value, 0) + 1
    if score_values:
        avg = sum(score_values) / len(score_values)
        max_score = max(score_values)
    else:
        avg = 0.0
        max_score = 0.0
    return {
        "route_counts": counts,
        "score_avg": round(avg, 4),
        "score_max": round(max_score, 4),
        "file_role_counts": role_counts,
        "scored_chunks": len(score_values),
    }
