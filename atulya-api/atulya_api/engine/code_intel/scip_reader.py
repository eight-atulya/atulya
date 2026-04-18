"""Optional SCIP index reader.

If the user runs `scip-python`, `scip-typescript`, etc. as part of their
codebase upload and an `index.scip` file is present, this module parses
the protobuf and produces precise symbol references that supersede the
tree-sitter heuristic edges from references.py.

The protobuf descriptor lives in the `scip-protobuf` PyPI package. We
import lazily so the module is silent and harmless when scip-protobuf
is not installed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ScipReference:
    """A single precise definition or reference parsed from a SCIP index."""

    document_path: str
    symbol: str  # SCIP-format symbol id (locally-stable string)
    is_definition: bool
    line: int  # 1-based line of the occurrence


def read_scip_index(scip_bytes: bytes) -> list[ScipReference]:
    """Parse a SCIP `Index` protobuf payload into a list of references.

    Returns an empty list (and never raises) if scip-protobuf is not
    installed or the payload is unparseable -- the pipeline silently
    falls back to tree-sitter heuristics."""

    try:
        from scip_pb2 import Index  # type: ignore[import-untyped]
    except Exception:
        try:
            from scip.scip_pb2 import Index  # type: ignore[import-untyped]
        except Exception:
            return []

    try:
        index = Index()
        index.ParseFromString(scip_bytes)
    except Exception:
        return []

    out: list[ScipReference] = []
    for document in index.documents:
        path = document.relative_path
        for occurrence in document.occurrences:
            symbol = occurrence.symbol
            if not symbol:
                continue
            line = (occurrence.range[0] + 1) if occurrence.range else 1
            is_def = bool(occurrence.symbol_roles & 0x1)
            out.append(
                ScipReference(
                    document_path=path,
                    symbol=symbol,
                    is_definition=is_def,
                    line=line,
                )
            )
    return out


def has_scip_support() -> bool:
    """Used by callers / tests to decide whether to bother."""

    try:
        import scip_pb2  # type: ignore[import-untyped]  # noqa: F401

        return True
    except Exception:
        try:
            import scip.scip_pb2  # type: ignore[import-untyped]  # noqa: F401

            return True
        except Exception:
            return False
