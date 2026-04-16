"""Small discrete HMM utilities: Laplace-smoothed transitions, Viterbi, Forward, A^h."""

from __future__ import annotations

import math
from typing import Sequence


def _log_sum_exp(logits: Sequence[float]) -> float:
    if not logits:
        return float("-inf")
    m = max(logits)
    if m == float("-inf"):
        return float("-inf")
    s = sum(math.exp(x - m) for x in logits)
    return m + math.log(s)


def laplace_row_stochastic(
    transition_counts: list[list[int]],
    *,
    laplace_alpha: float,
) -> list[list[float]]:
    """Convert count matrix to row-stochastic A with additive smoothing."""
    k = len(transition_counts)
    if k == 0:
        return []
    denom = laplace_alpha * k
    out: list[list[float]] = []
    for i in range(k):
        row_sum = sum(transition_counts[i]) + denom
        out.append([(transition_counts[i][j] + laplace_alpha) / row_sum for j in range(k)])
    return out


def build_counts_from_labels(labels: Sequence[str], vocab_index: dict[str, int]) -> list[list[int]]:
    k = len(vocab_index)
    counts = [[0] * k for _ in range(k)]
    for a, b in zip(labels, labels[1:], strict=False):
        ia = vocab_index.get(a)
        ib = vocab_index.get(b)
        if ia is None or ib is None:
            continue
        counts[ia][ib] += 1
    return counts


def viterbi(
    log_start: Sequence[float],
    log_trans: Sequence[Sequence[Sequence[float]]],
    log_emit: Sequence[Sequence[float]],
) -> tuple[list[int], float]:
    """
    Viterbi decoding.

    Args:
        log_start: log pi, shape K
        log_trans: log A, shape (T-1) x K x K — log_trans[t][i][j] = log P(j | i) from t to t+1
        log_emit: log B, shape T x K — emission log prob per (time, state)
    """
    t = len(log_emit)
    k = len(log_start)
    if t == 0 or k == 0:
        return [], float("-inf")
    dp = [[float("-inf")] * k for _ in range(t)]
    back = [[0] * k for _ in range(t)]
    for j in range(k):
        dp[0][j] = log_start[j] + log_emit[0][j]
    for ti in range(1, t):
        for j in range(k):
            best = float("-inf")
            best_i = 0
            for i in range(k):
                tr = log_trans[ti - 1][i][j] if ti - 1 < len(log_trans) else float("-inf")
                val = dp[ti - 1][i] + tr + log_emit[ti][j]
                if val > best:
                    best = val
                    best_i = i
            dp[ti][j] = best
            back[ti][j] = best_i
    last_j = max(range(k), key=lambda j: dp[t - 1][j])
    log_prob = dp[t - 1][last_j]
    path_rev: list[int] = [last_j]
    for ti in range(t - 1, 0, -1):
        last_j = back[ti][last_j]
        path_rev.append(last_j)
    path_rev.reverse()
    return path_rev, log_prob


def forward_log_probability(
    log_start: Sequence[float],
    log_trans: Sequence[Sequence[Sequence[float]]],
    log_emit: Sequence[Sequence[float]],
) -> float:
    """Log P(observations | model) using forward algorithm."""
    t = len(log_emit)
    k = len(log_start)
    if t == 0 or k == 0:
        return float("-inf")
    alpha = [log_start[j] + log_emit[0][j] for j in range(k)]
    for ti in range(1, t):
        new_alpha: list[float] = []
        for j in range(k):
            terms = []
            for i in range(k):
                tr = log_trans[ti - 1][i][j] if ti - 1 < len(log_trans) else float("-inf")
                terms.append(alpha[i] + tr + log_emit[ti][j])
            new_alpha.append(_log_sum_exp(terms))
        alpha = new_alpha
    return _log_sum_exp(alpha)


def matrix_power_row_stochastic(a: Sequence[Sequence[float]], power: int) -> list[list[float]]:
    """Return A^power for row-stochastic A (small K), power >= 0."""

    def mat_mul(x: list[list[float]], y: list[list[float]]) -> list[list[float]]:
        z = [[0.0] * k for _ in range(k)]
        for i in range(k):
            for j in range(k):
                z[i][j] = sum(x[i][r] * y[r][j] for r in range(k))
        return z

    k = len(a)
    if k == 0:
        return []
    ident = [[1.0 if i == j else 0.0 for j in range(k)] for i in range(k)]
    if power <= 0:
        return ident

    base = [[float(a[i][j]) for j in range(k)] for i in range(k)]
    res = ident
    n = power
    while n > 0:
        if n & 1:
            res = mat_mul(res, base)
        base = mat_mul(base, base)
        n >>= 1
    return res


def forecast_distribution(
    a: Sequence[Sequence[float]],
    initial_state_index: int,
    horizon: int,
) -> dict[int, float]:
    """Exact marginal over states after `horizon` steps: pi = e_{initial}^T A^h."""
    k = len(a)
    if k == 0 or horizon < 1:
        return {}
    ap = matrix_power_row_stochastic(a, horizon)
    row = ap[initial_state_index]
    return {j: row[j] for j in range(k)}


def emission_log_probs_cosine(
    observation_embeddings: Sequence[Sequence[float]],
    centroids: Sequence[Sequence[float]],
    *,
    eps: float = 1e-6,
) -> list[list[float]]:
    """
    Per (t, state): log softmax over cosines between observation_t and each centroid.
    """
    t_len = len(observation_embeddings)
    k = len(centroids)
    out: list[list[float]] = []
    for t in range(t_len):
        o = observation_embeddings[t]
        cos_vals: list[float] = []
        for s in range(k):
            c = centroids[s]
            dot = sum(ox * cx for ox, cx in zip(o, c, strict=False))
            no = math.sqrt(sum(x * x for x in o)) + eps
            nc = math.sqrt(sum(x * x for x in c)) + eps
            cos_vals.append(max(dot / (no * nc), eps))
        log_cos = [math.log(v) for v in cos_vals]
        lse = _log_sum_exp(log_cos)
        out.append([lc - lse for lc in log_cos])
    return out


def centroids_from_labels(
    observation_embeddings: Sequence[Sequence[float]],
    labels: Sequence[str],
    vocab: Sequence[str],
) -> list[list[float]]:
    """Mean embedding per vocabulary state (zero vector if no points)."""
    dim = len(observation_embeddings[0]) if observation_embeddings else 0
    k = len(vocab)
    sums = [[0.0] * dim for _ in range(k)]
    counts = [0] * k
    vmap = {s: i for i, s in enumerate(vocab)}
    for emb, lab in zip(observation_embeddings, labels, strict=False):
        idx = vmap.get(lab)
        if idx is None:
            continue
        counts[idx] += 1
        for d in range(dim):
            sums[idx][d] += emb[d]
    out: list[list[float]] = []
    for i in range(k):
        if counts[i] == 0:
            out.append([0.0] * dim)
        else:
            out.append([sums[i][d] / counts[i] for d in range(dim)])
    return out


def log_row_matrix(a: Sequence[Sequence[float]]) -> list[list[float]]:
    return [[math.log(max(x, 1e-300)) for x in row] for row in a]
