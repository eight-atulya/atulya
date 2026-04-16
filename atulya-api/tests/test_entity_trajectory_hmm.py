"""Unit tests for entity_trajectory hmm helpers."""

import math

from atulya_api.engine.entity_trajectory import hmm


def test_laplace_row_stochastic_rows_sum_to_one():
    counts = [[1, 2], [0, 3]]
    a = hmm.laplace_row_stochastic(counts, laplace_alpha=0.1)
    for row in a:
        assert abs(sum(row) - 1.0) < 1e-9


def test_viterbi_toy_two_state():
    k = 2
    log_start = [math.log(0.5), math.log(0.5)]
    log_trans = [[[math.log(0.9), math.log(0.1)], [math.log(0.2), math.log(0.8)]]]
    log_emit = [[0.0, -10.0], [-10.0, 0.0]]
    path, lp = hmm.viterbi(log_start, log_trans, log_emit)
    assert path == [0, 1]
    assert lp > -1e6


def test_forward_log_probability():
    k = 2
    log_start = [math.log(0.5), math.log(0.5)]
    log_trans = [[[math.log(0.5), math.log(0.5)], [math.log(0.5), math.log(0.5)]]]
    log_emit = [[math.log(0.7), math.log(0.3)], [math.log(0.4), math.log(0.6)]]
    lp = hmm.forward_log_probability(log_start, log_trans, log_emit)
    assert lp < 0.0


def test_matrix_power_identity_when_zero():
    a = [[0.5, 0.5], [0.5, 0.5]]
    i = hmm.matrix_power_row_stochastic(a, 0)
    assert i[0][0] == 1.0 and i[0][1] == 0.0


def test_forecast_distribution_sums_to_one():
    a = [[0.7, 0.3], [0.1, 0.9]]
    dist = hmm.forecast_distribution(a, 0, horizon=3)
    assert abs(sum(dist.values()) - 1.0) < 1e-9
