"""
Regression tests for Group 3 of the hindsight bugfix backport.

The bug: ``apply_combined_scoring`` treated cross-encoder scores as
authoritative, so a misconfigured / passthrough reranker that returns the
same score for every result destroyed the RRF order of recall — every
result tied at the same combined score, and final ordering was effectively
random within the tie group.

The fix detects degenerate CE scores (≤ 1 unique normalized score across ≥ 2
results) and reseeds ``cross_encoder_score_normalized`` from the RRF rank
via a stable monotone mapping ``(N - rank + 1) / N``. This preserves the
original retrieval order even when the reranker is broken or disabled.
"""

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from atulya_api.engine.search.reranking import apply_combined_scoring
from atulya_api.engine.search.types import MergedCandidate, RetrievalResult, ScoredResult

UTC = timezone.utc
NOW = datetime(2024, 6, 1, tzinfo=UTC)


def _make_result(ce_norm: float, rrf_rank: int) -> ScoredResult:
    retrieval = MagicMock(spec=RetrievalResult)
    retrieval.occurred_start = None
    retrieval.temporal_proximity = None
    retrieval.fact_type = "world"
    retrieval.proof_count = 0

    candidate = MagicMock(spec=MergedCandidate)
    candidate.retrieval = retrieval
    candidate.rrf_score = 0.05
    candidate.rrf_rank = rrf_rank
    candidate.source_ranks = {}

    return ScoredResult(
        candidate=candidate,
        cross_encoder_score=1.0,
        cross_encoder_score_normalized=ce_norm,
        weight=ce_norm,
    )


class TestPassthroughFallback:
    def test_uniform_ce_scores_falls_back_to_rrf_order(self, caplog):
        """When every result has the same CE score, fall back to RRF rank."""
        # 3 results, identical CE scores, distinct RRF ranks (1=best, 3=worst)
        results = [
            _make_result(ce_norm=0.5, rrf_rank=2),
            _make_result(ce_norm=0.5, rrf_rank=1),
            _make_result(ce_norm=0.5, rrf_rank=3),
        ]

        with caplog.at_level(logging.WARNING, logger="atulya_api.engine.search.reranking"):
            apply_combined_scoring(results, now=NOW)

        # Sorted by weight descending should now match RRF rank ascending.
        sorted_by_weight = sorted(results, key=lambda r: r.weight, reverse=True)
        assert [r.candidate.rrf_rank for r in sorted_by_weight] == [1, 2, 3], (
            "Expected RRF order to be preserved when CE scores are degenerate"
        )

        # Warning should have been emitted exactly once
        warnings = [rec for rec in caplog.records if "passthrough" in rec.getMessage()]
        assert len(warnings) == 1

    def test_real_reranker_scores_override_rrf(self, caplog):
        """Diverse CE scores must override the RRF order, no fallback."""
        # Best RRF rank gets the worst CE score; CE must win.
        results = [
            _make_result(ce_norm=0.1, rrf_rank=1),
            _make_result(ce_norm=0.9, rrf_rank=2),
            _make_result(ce_norm=0.5, rrf_rank=3),
        ]

        with caplog.at_level(logging.WARNING, logger="atulya_api.engine.search.reranking"):
            apply_combined_scoring(results, now=NOW)

        sorted_by_weight = sorted(results, key=lambda r: r.weight, reverse=True)
        # CE-driven order: 0.9, 0.5, 0.1
        assert [r.candidate.rrf_rank for r in sorted_by_weight] == [2, 3, 1]

        warnings = [rec for rec in caplog.records if "passthrough" in rec.getMessage()]
        assert warnings == [], "Should not warn about passthrough when CE scores diverge"

    def test_single_result_does_not_trigger_fallback(self, caplog):
        """A 1-result batch can't be 'passthrough' — no fallback, no warning."""
        results = [_make_result(ce_norm=0.5, rrf_rank=1)]

        with caplog.at_level(logging.WARNING, logger="atulya_api.engine.search.reranking"):
            apply_combined_scoring(results, now=NOW)

        warnings = [rec for rec in caplog.records if "passthrough" in rec.getMessage()]
        assert warnings == []
        # Score is preserved unchanged
        assert results[0].cross_encoder_score_normalized == 0.5

    def test_two_distinct_scores_does_not_trigger_fallback(self):
        """Even 2 unique CE scores is enough to trust the reranker."""
        results = [
            _make_result(ce_norm=0.4, rrf_rank=1),
            _make_result(ce_norm=0.6, rrf_rank=2),
        ]
        apply_combined_scoring(results, now=NOW)
        # CE-driven order: 0.6 first, 0.4 second
        sorted_by_weight = sorted(results, key=lambda r: r.weight, reverse=True)
        assert [r.candidate.rrf_rank for r in sorted_by_weight] == [2, 1]

    def test_fallback_preserves_strictly_decreasing_scores(self):
        """The synthetic CE proxy must be strictly decreasing so the final
        order is deterministic and never ties.
        """
        results = [_make_result(ce_norm=0.5, rrf_rank=i + 1) for i in range(5)]
        apply_combined_scoring(results, now=NOW)
        sorted_by_weight = sorted(results, key=lambda r: r.weight, reverse=True)
        # Strictly decreasing weights and RRF ranks 1..5 in order
        weights = [r.weight for r in sorted_by_weight]
        assert all(weights[i] > weights[i + 1] for i in range(len(weights) - 1)), (
            "Synthetic fallback scores must be strictly decreasing"
        )
        assert [r.candidate.rrf_rank for r in sorted_by_weight] == [1, 2, 3, 4, 5]

    def test_fallback_handles_missing_rrf_rank(self):
        """A candidate with rrf_rank=0 (unset/legacy) must not crash and is
        treated as worst — placed at the end of the synthetic order.
        """
        results = [
            _make_result(ce_norm=0.5, rrf_rank=1),
            _make_result(ce_norm=0.5, rrf_rank=2),
            _make_result(ce_norm=0.5, rrf_rank=0),  # missing
        ]
        apply_combined_scoring(results, now=NOW)
        # Still completes without IndexError or division-by-zero
        assert all(r.weight > 0.0 for r in results)
