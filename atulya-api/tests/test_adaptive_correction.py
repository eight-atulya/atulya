from atulya_api.engine.adaptive_correction import _adaptive_alpha


def test_adaptive_alpha_increases_with_severity():
    low = _adaptive_alpha(0.2)
    high = _adaptive_alpha(0.9)
    assert high > low

