"""
Activity prediction models for atulya-brain.

Implements real learning algorithms using only standard library math:
- Histogram: frequency-based hourly distribution
- Kalman filter: 1D per-hour state estimation with adaptive smoothing
- HMM: 2-state (active/inactive) forward algorithm with Baum-Welch update

All models operate on hourly UTC buckets (0-23) and produce normalised
probability distributions suitable for activity time prediction.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import UTC, datetime
from typing import Any


def build_histogram(events: list[datetime]) -> dict[str, Any]:
    """Normalised hourly frequency histogram."""
    if not events:
        return {"type": "histogram", "hourly_histogram": {}, "sample_count": 0}
    histogram = Counter(str(evt.astimezone(UTC).hour) for evt in events)
    total = sum(histogram.values())
    return {
        "type": "histogram",
        "hourly_histogram": {k: v / total for k, v in histogram.items()},
        "sample_count": total,
    }


def build_kalman(
    events: list[datetime],
    *,
    prior: dict[str, Any] | None = None,
    process_noise: float = 0.01,
    measurement_noise: float = 0.05,
) -> dict[str, Any]:
    """
    1D Kalman filter per hour bucket.

    State vector: 24 scalars (one per hour), each representing the
    expected activity probability for that hour.

    When a prior model exists (e.g. from a previous brain or remote
    brain), the filter fuses the prior estimate with new observations
    to produce a smoothed posterior — this is how brains learn from
    each other over time.
    """
    state = [0.0] * 24
    variance = [1.0] * 24

    if prior and "kalman_state" in prior:
        for i, val in enumerate(prior["kalman_state"][:24]):
            state[i] = float(val)
        for i, val in enumerate(prior.get("kalman_variance", [0.5] * 24)[:24]):
            variance[i] = float(val)

    if events:
        histogram = Counter(evt.astimezone(UTC).hour for evt in events)
        total = sum(histogram.values())
        for hour in range(24):
            measurement = histogram.get(hour, 0) / total if total > 0 else 0.0

            predicted_var = variance[hour] + process_noise
            kalman_gain = predicted_var / (predicted_var + measurement_noise)
            state[hour] = state[hour] + kalman_gain * (measurement - state[hour])
            variance[hour] = (1.0 - kalman_gain) * predicted_var

    total_state = sum(max(0.0, s) for s in state)
    normalised = {}
    for hour in range(24):
        val = max(0.0, state[hour])
        if val > 0 and total_state > 0:
            normalised[str(hour)] = val / total_state

    return {
        "type": "kalman",
        "hourly_histogram": normalised,
        "sample_count": len(events),
        "kalman_state": state,
        "kalman_variance": variance,
        "process_noise": process_noise,
        "measurement_noise": measurement_noise,
    }


def build_hmm(
    events: list[datetime],
    *,
    prior: dict[str, Any] | None = None,
    em_iterations: int = 5,
) -> dict[str, Any]:
    """
    2-state HMM (active / inactive) with emission over 24 hourly bins.

    Transition matrix:
        [[stay_inactive, go_active],
         [go_inactive,   stay_active]]

    Emission matrix:
        For each state, a 24-dim probability vector over hours.

    Learning: simplified Baum-Welch (forward-backward) EM.
    When a prior model exists, its parameters seed the initial estimate
    so the model converges faster with less data.
    """
    if prior and "hmm_transition" in prior:
        transition = [list(row) for row in prior["hmm_transition"]]
        emission = [list(row) for row in prior["hmm_emission"]]
        initial = list(prior.get("hmm_initial", [0.6, 0.4]))
    else:
        transition = [[0.85, 0.15], [0.20, 0.80]]
        emission = _uniform_emission_init()
        initial = [0.6, 0.4]

    observations = _events_to_hour_sequence(events)

    if len(observations) >= 2:
        for _ in range(em_iterations):
            transition, emission, initial = _baum_welch_step(observations, transition, emission, initial)

    histogram = Counter(evt.astimezone(UTC).hour for evt in events)
    total = sum(histogram.values())
    hourly_histogram = {}
    if total > 0:
        for hour in range(24):
            active_prob = emission[1][hour]
            inactive_prob = emission[0][hour]
            combined = initial[1] * active_prob + initial[0] * inactive_prob
            if combined > 0:
                hourly_histogram[str(hour)] = combined

        hist_total = sum(hourly_histogram.values())
        if hist_total > 0:
            hourly_histogram = {k: v / hist_total for k, v in hourly_histogram.items()}

    return {
        "type": "hmm",
        "hourly_histogram": hourly_histogram,
        "sample_count": len(events),
        "hmm_states": ["inactive", "active"],
        "hmm_transition": transition,
        "hmm_emission": emission,
        "hmm_initial": initial,
    }


def merge_activity_models(local: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    """
    Merge two activity models by combining their histograms weighted
    by sample count, and carrying forward Kalman/HMM state if present.

    This is the core of brain-to-brain learning: the remote brain's
    learned activity patterns are fused with local observations.
    """
    local_count = local.get("sample_count", 0)
    remote_count = remote.get("sample_count", 0)
    total = local_count + remote_count

    if total == 0:
        return local

    local_weight = local_count / total
    remote_weight = remote_count / total

    local_hist = local.get("hourly_histogram", {})
    remote_hist = remote.get("hourly_histogram", {})

    all_hours = set(local_hist.keys()) | set(remote_hist.keys())
    merged_hist: dict[str, float] = {}
    for hour in all_hours:
        merged_hist[hour] = local_hist.get(hour, 0.0) * local_weight + remote_hist.get(hour, 0.0) * remote_weight

    hist_total = sum(merged_hist.values())
    if hist_total > 0:
        merged_hist = {k: v / hist_total for k, v in merged_hist.items()}

    result: dict[str, Any] = {
        "hourly_histogram": merged_hist,
        "sample_count": total,
        "type": local.get("type", remote.get("type", "histogram")),
        "merged_from": {
            "local_count": local_count,
            "remote_count": remote_count,
        },
    }

    if "kalman_state" in local and "kalman_state" in remote:
        result["kalman_state"] = [
            local["kalman_state"][i] * local_weight + remote["kalman_state"][i] * remote_weight for i in range(24)
        ]
        result["kalman_variance"] = [
            min(local.get("kalman_variance", [0.5] * 24)[i], remote.get("kalman_variance", [0.5] * 24)[i])
            for i in range(24)
        ]

    if "hmm_transition" in local and "hmm_transition" in remote:
        result["hmm_transition"] = [
            [
                local["hmm_transition"][i][j] * local_weight + remote["hmm_transition"][i][j] * remote_weight
                for j in range(2)
            ]
            for i in range(2)
        ]
        result["hmm_emission"] = [
            [
                local["hmm_emission"][s][h] * local_weight + remote["hmm_emission"][s][h] * remote_weight
                for h in range(24)
            ]
            for s in range(2)
        ]
        result["hmm_initial"] = [
            local.get("hmm_initial", [0.6, 0.4])[s] * local_weight
            + remote.get("hmm_initial", [0.6, 0.4])[s] * remote_weight
            for s in range(2)
        ]

    return result


def _uniform_emission_init() -> list[list[float]]:
    """Initial emission: inactive peaks at night, active peaks during day."""
    inactive = [0.0] * 24
    active = [0.0] * 24
    for h in range(24):
        if 0 <= h < 6 or h >= 22:
            inactive[h] = 0.08
            active[h] = 0.01
        elif 8 <= h < 20:
            inactive[h] = 0.02
            active[h] = 0.07
        else:
            inactive[h] = 0.04
            active[h] = 0.04

    inactive_total = sum(inactive)
    active_total = sum(active)
    return [
        [v / inactive_total for v in inactive],
        [v / active_total for v in active],
    ]


def _events_to_hour_sequence(events: list[datetime]) -> list[int]:
    """Convert events to a chronological sequence of hour observations."""
    sorted_events = sorted(events)
    return [evt.astimezone(UTC).hour for evt in sorted_events]


def _baum_welch_step(
    observations: list[int],
    transition: list[list[float]],
    emission: list[list[float]],
    initial: list[float],
) -> tuple[list[list[float]], list[list[float]], list[float]]:
    """Single EM iteration of Baum-Welch for 2-state HMM with 24-bin emissions."""
    n_states = 2
    n_obs = 24
    T = len(observations)
    if T < 2:
        return transition, emission, initial

    # Forward pass with scaling
    alpha = [[0.0] * n_states for _ in range(T)]
    for s in range(n_states):
        alpha[0][s] = initial[s] * emission[s][observations[0]]
    c = [0.0] * T
    c[0] = sum(alpha[0]) or 1e-300
    for s in range(n_states):
        alpha[0][s] /= c[0]

    for t in range(1, T):
        for j in range(n_states):
            alpha[t][j] = (
                sum(alpha[t - 1][i] * transition[i][j] for i in range(n_states)) * emission[j][observations[t]]
            )
        c[t] = sum(alpha[t]) or 1e-300
        for j in range(n_states):
            alpha[t][j] /= c[t]

    # Backward pass with same scaling
    beta = [[0.0] * n_states for _ in range(T)]
    for s in range(n_states):
        beta[T - 1][s] = 1.0

    for t in range(T - 2, -1, -1):
        for i in range(n_states):
            beta[t][i] = sum(
                transition[i][j] * emission[j][observations[t + 1]] * beta[t + 1][j] for j in range(n_states)
            )
        bt_sum = c[t + 1] or 1e-300
        for i in range(n_states):
            beta[t][i] /= bt_sum

    # Gamma: P(state=s at time t | observations)
    gamma = [[0.0] * n_states for _ in range(T)]
    for t in range(T):
        denom = sum(alpha[t][s] * beta[t][s] for s in range(n_states)) or 1e-300
        for s in range(n_states):
            gamma[t][s] = alpha[t][s] * beta[t][s] / denom

    # Xi: P(state=i at t and state=j at t+1 | observations)
    xi_sum = [[0.0] * n_states for _ in range(n_states)]
    for t in range(T - 1):
        denom = 0.0
        for i in range(n_states):
            for j in range(n_states):
                denom += alpha[t][i] * transition[i][j] * emission[j][observations[t + 1]] * beta[t + 1][j]
        denom = denom or 1e-300
        for i in range(n_states):
            for j in range(n_states):
                xi_sum[i][j] += (
                    alpha[t][i] * transition[i][j] * emission[j][observations[t + 1]] * beta[t + 1][j]
                ) / denom

    # Update initial
    new_initial = [gamma[0][s] for s in range(n_states)]
    init_total = sum(new_initial) or 1.0
    new_initial = [v / init_total for v in new_initial]

    # Update transition
    new_transition = [[0.0] * n_states for _ in range(n_states)]
    for i in range(n_states):
        gamma_sum_i = sum(gamma[t][i] for t in range(T - 1)) or 1e-300
        for j in range(n_states):
            new_transition[i][j] = xi_sum[i][j] / gamma_sum_i
        row_total = sum(new_transition[i]) or 1.0
        new_transition[i] = [v / row_total for v in new_transition[i]]

    # Update emission with Laplace smoothing
    smoothing = 1e-6
    new_emission = [[smoothing] * n_obs for _ in range(n_states)]
    for s in range(n_states):
        for t in range(T):
            new_emission[s][observations[t]] += gamma[t][s]
        row_total = sum(new_emission[s])
        new_emission[s] = [v / row_total for v in new_emission[s]]

    return new_transition, new_emission, new_initial
