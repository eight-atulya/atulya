"""Gold-grade memory artifact builders.

Three artifact families per snapshot:

  - SymbolCard: per top-K significant symbol; the structured record an
    AI agent uses to "know" a function (signature, purpose, callers,
    callees, complexity, safety tags).
  - ModuleBrief: per package/folder; the public surface + dependencies
    + consumers + top symbols, plus a synthesized one-line purpose.
  - RepoMap: one per snapshot; ranked top-K symbols (the agent's tour
    of the codebase) plus module dependency edges and a snapshot-level
    summary.

All three are pure-Python dataclasses that serialize cleanly to JSON
and persist into `codebase_intel_artifacts.payload`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from ..codebase_index import IndexedEdge, IndexedFile
from .file_role import FileRole, classify_file_role
from .repo_map import RepoMapMetrics, module_for_path, normalized_pagerank
from .significance import SignificanceComponents, SignificanceScore


@dataclass(slots=True)
class SymbolCard:
    fq_name: str
    name: str
    kind: str
    language: str | None
    path: str
    start_line: int
    end_line: int
    signature: str
    purpose: str
    top_callers: list[str]
    top_callees: list[str]
    cyclomatic_complexity: int | None
    nloc: int | None
    safety_tags: list[str]
    pagerank: float
    fanin: int
    significance_score: float
    cluster_id: str | None
    chunk_key: str | None
    change_kind: str | None

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ModuleBrief:
    module: str
    purpose: str
    public_surface: list[str]
    internal_dependencies: list[str]
    external_consumers: list[str]
    top_symbols: list[str]
    file_count: int
    dominant_language: str | None
    dominant_role: str | None

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RepoMap:
    top_symbols: list[dict[str, Any]] = field(default_factory=list)
    module_edges: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "top_symbols": self.top_symbols,
            "module_edges": self.module_edges,
            "summary": self.summary,
        }


def build_artifacts(
    *,
    indexed_files: list[IndexedFile],
    file_edges: list[IndexedEdge],
    chunk_rows: list[dict[str, Any]],
    chunk_scores: dict[str, SignificanceScore],
    repo_map_metrics: RepoMapMetrics,
    chunk_complexity: dict[str, dict[str, Any]] | None = None,
    chunk_safety_tags: dict[str, list[str]] | None = None,
    file_text_provider: Callable[[str], str | None] | None = None,
    top_k_symbols: int = 200,
    top_k_modules: int = 60,
    top_k_repo_map: int = 100,
) -> tuple[list[SymbolCard], list[ModuleBrief], RepoMap]:
    """Build the three artifact families from the scored chunks."""

    chunk_complexity = chunk_complexity or {}
    chunk_safety_tags = chunk_safety_tags or {}

    symbol_to_chunks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in chunk_rows:
        fq = chunk.get("parent_fq_name") or chunk.get("label")
        if fq:
            symbol_to_chunks[fq].append(chunk)

    norm_pr = normalized_pagerank(repo_map_metrics)

    file_languages = {f.path: f.language for f in indexed_files}
    file_change_kinds = {f.path: f.change_kind for f in indexed_files}
    file_role_cache: dict[str, FileRole] = {}

    def _role_for(path: str) -> FileRole:
        cached = file_role_cache.get(path)
        if cached is None:
            cached = classify_file_role(path)
            file_role_cache[path] = cached
        return cached

    symbol_cards: list[SymbolCard] = []
    for fq_name, node in repo_map_metrics.nodes_by_fq.items():
        chunks_for_symbol = symbol_to_chunks.get(fq_name) or []
        primary_chunk = max(
            chunks_for_symbol,
            key=lambda c: chunk_scores.get(c["chunk_key"], _ZERO_SCORE).score,
            default=None,
        )
        primary_score = chunk_scores.get(primary_chunk["chunk_key"], _ZERO_SCORE) if primary_chunk else _ZERO_SCORE
        text = ""
        if primary_chunk:
            text = primary_chunk.get("content_text") or ""
        elif file_text_provider is not None:
            file_text = file_text_provider(node.path)
            if file_text:
                text = _slice_lines(file_text, node.start_line, node.end_line)

        signature = _extract_signature(text, node.kind, node.name, node.language)
        purpose = _extract_purpose(text, node.language)

        complexity_payload = chunk_complexity.get(primary_chunk["chunk_key"], {}) if primary_chunk else {}
        safety_for_symbol: list[str] = (
            chunk_safety_tags.get(primary_chunk["chunk_key"], []) if primary_chunk else primary_score.safety_tags
        )

        symbol_cards.append(
            SymbolCard(
                fq_name=node.fq_name,
                name=node.name,
                kind=node.kind,
                language=node.language,
                path=node.path,
                start_line=node.start_line,
                end_line=node.end_line,
                signature=signature,
                purpose=purpose,
                top_callers=repo_map_metrics.top_callers.get(fq_name, []),
                top_callees=repo_map_metrics.top_callees.get(fq_name, []),
                cyclomatic_complexity=complexity_payload.get("cyclomatic_complexity"),
                nloc=complexity_payload.get("nloc"),
                safety_tags=safety_for_symbol,
                pagerank=round(norm_pr.get(fq_name, 0.0), 4),
                fanin=int(repo_map_metrics.fanin.get(fq_name, 0)),
                significance_score=primary_score.score,
                cluster_id=primary_chunk.get("cluster_id") if primary_chunk else None,
                chunk_key=primary_chunk.get("chunk_key") if primary_chunk else None,
                change_kind=file_change_kinds.get(node.path),
            )
        )

    symbol_cards.sort(key=lambda card: (card.pagerank * 0.6 + card.significance_score * 0.4), reverse=True)
    symbol_cards = symbol_cards[:top_k_symbols]

    module_briefs = _build_module_briefs(
        indexed_files=indexed_files,
        file_edges=file_edges,
        repo_map_metrics=repo_map_metrics,
        symbol_cards=symbol_cards,
        file_role_cache=file_role_cache,
        file_languages=file_languages,
        top_k_modules=top_k_modules,
    )

    repo_map = _build_repo_map(
        indexed_files=indexed_files,
        file_edges=file_edges,
        repo_map_metrics=repo_map_metrics,
        symbol_cards=symbol_cards,
        chunk_safety_tags=chunk_safety_tags,
        chunk_complexity=chunk_complexity,
        top_k_repo_map=top_k_repo_map,
    )

    return symbol_cards, module_briefs, repo_map


def _build_module_briefs(
    *,
    indexed_files: list[IndexedFile],
    file_edges: list[IndexedEdge],
    repo_map_metrics: RepoMapMetrics,
    symbol_cards: list[SymbolCard],
    file_role_cache: dict[str, FileRole],
    file_languages: dict[str, str | None],
    top_k_modules: int,
) -> list[ModuleBrief]:
    files_by_module: dict[str, list[IndexedFile]] = defaultdict(list)
    for indexed in indexed_files:
        files_by_module[module_for_path(indexed.path)].append(indexed)

    module_imports: dict[str, set[str]] = defaultdict(set)
    module_consumers: dict[str, set[str]] = defaultdict(set)
    for edge in file_edges:
        if edge.edge_type != "imports" or not edge.to_path:
            continue
        from_module = module_for_path(edge.from_path)
        to_module = module_for_path(edge.to_path)
        if from_module == to_module:
            continue
        module_imports[from_module].add(to_module)
        module_consumers[to_module].add(from_module)

    cards_by_module: dict[str, list[SymbolCard]] = defaultdict(list)
    for card in symbol_cards:
        cards_by_module[module_for_path(card.path)].append(card)

    briefs: list[ModuleBrief] = []
    for module, files in files_by_module.items():
        cards = cards_by_module.get(module, [])
        roles = Counter(file_role_cache.get(f.path, classify_file_role(f.path)).value for f in files)
        languages = Counter(filter(None, (file_languages.get(f.path) for f in files)))
        public_surface = [card.fq_name for card in cards[:10]]
        top_symbols = [card.fq_name for card in cards[:3]]
        purpose = _synthesize_module_purpose(cards, files)
        briefs.append(
            ModuleBrief(
                module=module,
                purpose=purpose,
                public_surface=public_surface,
                internal_dependencies=sorted(module_imports.get(module, set()))[:25],
                external_consumers=sorted(module_consumers.get(module, set()))[:25],
                top_symbols=top_symbols,
                file_count=len(files),
                dominant_language=languages.most_common(1)[0][0] if languages else None,
                dominant_role=roles.most_common(1)[0][0] if roles else None,
            )
        )

    briefs.sort(key=lambda b: (-len(b.public_surface), -b.file_count, b.module))
    return briefs[:top_k_modules]


def _build_repo_map(
    *,
    indexed_files: list[IndexedFile],
    file_edges: list[IndexedEdge],
    repo_map_metrics: RepoMapMetrics,
    symbol_cards: list[SymbolCard],
    chunk_safety_tags: dict[str, list[str]],
    chunk_complexity: dict[str, dict[str, Any]],
    top_k_repo_map: int,
) -> RepoMap:
    top_symbols = [
        {
            "fq_name": card.fq_name,
            "name": card.name,
            "kind": card.kind,
            "language": card.language,
            "path": card.path,
            "start_line": card.start_line,
            "signature": card.signature,
            "pagerank": card.pagerank,
            "fanin": card.fanin,
            "safety_tags": card.safety_tags,
        }
        for card in symbol_cards[:top_k_repo_map]
    ]

    module_edge_counts: Counter[tuple[str, str]] = Counter()
    for edge in file_edges:
        if edge.edge_type != "imports" or not edge.to_path:
            continue
        from_module = module_for_path(edge.from_path)
        to_module = module_for_path(edge.to_path)
        if from_module != to_module:
            module_edge_counts[(from_module, to_module)] += 1

    module_edges = [
        {"from": from_module, "to": to_module, "weight": weight}
        for (from_module, to_module), weight in module_edge_counts.most_common(150)
    ]

    languages = Counter(filter(None, (f.language for f in indexed_files)))
    safety_summary: Counter[str] = Counter()
    for tags in chunk_safety_tags.values():
        for tag in tags:
            safety_summary[tag] += 1
    complexity_values = [c.get("cyclomatic_complexity", 0) or 0 for c in chunk_complexity.values()]
    summary: dict[str, Any] = {
        "total_files": len(indexed_files),
        "languages": dict(languages.most_common()),
        "safety_summary": dict(safety_summary.most_common()),
        "complexity": {
            "max_cyclomatic": max(complexity_values, default=0),
            "p95_cyclomatic": _percentile(complexity_values, 0.95),
            "samples": len(complexity_values),
        },
    }

    return RepoMap(top_symbols=top_symbols, module_edges=module_edges, summary=summary)


def _synthesize_module_purpose(cards: list[SymbolCard], files: list[IndexedFile]) -> str:
    for card in cards:
        if card.purpose and len(card.purpose) > 20:
            return _truncate(card.purpose, 200)
    if files:
        languages = ", ".join(sorted({f.language for f in files if f.language}))
        return f"Module containing {len(files)} files ({languages or 'mixed'})."
    return ""


def _extract_signature(text: str, kind: str, name: str, language: str | None) -> str:
    if not text:
        return name
    first_lines = text.splitlines()[:6]
    if not first_lines:
        return name
    if language == "python":
        for line in first_lines:
            stripped = line.strip()
            if stripped.startswith(("def ", "async def ", "class ")):
                return _truncate(stripped.rstrip(":"), 240)
    if language in {"typescript", "tsx", "javascript", "jsx"}:
        for line in first_lines:
            stripped = line.strip()
            if any(
                stripped.startswith(prefix)
                for prefix in ("export ", "function ", "class ", "const ", "let ", "interface ", "type ", "async ")
            ):
                return _truncate(stripped.rstrip("{").strip(), 240)
    return _truncate(first_lines[0].strip(), 240)


def _extract_purpose(text: str, language: str | None) -> str:
    if not text:
        return ""
    if language == "python":
        parse_docstring: Callable[[str], Any] | None = None
        try:
            from docstring_parser import parse as _parse_docstring  # type: ignore[import-untyped]

            parse_docstring = _parse_docstring
        except Exception:
            parse_docstring = None
        triple = _extract_python_docstring(text)
        if triple and parse_docstring is not None:
            try:
                parsed = parse_docstring(triple)
                desc = (parsed.short_description or "").strip() or (parsed.long_description or "").strip()
                if desc:
                    return _truncate(desc, 400)
            except Exception:
                pass
        if triple:
            return _truncate(_first_paragraph(triple), 400)

    comment = _extract_leading_comment(text, language)
    if comment:
        return _truncate(comment, 400)
    return ""


def _extract_python_docstring(text: str) -> str | None:
    lines = text.splitlines()
    body_start = None
    for index, line in enumerate(lines):
        if line.lstrip().startswith(("def ", "async def ", "class ")):
            body_start = index + 1
            break
    if body_start is None:
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(('"""', "'''", '"', "'")):
                body_start = index
                break
    if body_start is None or body_start >= len(lines):
        return None

    body = "\n".join(lines[body_start:]).lstrip()
    for marker in ('"""', "'''"):
        if body.startswith(marker):
            end = body.find(marker, len(marker))
            if end != -1:
                return body[len(marker) : end].strip()
    return None


def _extract_leading_comment(text: str, language: str | None) -> str:
    lines = text.splitlines()
    collected: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if collected:
                break
            continue
        if stripped.startswith("#"):
            collected.append(stripped.lstrip("# ").strip())
            continue
        if stripped.startswith("//"):
            collected.append(stripped.lstrip("/ ").strip())
            continue
        if stripped.startswith("/*"):
            inner = stripped.lstrip("/* ").rstrip(" */")
            collected.append(inner.strip())
            continue
        if stripped.startswith("*"):
            collected.append(stripped.lstrip("* ").strip())
            continue
        break
    return " ".join(part for part in collected if part)[:600]


def _slice_lines(text: str, start_line: int, end_line: int) -> str:
    lines = text.splitlines()
    start_idx = max(0, start_line - 1)
    end_idx = min(len(lines), end_line)
    return "\n".join(lines[start_idx:end_idx])


def _first_paragraph(text: str) -> str:
    paragraph: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            if paragraph:
                break
            continue
        paragraph.append(line.strip())
    return " ".join(paragraph)


def _percentile(values: Iterable[int], pct: float) -> float:
    items = sorted(int(v) for v in values)
    if not items:
        return 0.0
    k = max(0, min(len(items) - 1, int(round(pct * (len(items) - 1)))))
    return float(items[k])


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "\u2026"


_ZERO_SCORE = SignificanceScore(
    score=0.0,
    components=SignificanceComponents(),
    route_hint="review",
    reason="no-score",
    safety_tags=[],
)
