"""Unit tests for the new code intelligence pipeline modules.

Covers the deterministic, dependency-free pieces:
- file_role classification
- safety tag scanning + safety priority
- significance scoring + auto-route policy
- repo_map graph construction + PageRank
- pipeline orchestration end-to-end on a tiny synthetic project
"""

from __future__ import annotations

import pytest

from atulya_api.engine.code_intel import (
    classify_file_role,
    compute_significance,
    run_pipeline,
)
from atulya_api.engine.code_intel.file_role import (
    FileRole,
    is_dismiss_role,
    is_high_value_role,
    role_weight,
)
from atulya_api.engine.code_intel.metrics import FunctionMetrics
from atulya_api.engine.code_intel.repo_map import (
    build_repo_map_metrics,
    module_for_path,
    normalized_pagerank,
)
from atulya_api.engine.code_intel.safety import (
    safety_priority,
    scan_text_for_safety_tags,
)
from atulya_api.engine.code_intel.significance import SignificanceThresholds
from atulya_api.engine.codebase_index import IndexedEdge, IndexedFile, IndexedSymbol


# ---------------------------------------------------------------------------
# file_role
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path, expected",
    [
        ("services/main.py", FileRole.ENTRYPOINT),
        ("apps/web/src/index.ts", FileRole.ENTRYPOINT),
        ("backend/api/routes/users.py", FileRole.API_ROUTE),
        ("backend/handlers/login.py", FileRole.API_ROUTE),
        ("src/utils/strings.py", FileRole.SHARED_UTIL),
        ("infra/db.py", FileRole.PUBLIC_LIB),
        ("config/settings.py", FileRole.CONFIG),
        ("alembic/versions/0001_init.py", FileRole.MIGRATION),
        ("backend/migrations/0001.py", FileRole.MIGRATION),
        ("tests/test_payments.py", FileRole.TEST),
        ("docs/architecture.md", FileRole.DOCS),
        ("fixtures/users.json", FileRole.FIXTURE),
        ("dist/bundle.js", FileRole.GENERATED),
        ("vendor/lib/foo.py", FileRole.VENDORED),
        ("node_modules/react/index.js", FileRole.VENDORED),
        ("src/models/user.py", FileRole.SCHEMA_MODEL),
    ],
)
def test_classify_file_role(path: str, expected: FileRole) -> None:
    assert classify_file_role(path) == expected


def test_role_weight_relative_ordering() -> None:
    assert role_weight(FileRole.ENTRYPOINT) > role_weight(FileRole.SHARED_UTIL)
    assert role_weight(FileRole.SHARED_UTIL) > role_weight(FileRole.TEST)
    assert role_weight(FileRole.TEST) > role_weight(FileRole.GENERATED)


def test_role_dismiss_and_high_value_helpers() -> None:
    assert is_dismiss_role(FileRole.GENERATED) is True
    assert is_dismiss_role(FileRole.VENDORED) is True
    assert is_dismiss_role(FileRole.BOILERPLATE) is True
    assert is_dismiss_role(FileRole.SHARED_UTIL) is False
    assert is_high_value_role(FileRole.ENTRYPOINT) is True
    assert is_high_value_role(FileRole.API_ROUTE) is True
    assert is_high_value_role(FileRole.TEST) is False


# ---------------------------------------------------------------------------
# safety
# ---------------------------------------------------------------------------


def test_scan_text_for_safety_tags_detects_common_patterns() -> None:
    text = """
    import jwt
    import subprocess
    def login(password):
        token = jwt.encode({'pw': password}, 'secret')
        subprocess.run(['ls'], shell=True)
        return token
    """
    tags = set(scan_text_for_safety_tags(text))
    assert "auth" in tags
    assert "subprocess" in tags


def test_scan_text_for_safety_tags_detects_sql_and_eval() -> None:
    text = """
    cursor.execute("SELECT * FROM users WHERE id = " + user_id)
    eval(user_input)
    """
    tags = set(scan_text_for_safety_tags(text))
    assert "sql_string" in tags
    assert "eval" in tags


def test_safety_priority_orders_by_severity() -> None:
    assert safety_priority(["eval"]) >= safety_priority(["network"])
    assert safety_priority(["auth"]) >= safety_priority(["sql_string"])
    assert safety_priority([]) == 0.0


# ---------------------------------------------------------------------------
# significance
# ---------------------------------------------------------------------------


def _significance(**overrides):
    base = dict(
        chunk_kind="function",
        chunk_text="def add(a, b):\n    return a + b\n",
        chunk_label="add",
        parent_fq_name=None,
        file_role=FileRole.SHARED_UTIL,
        pagerank_for_symbol=0.0,
        pagerank_for_file=0.0,
        fanin_count=0,
        complexity=None,
        safety_tags=[],
        is_cluster_representative=False,
        change_kind="unchanged",
        parse_confidence=0.9,
        chunk_lines=5,
        language="python",
    )
    base.update(overrides)
    return compute_significance(**base)


def test_compute_significance_dismisses_generated_files() -> None:
    score = _significance(file_role=FileRole.GENERATED)
    assert score.route_hint == "dismiss"


def test_compute_significance_dismisses_vendored_files() -> None:
    score = _significance(file_role=FileRole.VENDORED)
    assert score.route_hint == "dismiss"


def test_compute_significance_promotes_high_pagerank_symbols() -> None:
    score = _significance(
        file_role=FileRole.API_ROUTE,
        pagerank_for_symbol=0.9,
        pagerank_for_file=0.5,
        fanin_count=12,
        chunk_kind="function",
        complexity=FunctionMetrics(
            name="handle_payment",
            start_line=1,
            end_line=40,
            nloc=35,
            cyclomatic_complexity=14,
            parameter_count=4,
        ),
        safety_tags=["auth", "sql_string"],
    )
    assert score.route_hint == "memory"
    assert score.score > 0.5


def test_compute_significance_keeps_gray_zone_in_review() -> None:
    score = _significance(
        file_role=FileRole.SHARED_UTIL,
        pagerank_for_symbol=0.05,
        pagerank_for_file=0.05,
        fanin_count=1,
        chunk_kind="function",
        complexity=FunctionMetrics(
            name="util",
            start_line=1,
            end_line=10,
            nloc=8,
            cyclomatic_complexity=3,
            parameter_count=1,
        ),
    )
    assert score.route_hint == "review"


def test_compute_significance_thresholds_can_be_lowered() -> None:
    permissive = SignificanceThresholds(high=0.05, centrality=0.0, safety=0.0)
    score = compute_significance(
        chunk_kind="function",
        chunk_text="def f():\n    return 1\n",
        chunk_label="f",
        parent_fq_name=None,
        file_role=FileRole.SHARED_UTIL,
        pagerank_for_symbol=0.0,
        pagerank_for_file=0.0,
        fanin_count=0,
        complexity=None,
        safety_tags=[],
        is_cluster_representative=False,
        change_kind="unchanged",
        parse_confidence=0.9,
        chunk_lines=2,
        language="python",
        thresholds=permissive,
    )
    assert score.route_hint in {"memory", "review"}


# ---------------------------------------------------------------------------
# repo_map
# ---------------------------------------------------------------------------


def _make_indexed_file(
    path: str,
    *,
    symbols: list[IndexedSymbol],
    edges: list[IndexedEdge] | None = None,
    language: str | None = "python",
    text: str = "",
) -> IndexedFile:
    return IndexedFile(
        path=path,
        language=language,
        size_bytes=len(text.encode("utf-8")),
        content_hash="hash-" + path,
        status="indexed",
        reason=None,
        retain_text=text,
        should_parse_symbols=True,
        change_kind="unchanged",
        symbols=symbols,
        edges=edges or [],
        chunks=[],
    )


def test_module_for_path_uses_first_non_root_segment() -> None:
    assert module_for_path("services/api/main.py") == "services/api"
    assert module_for_path("toplevel.py") == "toplevel"
    assert module_for_path("a/b/c/d.py") == "a/b"
    assert module_for_path("a/b.py") == "a"


def test_build_repo_map_metrics_assigns_pagerank() -> None:
    f1_symbols = [
        IndexedSymbol(
            name="add",
            kind="function",
            fq_name="util.add",
            path="util.py",
            language="python",
            container=None,
            start_line=1,
            end_line=2,
        ),
    ]
    f2_symbols = [
        IndexedSymbol(
            name="run",
            kind="function",
            fq_name="main.run",
            path="main.py",
            language="python",
            container=None,
            start_line=1,
            end_line=4,
        ),
    ]
    f1 = _make_indexed_file(
        "util.py",
        symbols=f1_symbols,
        text="def add(a, b):\n    return a + b\n",
    )
    f2 = _make_indexed_file(
        "main.py",
        symbols=f2_symbols,
        text="from util import add\n\ndef run():\n    return add(1, 2)\n",
    )
    metrics = build_repo_map_metrics(
        indexed_files=[f1, f2],
        file_edges=[
            IndexedEdge(
                edge_type="import",
                from_path="main.py",
                to_path="util.py",
            )
        ],
        file_text_provider=lambda path: f1.retain_text if path == "util.py" else f2.retain_text,
    )
    assert "util.py" in metrics.file_pagerank
    assert "main.py" in metrics.file_pagerank
    norm = normalized_pagerank(metrics)
    assert isinstance(norm, dict)
    for value in norm.values():
        assert 0.0 <= value <= 1.0
    assert metrics.fanin.get("util.add", 0) >= 1


# ---------------------------------------------------------------------------
# pipeline (end-to-end smoke test)
# ---------------------------------------------------------------------------


def test_run_pipeline_smoke_end_to_end() -> None:
    util_text = "def add(a, b):\n    return a + b\n\ndef helper():\n    return add(1, 2)\n"
    main_text = (
        "from util import add\n\n"
        "def run():\n"
        "    return add(1, 2)\n\n"
        "def login(password):\n"
        "    import jwt\n"
        "    return jwt.encode({'pw': password}, 'secret')\n"
    )
    util_symbols = [
        IndexedSymbol(
            name="add",
            kind="function",
            fq_name="util.add",
            path="util.py",
            language="python",
            container=None,
            start_line=1,
            end_line=2,
        ),
        IndexedSymbol(
            name="helper",
            kind="function",
            fq_name="util.helper",
            path="util.py",
            language="python",
            container=None,
            start_line=4,
            end_line=5,
        ),
    ]
    main_symbols = [
        IndexedSymbol(
            name="run",
            kind="function",
            fq_name="main.run",
            path="main.py",
            language="python",
            container=None,
            start_line=3,
            end_line=4,
        ),
        IndexedSymbol(
            name="login",
            kind="function",
            fq_name="main.login",
            path="main.py",
            language="python",
            container=None,
            start_line=6,
            end_line=8,
        ),
    ]
    util_file = _make_indexed_file("util.py", symbols=util_symbols, text=util_text)
    main_file = _make_indexed_file(
        "main.py",
        symbols=main_symbols,
        text=main_text,
        edges=[
            IndexedEdge(
                edge_type="import",
                from_path="main.py",
                to_path="util.py",
            )
        ],
    )
    login_text = (
        "def login(password):\n"
        "    import jwt\n"
        "    return jwt.encode({'pw': password}, 'secret')\n"
    )
    chunk_rows = [
        {
            "id": "chunk-1",
            "chunk_key": "util.py::add",
            "path": "util.py",
            "language": "python",
            "kind": "function",
            "label": "add",
            "content_text": "def add(a, b):\n    return a + b\n",
            "preview_text": util_text,
            "start_line": 1,
            "end_line": 2,
            "container": None,
            "parent_symbol": None,
            "parent_fq_name": "util.add",
            "parse_confidence": 0.9,
            "cluster_id": None,
            "cluster_label": None,
            "change_kind": "unchanged",
            "related_count": 0,
        },
        {
            "id": "chunk-2",
            "chunk_key": "main.py::run",
            "path": "main.py",
            "language": "python",
            "kind": "function",
            "label": "run",
            "content_text": "def run():\n    return add(1, 2)\n",
            "preview_text": main_text,
            "start_line": 3,
            "end_line": 4,
            "container": None,
            "parent_symbol": None,
            "parent_fq_name": "main.run",
            "parse_confidence": 0.9,
            "cluster_id": None,
            "cluster_label": None,
            "change_kind": "unchanged",
            "related_count": 0,
        },
        {
            "id": "chunk-3",
            "chunk_key": "main.py::login",
            "path": "main.py",
            "language": "python",
            "kind": "function",
            "label": "login",
            "content_text": login_text,
            "preview_text": login_text,
            "start_line": 6,
            "end_line": 8,
            "container": None,
            "parent_symbol": None,
            "parent_fq_name": "main.login",
            "parse_confidence": 0.9,
            "cluster_id": None,
            "cluster_label": None,
            "change_kind": "unchanged",
            "related_count": 0,
        },
    ]

    result = run_pipeline(
        indexed_files=[util_file, main_file],
        file_edges=main_file.edges,
        chunk_rows=chunk_rows,
        file_text_provider=lambda path: util_text if path == "util.py" else main_text,
        enable_safety_scan=True,
    )

    expected_keys = {"util.py::add", "main.py::run", "main.py::login"}
    assert set(result.chunk_scores.keys()) == expected_keys

    login_score = result.chunk_scores["main.py::login"]
    assert "auth" in login_score.safety_tags

    assert result.repo_map_metrics is not None
    assert isinstance(result.repo_map_metrics.file_pagerank, dict)
    assert "util.py" in result.repo_map_metrics.file_pagerank

    assert result.repo_map is not None
    assert result.repo_map.top_symbols, "RepoMap should rank at least one symbol"
    assert result.module_briefs, "Module briefs should be produced"
    assert result.symbol_cards, "Symbol cards should be produced"

    for hint in (s.route_hint for s in result.chunk_scores.values()):
        assert hint in {"memory", "review", "dismiss"}
