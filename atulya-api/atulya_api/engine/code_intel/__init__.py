"""Code intelligence pipeline.

Turns mechanical chunks + edges from the ASD index into:
  - per-chunk significance scores with explainable component breakdowns
  - deterministic auto-route hints (dismiss / memory / review)
  - gold-grade memory artifacts (Symbol Cards, Module Briefs, Repo Map)

The pipeline is built on proven libraries:
  - tree-sitter (already wired) for AST parsing
  - aider-style symbol+reference graph + NetworkX PageRank for importance
  - lizard for cyclomatic complexity / NLOC
  - Semgrep (curated rulepack, opt-in via settings) for safety tags
  - Jina/Voyage code embeddings via CodeEmbeddingProvider abstraction
  - SCIP indexers (opt-in) for precise cross-references

All heavy/optional dependencies are lazy-imported so the module loads
fast and degrades gracefully when extras are not installed.
"""

from .artifacts import ModuleBrief, RepoMap, SymbolCard, build_artifacts
from .embeddings import CodeEmbeddingProvider, get_code_embedding_provider
from .file_role import FileRole, classify_file_role
from .pipeline import CodeIntelResult, run_pipeline
from .references import collect_reference_edges
from .repo_map import RepoMapMetrics, build_repo_map_metrics
from .significance import SignificanceScore, compute_significance

__all__ = [
    "CodeEmbeddingProvider",
    "CodeIntelResult",
    "FileRole",
    "ModuleBrief",
    "RepoMap",
    "RepoMapMetrics",
    "SignificanceScore",
    "SymbolCard",
    "build_artifacts",
    "build_repo_map_metrics",
    "classify_file_role",
    "collect_reference_edges",
    "compute_significance",
    "get_code_embedding_provider",
    "run_pipeline",
]
