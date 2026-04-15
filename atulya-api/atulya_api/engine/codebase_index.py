"""
ASD-backed deterministic codebase archive indexing helpers.

This module keeps codebase import logic mechanical and non-LLM:
- unpack ZIP archives safely
- normalize and filter file paths
- classify files for retain/index/exclude decisions
- use ASD tree-sitter parsing for supported languages
- emit deterministic symbols and import edges for query APIs
"""

from __future__ import annotations

import fnmatch
import hashlib
import io
import posixpath
import re
import threading
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_parser

_MANIFEST_FILES = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "poetry.lock",
    "pipfile",
    "pipfile.lock",
    "cargo.toml",
    "cargo.lock",
    "go.mod",
    "go.sum",
    "composer.json",
    "composer.lock",
}

_EXCLUDED_DIRS = {
    ".git",
    ".next",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
}

_BINARY_EXTENSIONS = {
    ".7z",
    ".a",
    ".bin",
    ".bmp",
    ".class",
    ".dll",
    ".dylib",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".mp3",
    ".mp4",
    ".o",
    ".otf",
    ".pdf",
    ".png",
    ".pyc",
    ".pyd",
    ".so",
    ".svg",
    ".tar",
    ".tgz",
    ".ttf",
    ".wav",
    ".webm",
    ".woff",
    ".woff2",
    ".zip",
}

_TEXT_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".graphql",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".md",
    ".mjs",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scss",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}

_DEEP_PARSE_LANGUAGES = {"python", "javascript", "typescript", "jsx", "tsx"}
_MAX_MANIFEST_ONLY_TEXT_BYTES = 512 * 1024
_JS_REQUIRE_RE = re.compile(r"""(?:(?:^|[^\w$])require\(\s*["'](?P<require>[^"']+)["']\s*\))""")
_JS_DYNAMIC_IMPORT_RE = re.compile(r"""import\(\s*["'](?P<dynamic>[^"']+)["']\s*\)""")


@dataclass(slots=True)
class ArchiveSourceFile:
    """Normalized file extracted from a codebase archive."""

    path: str
    data: bytes
    size_bytes: int


@dataclass(slots=True)
class IndexedSymbol:
    """Deterministically extracted symbol metadata."""

    name: str
    kind: str
    fq_name: str
    path: str
    language: str | None
    container: str | None
    start_line: int
    end_line: int


@dataclass(slots=True)
class IndexedEdge:
    """Relationship emitted by deterministic code analysis."""

    edge_type: str
    from_path: str
    to_path: str | None = None
    from_symbol: str | None = None
    to_symbol: str | None = None
    target_ref: str | None = None
    label: str | None = None


@dataclass(slots=True)
class IndexedChunk:
    """Deterministic semantic chunk metadata."""

    chunk_key: str
    path: str
    language: str | None
    kind: str
    label: str
    content_hash: str
    content_text: str
    preview_text: str
    start_line: int
    end_line: int
    container: str | None = None
    parent_symbol: str | None = None
    parent_fq_name: str | None = None
    parse_confidence: float = 0.5


@dataclass(slots=True)
class IndexedFile:
    """Final normalized file record used for database persistence."""

    path: str
    language: str | None
    size_bytes: int
    content_hash: str
    status: str
    reason: str | None
    retain_text: str | None
    should_parse_symbols: bool
    document_tags: list[str] = field(default_factory=list)
    change_kind: str = "added"
    symbols: list[IndexedSymbol] = field(default_factory=list)
    edges: list[IndexedEdge] = field(default_factory=list)
    chunks: list[IndexedChunk] = field(default_factory=list)


@dataclass(slots=True)
class ArchiveIndexResult:
    """Complete deterministic index output for a snapshot."""

    files: list[IndexedFile]
    added_files: list[str]
    changed_files: list[str]
    unchanged_files: list[str]
    deleted_files: list[str]
    chunk_count: int = 0
    parse_coverage: float = 0.0


@dataclass(slots=True)
class ASDParseResult:
    """Symbols and graph edges emitted by the ASD parser."""

    symbols: list[IndexedSymbol]
    edges: list[IndexedEdge]


def _normalize_path(raw_path: str) -> str | None:
    candidate = raw_path.replace("\\", "/").strip()
    if not candidate or candidate.endswith("/"):
        return None

    normalized = posixpath.normpath(candidate)
    if normalized in (".", ""):
        return None
    if normalized.startswith("../") or normalized == ".." or normalized.startswith("/"):
        return None
    return normalized


def _detect_archive_root(paths: Iterable[str]) -> str | None:
    first_parts = []
    normalized_paths = [path for path in paths if path]
    if not normalized_paths:
        return None
    for path in normalized_paths:
        parts = path.split("/", 1)
        first_parts.append(parts[0])
    unique_parts = set(first_parts)
    if len(unique_parts) != 1:
        return None
    root = first_parts[0]
    if not root:
        return None
    for path in normalized_paths:
        if path == root:
            return None
    return root


def _strip_prefix(path: str, prefix: str | None) -> str | None:
    if not prefix:
        return path
    clean_prefix = prefix.strip("/").replace("\\", "/")
    if not clean_prefix:
        return path
    if path == clean_prefix:
        return None
    if path.startswith(f"{clean_prefix}/"):
        return path[len(clean_prefix) + 1 :]
    return None


def _path_matches_globs(path: str, patterns: list[str] | None) -> bool:
    if not patterns:
        return True
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def load_zip_archive(
    archive_bytes: bytes,
    *,
    root_path: str | None = None,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
) -> list[ArchiveSourceFile]:
    """Safely unpack a ZIP archive into normalized source files."""

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        raw_names = [_normalize_path(info.filename) for info in archive.infolist() if not info.is_dir()]
        raw_names = [name for name in raw_names if name]
        auto_root = _detect_archive_root(raw_names)

        results: list[ArchiveSourceFile] = []
        for info in archive.infolist():
            if info.is_dir():
                continue
            normalized = _normalize_path(info.filename)
            if not normalized:
                continue
            normalized = _strip_prefix(normalized, auto_root)
            normalized = _strip_prefix(normalized or "", root_path)
            if not normalized:
                continue
            if not _path_matches_globs(normalized, include_globs):
                continue
            if exclude_globs and any(fnmatch.fnmatch(normalized, pattern) for pattern in exclude_globs):
                continue
            with archive.open(info, "r") as handle:
                data = handle.read()
            results.append(ArchiveSourceFile(path=normalized, data=data, size_bytes=len(data)))
        return results


def detect_language(path: str) -> str | None:
    """Detect language label from file name and extension."""

    lower_name = PurePosixPath(path).name.lower()
    suffix = PurePosixPath(path).suffix.lower()
    if lower_name in _MANIFEST_FILES:
        return suffix.lstrip(".") or lower_name
    if suffix == ".py":
        return "python"
    if suffix == ".ts":
        return "typescript"
    if suffix == ".tsx":
        return "tsx"
    if suffix == ".jsx":
        return "jsx"
    if suffix in {".js", ".mjs"}:
        return "javascript"
    if suffix:
        return suffix.lstrip(".")
    return None


def _is_manifest_file(path: str) -> bool:
    return PurePosixPath(path).name.lower() in _MANIFEST_FILES


def _is_binary_data(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data:
        return True
    sample = data[:2048]
    non_text = sum(1 for b in sample if b < 9 or (13 < b < 32))
    return non_text / max(len(sample), 1) > 0.2


def _decode_text(data: bytes) -> str | None:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _line_slice(text: str, start_line: int, end_line: int) -> str:
    lines = text.splitlines()
    start_index = max(0, start_line - 1)
    end_index = min(len(lines), end_line)
    return "\n".join(lines[start_index:end_index]).strip()


def _compact_preview(text: str, max_chars: int = 220) -> str:
    single_line = " ".join(text.strip().split())
    if len(single_line) <= max_chars:
        return single_line
    return f"{single_line[: max_chars - 1].rstrip()}..."


def _chunk_key(path: str, kind: str, label: str, start_line: int, end_line: int) -> str:
    raw = f"{path}|{kind}|{label}|{start_line}|{end_line}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _build_chunk(
    *,
    path: str,
    language: str | None,
    kind: str,
    label: str,
    content_text: str,
    start_line: int,
    end_line: int,
    container: str | None,
    parent_symbol: str | None,
    parent_fq_name: str | None,
    parse_confidence: float,
) -> IndexedChunk | None:
    normalized_text = content_text.strip()
    if not normalized_text:
        return None
    chunk_key = _chunk_key(path, kind, label, start_line, end_line)
    geo_header = f"# {path}  lines {start_line}-{end_line}\n"
    stored_content_text = f"{geo_header}{normalized_text}"
    return IndexedChunk(
        chunk_key=chunk_key,
        path=path,
        language=language,
        kind=kind,
        label=label,
        content_hash=hashlib.sha256(stored_content_text.encode("utf-8")).hexdigest(),
        content_text=stored_content_text,
        preview_text=_compact_preview(stored_content_text),
        start_line=start_line,
        end_line=end_line,
        container=container,
        parent_symbol=parent_symbol,
        parent_fq_name=parent_fq_name,
        parse_confidence=parse_confidence,
    )


def _build_region_chunks(
    *,
    path: str,
    language: str | None,
    text: str,
    occupied_ranges: list[tuple[int, int]],
    label_prefix: str,
    parse_confidence: float,
    max_lines: int = 80,
) -> list[IndexedChunk]:
    lines = text.splitlines()
    if not lines:
        return []

    covered = [False] * len(lines)
    for start_line, end_line in occupied_ranges:
        for index in range(max(0, start_line - 1), min(len(lines), end_line)):
            covered[index] = True

    chunks: list[IndexedChunk] = []
    start_index: int | None = None
    region_index = 0

    def flush(end_index: int) -> None:
        nonlocal start_index, region_index
        if start_index is None or end_index < start_index:
            start_index = None
            return
        cursor = start_index
        while cursor <= end_index:
            chunk_end = min(end_index, cursor + max_lines - 1)
            segment_lines = lines[cursor : chunk_end + 1]
            segment_text = "\n".join(segment_lines).strip()
            if segment_text:
                region_index += 1
                chunk = _build_chunk(
                    path=path,
                    language=language,
                    kind="region",
                    label=f"{label_prefix} section {region_index}",
                    content_text=segment_text,
                    start_line=cursor + 1,
                    end_line=chunk_end + 1,
                    container=None,
                    parent_symbol=None,
                    parent_fq_name=None,
                    parse_confidence=parse_confidence,
                )
                if chunk:
                    chunks.append(chunk)
            cursor = chunk_end + 1
        start_index = None

    for index, is_covered in enumerate(covered):
        if not is_covered and lines[index].strip():
            if start_index is None:
                start_index = index
            continue
        if start_index is not None:
            flush(index - 1)

    if start_index is not None:
        flush(len(lines) - 1)

    return chunks


def _is_excluded_by_default(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    if any(part in _EXCLUDED_DIRS for part in parts):
        return "excluded_dir"
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in _BINARY_EXTENSIONS:
        return "binary_extension"
    return None


def _is_probably_generated(path: str, text: str) -> str | None:
    name = PurePosixPath(path).name.lower()
    if name.endswith(".min.js") or name.endswith(".min.css"):
        return "minified"
    if len(text) > _MAX_MANIFEST_ONLY_TEXT_BYTES:
        return "large_text_file"
    longest_line = max((len(line) for line in text.splitlines()), default=0)
    if longest_line > 1200:
        return "generated_long_lines"
    return None


def _build_python_module_map(paths: Iterable[str]) -> dict[str, str]:
    module_map: dict[str, str] = {}
    for path in paths:
        pure = PurePosixPath(path)
        if pure.suffix.lower() != ".py":
            continue
        parts = list(pure.parts)
        if parts[-1] == "__init__.py":
            module = ".".join(parts[:-1])
        else:
            parts[-1] = pure.stem
            module = ".".join(parts)
        if module:
            module_map[module] = path
    return module_map


def _module_name_for_path(path: str) -> str | None:
    pure = PurePosixPath(path)
    if pure.suffix.lower() != ".py":
        return None
    parts = list(pure.parts)
    if parts[-1] == "__init__.py":
        return ".".join(parts[:-1]) or None
    parts[-1] = pure.stem
    return ".".join(parts) or None


def _resolve_python_import(
    current_path: str,
    module: str | None,
    name: str | None,
    level: int,
    module_map: dict[str, str],
) -> tuple[str | None, str | None]:
    current_module = _module_name_for_path(current_path) or ""
    current_parts = current_module.split(".") if current_module else []
    if current_parts and PurePosixPath(current_path).name != "__init__.py":
        current_parts = current_parts[:-1]
    if level > 0:
        base_parts = current_parts[: -(level - 1)] if level - 1 <= len(current_parts) else []
    else:
        base_parts = []

    module_parts = module.split(".") if module else []
    base_module = ".".join([part for part in [*base_parts, *module_parts] if part])
    candidates = [candidate for candidate in [base_module, f"{base_module}.{name}" if name else None] if candidate]
    for candidate in candidates:
        if candidate in module_map:
            return module_map[candidate], candidate
    return None, candidates[0] if candidates else None


def _line_number(node: Node) -> tuple[int, int]:
    return node.start_point.row + 1, node.end_point.row + 1


def _node_text(source_bytes: bytes, node: Node | None) -> str | None:
    if node is None:
        return None
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")


def _walk(node: Node) -> Iterator[Node]:
    yield node
    for child in node.named_children:
        yield from _walk(child)


def _string_content(source_bytes: bytes, node: Node | None) -> str | None:
    raw = _node_text(source_bytes, node)
    if not raw:
        return None
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] in {"'", '"'} and raw[-1] == raw[0]:
        return raw[1:-1]
    return raw


def _collect_python_assignment_names(node: Node, source_bytes: bytes) -> list[str]:
    names: list[str] = []
    for child in _walk(node):
        if child.type == "identifier":
            text = _node_text(source_bytes, child)
            if text:
                names.append(text)
    return names


class ASDParser:
    """Proprietary mechanical parser facade backed by tree-sitter."""

    _parsers: dict[str, Parser] = {}
    _lock = threading.Lock()

    @classmethod
    def _parser_name(cls, language: str) -> str:
        if language == "jsx":
            return "javascript"
        return language

    @classmethod
    def get_parser(cls, language: str) -> Parser:
        parser_name = cls._parser_name(language)
        with cls._lock:
            parser = cls._parsers.get(parser_name)
            if parser is None:
                parser = get_parser(parser_name)
                cls._parsers[parser_name] = parser
            return parser

    @classmethod
    def parse_file(
        cls,
        *,
        path: str,
        text: str,
        module_map: dict[str, str],
        path_set: set[str],
    ) -> ASDParseResult:
        language = detect_language(path)
        if language == "python":
            return cls._parse_python(path, text, module_map)
        if language in {"javascript", "typescript", "jsx", "tsx"}:
            return cls._parse_js_ts(path, text, path_set)
        return ASDParseResult(symbols=[], edges=[])

    @classmethod
    def _parse_python(cls, path: str, text: str, module_map: dict[str, str]) -> ASDParseResult:
        source_bytes = text.encode("utf-8")
        root = cls.get_parser("python").parse(source_bytes).root_node
        symbols: list[IndexedSymbol] = []
        edges: list[IndexedEdge] = []

        def visit(node: Node, container: list[str]) -> None:
            if node.type == "class_definition":
                name_node = node.child_by_field_name("name")
                name = _node_text(source_bytes, name_node)
                if not name:
                    return
                start_line, end_line = _line_number(node)
                container_name = ".".join(container) if container else None
                fq_name = f"{container_name}.{name}" if container_name else name
                symbols.append(
                    IndexedSymbol(
                        name=name,
                        kind="class",
                        fq_name=fq_name,
                        path=path,
                        language="python",
                        container=container_name,
                        start_line=start_line,
                        end_line=end_line,
                    )
                )
                body = node.child_by_field_name("body")
                if body:
                    visit(body, [*container, name])
                return

            if node.type == "function_definition":
                name_node = node.child_by_field_name("name")
                name = _node_text(source_bytes, name_node)
                if not name:
                    return
                start_line, end_line = _line_number(node)
                container_name = ".".join(container) if container else None
                fq_name = f"{container_name}.{name}" if container_name else name
                symbols.append(
                    IndexedSymbol(
                        name=name,
                        kind="function",
                        fq_name=fq_name,
                        path=path,
                        language="python",
                        container=container_name,
                        start_line=start_line,
                        end_line=end_line,
                    )
                )
                body = node.child_by_field_name("body")
                if body:
                    visit(body, [*container, name])
                return

            if node.type == "assignment" and not container:
                left = node.child_by_field_name("left")
                for name in _collect_python_assignment_names(left or node, source_bytes):
                    start_line, end_line = _line_number(node)
                    symbols.append(
                        IndexedSymbol(
                            name=name,
                            kind="variable",
                            fq_name=name,
                            path=path,
                            language="python",
                            container=None,
                            start_line=start_line,
                            end_line=end_line,
                        )
                    )

            if node.type == "import_statement":
                for child in node.named_children:
                    if child.type not in {"dotted_name", "aliased_import"}:
                        continue
                    module_name = None
                    if child.type == "aliased_import":
                        module_name = _node_text(
                            source_bytes, child.named_children[0] if child.named_children else None
                        )
                    else:
                        module_name = _node_text(source_bytes, child)
                    if not module_name:
                        continue
                    target_path, target_ref = _resolve_python_import(path, module_name, None, 0, module_map)
                    edges.append(
                        IndexedEdge(
                            edge_type="imports",
                            from_path=path,
                            to_path=target_path,
                            target_ref=target_ref or module_name,
                            label=module_name,
                        )
                    )

            if node.type == "import_from_statement":
                module: str | None = None
                level = 0
                names: list[str | None] = []
                first = node.named_children[0] if node.named_children else None
                remaining = list(node.named_children[1:]) if len(node.named_children) > 1 else []
                if first and first.type == "relative_import":
                    prefix = first.children[0] if first.children else None
                    prefix_text = _node_text(source_bytes, prefix) or ""
                    level = len(prefix_text)
                    dotted = next((child for child in first.named_children if child.type == "dotted_name"), None)
                    module = _node_text(source_bytes, dotted)
                elif first and first.type == "dotted_name":
                    module = _node_text(source_bytes, first)

                for child in remaining:
                    if child.type == "aliased_import":
                        dotted = next((item for item in child.named_children if item.type == "dotted_name"), None)
                        names.append(_node_text(source_bytes, dotted))
                    elif child.type == "dotted_name":
                        names.append(_node_text(source_bytes, child))
                if not names:
                    names = [None]

                for imported_name in names:
                    target_path, target_ref = _resolve_python_import(path, module, imported_name, level, module_map)
                    edges.append(
                        IndexedEdge(
                            edge_type="imports",
                            from_path=path,
                            to_path=target_path,
                            target_ref=target_ref or module or imported_name,
                            label=imported_name or module,
                        )
                    )

            for child in node.named_children:
                visit(child, container)

        visit(root, [])
        return ASDParseResult(symbols=symbols, edges=edges)

    @classmethod
    def _parse_js_ts(cls, path: str, text: str, path_set: set[str]) -> ASDParseResult:
        source_bytes = text.encode("utf-8")
        language = detect_language(path)
        parser = cls.get_parser(language or "javascript")
        root = parser.parse(source_bytes).root_node
        symbols: list[IndexedSymbol] = []
        edges: list[IndexedEdge] = []
        seen_symbols: set[tuple[str, str, int]] = set()
        seen_edges: set[tuple[str, str | None]] = set()

        def add_symbol(name: str, kind: str, node: Node, container: str | None = None) -> None:
            start_line, end_line = _line_number(node)
            key = (name, kind, start_line)
            if key in seen_symbols:
                return
            seen_symbols.add(key)
            fq_name = f"{container}.{name}" if container else name
            symbols.append(
                IndexedSymbol(
                    name=name,
                    kind=kind,
                    fq_name=fq_name,
                    path=path,
                    language=language,
                    container=container,
                    start_line=start_line,
                    end_line=end_line,
                )
            )

        def add_edge(specifier: str | None, node: Node) -> None:
            if not specifier:
                return
            key = (specifier, _resolve_relative_import(path, specifier, path_set))
            if key in seen_edges:
                return
            seen_edges.add(key)
            edges.append(
                IndexedEdge(
                    edge_type="imports",
                    from_path=path,
                    to_path=key[1],
                    target_ref=specifier,
                    label=specifier,
                )
            )

        def collect_declaration(node: Node, exported: bool = False, container: str | None = None) -> None:
            if node.type == "function_declaration":
                name = _node_text(source_bytes, node.child_by_field_name("name"))
                if name:
                    add_symbol(name, "function", node, container)
                return

            if node.type == "class_declaration":
                name = _node_text(source_bytes, node.child_by_field_name("name"))
                if name:
                    add_symbol(name, "class", node, container)
                body = node.child_by_field_name("body")
                if name and body:
                    for child in body.named_children:
                        if child.type == "method_definition":
                            method_name = _node_text(source_bytes, child.child_by_field_name("name"))
                            if method_name:
                                add_symbol(method_name, "function", child, name)
                return

            if node.type == "interface_declaration":
                name = _node_text(source_bytes, node.child_by_field_name("name"))
                if name:
                    add_symbol(name, "interface", node, container)
                return

            if node.type == "type_alias_declaration":
                name = _node_text(source_bytes, node.child_by_field_name("name"))
                if name:
                    add_symbol(name, "type", node, container)
                return

            if node.type == "enum_declaration":
                name = _node_text(source_bytes, node.child_by_field_name("name"))
                if name:
                    add_symbol(name, "enum", node, container)
                return

            if node.type in {"lexical_declaration", "variable_declaration"}:
                for declarator in node.named_children:
                    if declarator.type != "variable_declarator":
                        continue
                    name = _node_text(source_bytes, declarator.child_by_field_name("name"))
                    if not name:
                        continue
                    value = declarator.child_by_field_name("value")
                    kind = (
                        "function"
                        if value and value.type in {"arrow_function", "function_expression", "generator_function"}
                        else "class"
                        if value and value.type == "class"
                        else "variable"
                    )
                    add_symbol(name, kind, declarator, container)
                return

            if node.type == "export_statement":
                source_node = node.child_by_field_name("source")
                add_edge(_string_content(source_bytes, source_node), node)
                for child in node.named_children:
                    if child.type in {
                        "function_declaration",
                        "class_declaration",
                        "lexical_declaration",
                        "variable_declaration",
                        "interface_declaration",
                        "type_alias_declaration",
                        "enum_declaration",
                    }:
                        collect_declaration(child, exported=True, container=container)
                return

            if node.type == "import_statement":
                source_node = node.child_by_field_name("source")
                add_edge(_string_content(source_bytes, source_node), node)
                return

        for child in root.named_children:
            collect_declaration(child)

        for match in _JS_REQUIRE_RE.finditer(text):
            add_edge(match.group("require"), root)
        for match in _JS_DYNAMIC_IMPORT_RE.finditer(text):
            add_edge(match.group("dynamic"), root)

        return ASDParseResult(symbols=symbols, edges=edges)


def _resolve_relative_import(current_path: str, specifier: str, path_set: set[str]) -> str | None:
    if not specifier.startswith("."):
        return None

    base_dir = PurePosixPath(current_path).parent
    candidate = posixpath.normpath(posixpath.join(str(base_dir), specifier))
    direct_candidates = [candidate]
    if not PurePosixPath(candidate).suffix:
        direct_candidates.extend(
            [
                f"{candidate}.ts",
                f"{candidate}.tsx",
                f"{candidate}.js",
                f"{candidate}.jsx",
                f"{candidate}.mjs",
                f"{candidate}/index.ts",
                f"{candidate}/index.tsx",
                f"{candidate}/index.js",
                f"{candidate}/index.jsx",
                f"{candidate}/index.mjs",
            ]
        )
    for path in direct_candidates:
        normalized = _normalize_path(path)
        if normalized and normalized in path_set:
            return normalized
    return None


def _symbol_chunks_for_text(
    *,
    path: str,
    language: str | None,
    text: str,
    symbols: list[IndexedSymbol],
) -> list[IndexedChunk]:
    chunks: list[IndexedChunk] = []
    seen_ranges: set[tuple[int, int, str]] = set()
    for symbol in sorted(symbols, key=lambda item: (item.start_line, item.end_line, item.fq_name)):
        key = (symbol.start_line, symbol.end_line, symbol.fq_name)
        if key in seen_ranges or symbol.end_line < symbol.start_line:
            continue
        seen_ranges.add(key)
        symbol_text = _line_slice(text, symbol.start_line, symbol.end_line)
        chunk = _build_chunk(
            path=path,
            language=language,
            kind=symbol.kind,
            label=symbol.fq_name,
            content_text=symbol_text,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            container=symbol.container,
            parent_symbol=symbol.name,
            parent_fq_name=symbol.fq_name,
            parse_confidence=1.0,
        )
        if chunk:
            chunks.append(chunk)
    return chunks


def build_semantic_chunks(
    *,
    path: str,
    language: str | None,
    text: str,
    symbols: list[IndexedSymbol],
) -> list[IndexedChunk]:
    """Build semantic chunks from parsed symbols with deterministic fallback regions."""

    symbol_chunks = _symbol_chunks_for_text(path=path, language=language, text=text, symbols=symbols)
    occupied = [(chunk.start_line, chunk.end_line) for chunk in symbol_chunks]
    label_prefix = PurePosixPath(path).name

    if symbol_chunks:
        fallback_chunks = _build_region_chunks(
            path=path,
            language=language,
            text=text,
            occupied_ranges=occupied,
            label_prefix=label_prefix,
            parse_confidence=0.72,
        )
        return [*symbol_chunks, *fallback_chunks]

    return _build_region_chunks(
        path=path,
        language=language,
        text=text,
        occupied_ranges=[],
        label_prefix=label_prefix,
        parse_confidence=0.55,
    )


class ASDIndexer:
    """Mechanical codebase indexer that wraps ASD parsing and diffing."""

    @classmethod
    def build_archive_index(
        cls,
        source_files: list[ArchiveSourceFile],
        *,
        previous_hashes: dict[str, str] | None = None,
    ) -> ArchiveIndexResult:
        previous_hashes = previous_hashes or {}
        paths = {source.path for source in source_files}
        module_map = _build_python_module_map(paths)
        indexed_files: list[IndexedFile] = []
        added_files: list[str] = []
        changed_files: list[str] = []
        unchanged_files: list[str] = []
        parse_candidate_count = 0
        parsed_file_count = 0
        chunk_count = 0

        for source in sorted(source_files, key=lambda item: item.path):
            excluded_reason = _is_excluded_by_default(source.path)
            content_hash = hashlib.sha256(source.data).hexdigest()
            language = detect_language(source.path)
            change_kind = "added"
            if source.path in previous_hashes:
                change_kind = "unchanged" if previous_hashes[source.path] == content_hash else "modified"

            if excluded_reason:
                indexed_files.append(
                    IndexedFile(
                        path=source.path,
                        language=language,
                        size_bytes=source.size_bytes,
                        content_hash=content_hash,
                        status="excluded",
                        reason=excluded_reason,
                        retain_text=None,
                        should_parse_symbols=False,
                        change_kind=change_kind,
                    )
                )
                continue

            suffix = PurePosixPath(source.path).suffix.lower()
            manifest = _is_manifest_file(source.path)
            if suffix not in _TEXT_EXTENSIONS and not manifest:
                indexed_files.append(
                    IndexedFile(
                        path=source.path,
                        language=language,
                        size_bytes=source.size_bytes,
                        content_hash=content_hash,
                        status="manifest_only",
                        reason="unsupported_text_type",
                        retain_text=None,
                        should_parse_symbols=False,
                        change_kind=change_kind,
                    )
                )
                continue

            if _is_binary_data(source.data):
                indexed_files.append(
                    IndexedFile(
                        path=source.path,
                        language=language,
                        size_bytes=source.size_bytes,
                        content_hash=content_hash,
                        status="manifest_only",
                        reason="binary_content",
                        retain_text=None,
                        should_parse_symbols=False,
                        change_kind=change_kind,
                    )
                )
                continue

            text = _decode_text(source.data)
            if text is None:
                indexed_files.append(
                    IndexedFile(
                        path=source.path,
                        language=language,
                        size_bytes=source.size_bytes,
                        content_hash=content_hash,
                        status="manifest_only",
                        reason="undecodable_text",
                        retain_text=None,
                        should_parse_symbols=False,
                        change_kind=change_kind,
                    )
                )
                continue

            generated_reason = _is_probably_generated(source.path, text)
            if generated_reason:
                indexed_files.append(
                    IndexedFile(
                        path=source.path,
                        language=language,
                        size_bytes=source.size_bytes,
                        content_hash=content_hash,
                        status="manifest_only",
                        reason=generated_reason,
                        retain_text=None,
                        should_parse_symbols=False,
                        change_kind=change_kind,
                    )
                )
                continue

            status = "indexed" if language in _DEEP_PARSE_LANGUAGES else "retained"
            indexed_file = IndexedFile(
                path=source.path,
                language=language,
                size_bytes=source.size_bytes,
                content_hash=content_hash,
                status=status,
                reason=None,
                retain_text=text,
                should_parse_symbols=language in _DEEP_PARSE_LANGUAGES,
                change_kind=change_kind,
            )

            if indexed_file.should_parse_symbols:
                parse_candidate_count += 1
                try:
                    parsed = ASDParser.parse_file(
                        path=source.path,
                        text=text,
                        module_map=module_map,
                        path_set=paths,
                    )
                    indexed_file.symbols = parsed.symbols
                    indexed_file.edges = parsed.edges
                    parsed_file_count += 1
                except Exception:
                    indexed_file.status = "retained"
                    indexed_file.reason = "asd_parse_error"
                    indexed_file.should_parse_symbols = False

            indexed_file.chunks = build_semantic_chunks(
                path=source.path,
                language=language,
                text=text,
                symbols=indexed_file.symbols,
            )
            chunk_count += len(indexed_file.chunks)
            indexed_files.append(indexed_file)
            if change_kind == "added":
                added_files.append(source.path)
            elif change_kind == "modified":
                changed_files.append(source.path)
            else:
                unchanged_files.append(source.path)

        previous_paths = set(previous_hashes)
        deleted_files = sorted(previous_paths - paths)
        return ArchiveIndexResult(
            files=indexed_files,
            added_files=added_files,
            changed_files=changed_files,
            unchanged_files=unchanged_files,
            deleted_files=deleted_files,
            chunk_count=chunk_count,
            parse_coverage=(parsed_file_count / parse_candidate_count) if parse_candidate_count else 0.0,
        )


def build_archive_index(
    source_files: list[ArchiveSourceFile],
    *,
    previous_hashes: dict[str, str] | None = None,
) -> ArchiveIndexResult:
    """Compatibility wrapper for the ASD-backed archive indexer."""

    return ASDIndexer.build_archive_index(source_files, previous_hashes=previous_hashes)
