"""Aider-style repository map.

Builds a symbol-level definition+reference graph from the existing
ASD parse output (symbols + import edges) plus our heuristic call
edges (references.py) and runs NetworkX PageRank to score every
symbol's importance in the codebase.

This is the same recipe used by aider's RepoMap (MIT) which has been
proven across millions of LLM coding sessions: tree-sitter -> symbol
graph -> PageRank -> ranked tags map. We re-implement it on top of
our own symbol/edge dataclasses to stay decoupled from aider's
internals.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ..codebase_index import IndexedEdge, IndexedFile, IndexedSymbol
from .references import ReferenceEdge, collect_reference_edges


@dataclass(slots=True)
class SymbolNode:
    """A node in the repo-map graph: one symbol = one node.

    The "module" pseudo-symbol per file (`fq_name = '<module>:path'`)
    is used as a fallback caller for top-level call sites.
    """

    fq_name: str
    name: str
    kind: str
    path: str
    language: str | None
    start_line: int
    end_line: int
    container: str | None = None


@dataclass(slots=True)
class RepoMapMetrics:
    """Aggregated per-symbol metrics produced by the repo-map pass."""

    pagerank: dict[str, float] = field(default_factory=dict)
    fanin: dict[str, int] = field(default_factory=dict)
    fanout: dict[str, int] = field(default_factory=dict)
    top_callers: dict[str, list[str]] = field(default_factory=dict)
    top_callees: dict[str, list[str]] = field(default_factory=dict)
    file_pagerank: dict[str, float] = field(default_factory=dict)
    symbols_by_path: dict[str, list[SymbolNode]] = field(default_factory=dict)
    nodes_by_fq: dict[str, SymbolNode] = field(default_factory=dict)


def build_repo_map_metrics(
    *,
    indexed_files: list[IndexedFile],
    file_edges: list[IndexedEdge] | None = None,
    file_text_provider: Callable[[str], str | None] | None = None,
) -> RepoMapMetrics:
    """Build the symbol graph and run PageRank.

    Inputs:
      - `indexed_files`: same list the chunk graph builder gets.
      - `file_edges`: optional cross-file import edges (already in the
        ASD pipeline) -- we use them for module-level resolution.
      - `file_text_provider`: callable `path -> str` to fetch source
        text for the call-edge extractor; if None, we skip call edges
        (still produces meaningful metrics from defs + imports).

    Returns RepoMapMetrics with PageRank, fan-in, fan-out, and the
    per-symbol top callers/callees lists used to build Symbol Cards.
    """

    file_edges = file_edges or []

    nodes_by_fq: dict[str, SymbolNode] = {}
    symbols_by_path: dict[str, list[SymbolNode]] = {}
    name_to_fq: dict[str, list[str]] = {}

    for indexed in indexed_files:
        for symbol in indexed.symbols:
            node = SymbolNode(
                fq_name=symbol.fq_name,
                name=symbol.name,
                kind=symbol.kind,
                path=symbol.path,
                language=symbol.language,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                container=symbol.container,
            )
            nodes_by_fq[symbol.fq_name] = node
            symbols_by_path.setdefault(symbol.path, []).append(node)
            name_to_fq.setdefault(symbol.name, []).append(symbol.fq_name)

    file_imports: dict[str, set[str]] = {}
    for edge in file_edges:
        if edge.edge_type != "imports" or not edge.to_path:
            continue
        file_imports.setdefault(edge.from_path, set()).add(edge.to_path)

    reference_edges: list[ReferenceEdge] = []
    if file_text_provider is not None:
        for indexed in indexed_files:
            text = file_text_provider(indexed.path)
            if not text or not indexed.symbols:
                continue
            try:
                refs = collect_reference_edges(path=indexed.path, text=text, symbols=indexed.symbols)
            except Exception:
                refs = []
            reference_edges.extend(refs)

    edges: list[tuple[str, str, float]] = []

    for ref in reference_edges:
        callee_fq = _resolve_callee_fq(
            callee_name=ref.to_name,
            from_path=ref.from_path,
            symbols_by_path=symbols_by_path,
            name_to_fq=name_to_fq,
            file_imports=file_imports,
        )
        if callee_fq is None or callee_fq == ref.from_symbol_fq:
            continue
        if callee_fq not in nodes_by_fq:
            continue
        caller_fq = ref.from_symbol_fq
        if caller_fq not in nodes_by_fq:
            caller_fq = f"<module>:{ref.from_path}"
        edges.append((caller_fq, callee_fq, 1.0))

    for from_path, neighbors in file_imports.items():
        for neighbor in neighbors:
            for src_node in symbols_by_path.get(from_path, [])[:8]:
                for tgt_node in symbols_by_path.get(neighbor, [])[:8]:
                    if src_node.fq_name == tgt_node.fq_name:
                        continue
                    edges.append((src_node.fq_name, tgt_node.fq_name, 0.25))

    pagerank, fanin, fanout, top_callers, top_callees = _compute_graph_metrics(nodes_by_fq.keys(), edges)

    file_pagerank: dict[str, float] = {}
    for fq, score in pagerank.items():
        node = nodes_by_fq.get(fq)
        if node is None:
            continue
        file_pagerank[node.path] = file_pagerank.get(node.path, 0.0) + score

    return RepoMapMetrics(
        pagerank=pagerank,
        fanin=fanin,
        fanout=fanout,
        top_callers=top_callers,
        top_callees=top_callees,
        file_pagerank=file_pagerank,
        symbols_by_path=symbols_by_path,
        nodes_by_fq=nodes_by_fq,
    )


def _resolve_callee_fq(
    *,
    callee_name: str,
    from_path: str,
    symbols_by_path: dict[str, list[SymbolNode]],
    name_to_fq: dict[str, list[str]],
    file_imports: dict[str, set[str]],
) -> str | None:
    """Heuristic name-to-fq resolver, similar to aider's repo-map.

    Resolution preference:
      1) Symbol with this name in the same file.
      2) Symbol with this name in an imported file.
      3) Globally-unique symbol with this name.
    Returns None if the name has no plausible target."""

    same_file = [s for s in symbols_by_path.get(from_path, []) if s.name == callee_name]
    if same_file:
        return same_file[0].fq_name

    imported = file_imports.get(from_path, set())
    for path in imported:
        for symbol in symbols_by_path.get(path, []):
            if symbol.name == callee_name:
                return symbol.fq_name

    candidates = name_to_fq.get(callee_name, [])
    if len(candidates) == 1:
        return candidates[0]

    return None


def _compute_graph_metrics(
    node_ids: Iterable[str],
    edges: list[tuple[str, str, float]],
) -> tuple[dict[str, float], dict[str, int], dict[str, int], dict[str, list[str]], dict[str, list[str]]]:
    """Run PageRank + fanin/fanout. NetworkX is preferred; if missing
    we fall back to a tiny power-iteration so the pipeline still works."""

    node_list = list(dict.fromkeys(node_ids))
    if not node_list:
        return {}, {}, {}, {}, {}

    fanin: dict[str, int] = dict.fromkeys(node_list, 0)
    fanout: dict[str, int] = dict.fromkeys(node_list, 0)
    callers: dict[str, dict[str, float]] = {fq: {} for fq in node_list}
    callees: dict[str, dict[str, float]] = {fq: {} for fq in node_list}
    for src, dst, weight in edges:
        if src not in fanout or dst not in fanin:
            continue
        fanout[src] = fanout.get(src, 0) + 1
        fanin[dst] = fanin.get(dst, 0) + 1
        callees[src][dst] = callees[src].get(dst, 0.0) + weight
        callers[dst][src] = callers[dst].get(src, 0.0) + weight

    try:
        import networkx as nx

        graph = nx.DiGraph()
        graph.add_nodes_from(node_list)
        for src, dst, weight in edges:
            if graph.has_edge(src, dst):
                graph[src][dst]["weight"] += weight
            else:
                graph.add_edge(src, dst, weight=weight)
        try:
            pagerank = nx.pagerank(graph, weight="weight", max_iter=100, tol=1.0e-6)
        except Exception:
            pagerank = nx.pagerank(graph, max_iter=100, tol=1.0e-6)
    except Exception:
        pagerank = _power_iteration_pagerank(node_list, edges)

    top_callers: dict[str, list[str]] = {
        fq: [src for src, _ in sorted(callers[fq].items(), key=lambda item: item[1], reverse=True)[:5]]
        for fq in node_list
    }
    top_callees: dict[str, list[str]] = {
        fq: [dst for dst, _ in sorted(callees[fq].items(), key=lambda item: item[1], reverse=True)[:5]]
        for fq in node_list
    }

    return pagerank, fanin, fanout, top_callers, top_callees


def _power_iteration_pagerank(
    node_list: list[str],
    edges: list[tuple[str, str, float]],
    *,
    damping: float = 0.85,
    max_iter: int = 50,
    tol: float = 1.0e-6,
) -> dict[str, float]:
    """Bare-bones PageRank fallback when networkx is unavailable."""

    if not node_list:
        return {}
    n = len(node_list)
    rank = dict.fromkeys(node_list, 1.0 / n)
    out_weight: dict[str, float] = dict.fromkeys(node_list, 0.0)
    out_targets: dict[str, list[tuple[str, float]]] = {fq: [] for fq in node_list}
    for src, dst, weight in edges:
        if src in out_weight and dst in rank:
            out_weight[src] += weight
            out_targets[src].append((dst, weight))

    for _ in range(max_iter):
        new = dict.fromkeys(node_list, (1.0 - damping) / n)
        sink_share = 0.0
        for fq in node_list:
            if out_weight[fq] == 0:
                sink_share += rank[fq]
        sink_share = damping * sink_share / n
        for fq in node_list:
            new[fq] += sink_share

        for src in node_list:
            if out_weight[src] == 0:
                continue
            share = damping * rank[src] / out_weight[src]
            for dst, weight in out_targets[src]:
                new[dst] += share * weight

        delta = sum(abs(new[fq] - rank[fq]) for fq in node_list)
        rank = new
        if delta < tol:
            break

    return rank


def normalized_pagerank(metrics: RepoMapMetrics) -> dict[str, float]:
    """Min-max-normalize raw PageRank to [0..1] for use in the
    significance score."""

    if not metrics.pagerank:
        return {}
    values = list(metrics.pagerank.values())
    lo = min(values)
    hi = max(values)
    if hi - lo < 1e-12:
        return {fq: 0.5 for fq in metrics.pagerank}
    return {fq: (score - lo) / (hi - lo) for fq, score in metrics.pagerank.items()}


def normalized_file_pagerank(metrics: RepoMapMetrics) -> dict[str, float]:
    """Same idea, but at the file level."""

    if not metrics.file_pagerank:
        return {}
    values = list(metrics.file_pagerank.values())
    lo = min(values)
    hi = max(values)
    if hi - lo < 1e-12:
        return {path: 0.5 for path in metrics.file_pagerank}
    return {path: (score - lo) / (hi - lo) for path, score in metrics.file_pagerank.items()}


def module_for_path(path: str) -> str:
    """Pick a stable module/package label for a path. Used as the
    grouping key for Module Briefs.

    Heuristic: take the first two path components when nested, the
    file stem when top-level. Mirrors how teams talk about modules.
    """

    pure = PurePosixPath(path)
    parts = list(pure.parts)
    if len(parts) >= 3:
        return "/".join(parts[:2])
    if len(parts) == 2:
        return parts[0]
    return pure.stem
