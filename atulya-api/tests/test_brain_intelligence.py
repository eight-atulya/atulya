from datetime import UTC, datetime, timedelta

from atulya_api.brain.intelligence import (
    InfluenceFeatures,
    confidence_bands,
    ewma,
    hour_weekday_heatmap,
    iqr_anomaly_flags,
    influence_score,
    recency_decay_score,
    robust_zscore,
)


def test_recency_decay_is_bounded():
    assert 0.0 <= recency_decay_score(0) <= 1.0
    assert 0.0 <= recency_decay_score(30) <= 1.0
    assert recency_decay_score(1) > recency_decay_score(10)


def test_influence_score_has_decomposition():
    score, parts = influence_score(
        InfluenceFeatures(
            recency_days=2.0,
            access_freq=0.6,
            graph_signal=0.4,
            rerank_signal=0.5,
            dream_signal=0.3,
        )
    )
    assert 0.0 <= score <= 1.0
    assert set(parts.keys()) == {"recency", "freq", "graph", "rerank", "dream"}
    assert abs(sum(parts.values()) - score) < 1e-5


def test_heatmap_rows_shape():
    now = datetime.now(UTC)
    rows = hour_weekday_heatmap([now - timedelta(hours=i) for i in range(10)])
    assert len(rows) == 7 * 24
    assert {"weekday", "hour_utc", "count", "score"}.issubset(rows[0].keys())


def test_ewma_and_robust_zscore():
    series = [0.2, 0.25, 0.21, 0.27, 0.9]
    smooth = ewma(series)
    assert len(smooth) == len(series)
    z = robust_zscore(smooth[-1], smooth)
    assert isinstance(z, float)


def test_confidence_bands_shape():
    series = [0.1, 0.2, 0.3]
    bands = confidence_bands(series)
    assert len(bands) == len(series)
    assert {"value", "lower", "upper"}.issubset(bands[0].keys())


def test_iqr_anomaly_flags_detect_outlier():
    flags = iqr_anomaly_flags([0.1, 0.12, 0.11, 0.13, 2.0])
    assert len(flags) == 5
    assert flags[-1] is True
