"""Tree-sitter based call/reference edge extraction.

Augments the existing import-only edges from ASDParser with symbol-level
call edges so the repo-map PageRank can rank actual function importance,
not just file importance.

This is intentionally heuristic and lightweight: we walk the tree
looking for `call`/`call_expression` nodes and record the callee name.
For precise cross-references the SCIP reader is preferred (see
scip_reader.py); these heuristics are the always-on fallback.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..codebase_index import ASDParser, IndexedSymbol, detect_language


@dataclass(slots=True, frozen=True)
class ReferenceEdge:
    """A heuristic call/reference edge.

    `from_symbol_fq` is the fully qualified caller (or '<module>' when
    the call happens at module top level). `to_name` is the callee name
    as written in source -- resolution happens later in repo_map.
    """

    from_path: str
    from_symbol_fq: str
    to_name: str


_PY_CALL_TYPES = {"call"}
_JS_CALL_TYPES = {"call_expression", "new_expression"}


def collect_reference_edges(
    *,
    path: str,
    text: str,
    symbols: list[IndexedSymbol],
) -> list[ReferenceEdge]:
    """Walk the AST and emit one ReferenceEdge per call site.

    Returns an empty list for unsupported languages (silent fallback)."""

    language = detect_language(path)
    if not language:
        return []
    try:
        parser = ASDParser.get_parser(language)
    except Exception:
        return []

    source_bytes = text.encode("utf-8")
    try:
        root = parser.parse(source_bytes).root_node
    except Exception:
        return []

    if language == "python":
        call_types = _PY_CALL_TYPES
    elif language in {"javascript", "typescript", "tsx", "jsx"}:
        call_types = _JS_CALL_TYPES
    else:
        return []

    enclosing = _build_enclosing_index(symbols)
    edges: list[ReferenceEdge] = []
    seen: set[tuple[str, str, str]] = set()

    def visit(node) -> None:
        if node.type in call_types:
            callee_name = _extract_callee_name(node, source_bytes, language)
            if callee_name:
                start_line = node.start_point[0] + 1
                from_fq = _enclosing_symbol_fq(enclosing, start_line)
                key = (path, from_fq, callee_name)
                if key not in seen:
                    seen.add(key)
                    edges.append(
                        ReferenceEdge(
                            from_path=path,
                            from_symbol_fq=from_fq,
                            to_name=callee_name,
                        )
                    )
        for child in node.named_children:
            visit(child)

    visit(root)
    return edges


def _extract_callee_name(node, source_bytes: bytes, language: str) -> str | None:
    """Pull a usable callee name out of a call node.

    For attribute calls (e.g. `foo.bar()` or `obj.method()`) we keep the
    last attribute -- it's a heuristic but matches how aider's repo-map
    treats references."""

    func_field = node.child_by_field_name("function") or node.child_by_field_name("constructor")
    target = func_field
    if target is None and node.named_children:
        target = node.named_children[0]
    if target is None:
        return None

    if target.type in {"identifier", "type_identifier", "property_identifier"}:
        return _node_text(source_bytes, target)

    if target.type in {"attribute", "member_expression"}:
        attr = target.child_by_field_name("attribute") or target.child_by_field_name("property")
        if attr is not None:
            return _node_text(source_bytes, attr)

    return _node_text(source_bytes, target)


def _node_text(source_bytes: bytes, node) -> str | None:
    if node is None:
        return None
    text = source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace").strip()
    return text or None


def _build_enclosing_index(symbols: list[IndexedSymbol]) -> list[tuple[int, int, str]]:
    """Sort symbols by start_line; we'll binary-walk to find the
    innermost enclosing symbol for a given line."""

    return sorted(
        ((symbol.start_line, symbol.end_line, symbol.fq_name) for symbol in symbols),
        key=lambda item: (item[0], -item[1]),
    )


def _enclosing_symbol_fq(symbol_ranges: list[tuple[int, int, str]], line: int) -> str:
    """Linear scan -- symbols are usually <500 per file so this is
    fine. Returns '<module>' when the line is not inside any symbol."""

    best_fq = "<module>"
    best_span = None
    for start, end, fq in symbol_ranges:
        if start <= line <= end:
            span = end - start
            if best_span is None or span < best_span:
                best_span = span
                best_fq = fq
    return best_fq
