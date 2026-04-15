from datetime import UTC, datetime

from atulya_api.engine.pattern_library import _feature_set, _jaccard
from atulya_api.engine.retain.types import ProcessedFact


def _fact() -> ProcessedFact:
    return ProcessedFact(
        fact_text="Alice believes tests are useful.",
        fact_type="opinion",
        embedding=[0.1, 0.2],
        occurred_start=datetime.now(UTC),
        occurred_end=None,
        mentioned_at=datetime.now(UTC),
        timeline_anchor_kind="recorded_only",
        temporal_direction="atemporal",
        temporal_confidence=None,
        temporal_reference_text=None,
        context="engineering",
        metadata={"source": "note"},
    )


def test_feature_set_contains_fact_type_marker():
    features = _feature_set(_fact())
    assert "fact_type:opinion" in features
    assert "has_context" in features


def test_jaccard_similarity():
    left = {"a", "b"}
    right = {"b", "c"}
    assert _jaccard(left, right) == 1 / 3

