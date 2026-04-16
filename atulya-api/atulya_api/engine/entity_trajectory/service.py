"""Orchestrate fetch → LLM → HMM → persist for one entity."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from typing import TYPE_CHECKING, Any

from atulya_api.engine.entity_trajectory import hmm
from atulya_api.engine.entity_trajectory.llm_labeler import _PROMPT_VERSION, label_trajectory_with_llm
from atulya_api.engine.entity_trajectory.models import TrajectoryViterbiStep
from atulya_api.engine.entity_trajectory.sequence import fetch_observations_for_entity, fetch_prior_vocabulary
from atulya_api.engine.memory_engine import fq_table

if TYPE_CHECKING:
    import asyncpg

    from atulya_api.engine.llm_wrapper import LLMConfig

logger = logging.getLogger(__name__)


def _anomaly_score_from_forward(forward_log: float, t: int, k: int) -> float:
    """Map log P(O|λ) to [0,1] where higher = more anomalous (lower likelihood)."""
    if t <= 0 or k <= 0:
        return 0.0
    scale = float(t * k)
    z = max(0.0, -forward_log / max(scale, 1.0))
    return max(0.0, min(1.0, 1.0 - math.exp(-z)))


class EntityTrajectoryService:
    """Compute and upsert entity_trajectories row."""

    @staticmethod
    async def compute_and_persist(
        conn: "asyncpg.Connection",
        *,
        bank_id: str,
        entity_id: str,
        entity_canonical_name: str,
        llm_config: "LLMConfig",
        resolved_config: Any,
        schema: str | None = None,
    ) -> bool:
        """
        Returns True if a row was written, False if skipped (too few facts or disabled upstream).
        """
        _ = schema  # reserved for logging
        if not getattr(resolved_config, "enable_entity_trajectories", False):
            return False

        max_facts = int(getattr(resolved_config, "entity_trajectory_max_facts_per_entity", 200))
        min_facts = int(getattr(resolved_config, "entity_trajectory_min_facts", 3))
        laplace = float(getattr(resolved_config, "entity_trajectory_laplace_alpha", 0.1))
        horizon = int(getattr(resolved_config, "entity_trajectory_forecast_horizon", 5))
        prompt_ver = str(getattr(resolved_config, "entity_trajectory_prompt_version", _PROMPT_VERSION))

        observations = await fetch_observations_for_entity(
            conn, bank_id=bank_id, entity_id=entity_id, max_facts=max_facts
        )
        if len(observations) < min_facts:
            logger.debug(
                "Skipping entity trajectory for %s / %s: %s facts < min %s",
                bank_id,
                entity_id,
                len(observations),
                min_facts,
            )
            return False

        prior = await fetch_prior_vocabulary(conn, bank_id=bank_id, entity_id=entity_id)
        llm_labels, model_name = await label_trajectory_with_llm(
            llm_config=llm_config,
            config=resolved_config,
            entity_name=entity_canonical_name,
            observations=observations,
            prior_vocabulary=prior,
        )

        labels = list(llm_labels.labels)
        vocab = list(llm_labels.state_vocabulary)
        used = set(labels)
        for u in used:
            if u not in vocab:
                vocab.append(u)

        k = len(vocab)
        if k < 2:
            vocab = ["STATE_A", "STATE_B"]
            labels = [vocab[0] if i % 2 == 0 else vocab[1] for i in range(len(observations))]
            k = 2

        vmap = {s: i for i, s in enumerate(vocab)}
        counts = hmm.build_counts_from_labels(labels, vmap)
        a_dense = hmm.laplace_row_stochastic(counts, laplace_alpha=laplace)
        log_a = hmm.log_row_matrix(a_dense)

        embs = [o.embedding for o in observations]
        centroids = hmm.centroids_from_labels(embs, labels, vocab)
        log_emit = hmm.emission_log_probs_cosine(embs, centroids)

        t_len = len(observations)
        log_trans = [log_a for _ in range(max(0, t_len - 1))]

        log_start = [math.log(1.0 / k)] * k

        path_idx, _vit_lp = hmm.viterbi(log_start, log_trans, log_emit)
        forward_lp = hmm.forward_log_probability(log_start, log_trans, log_emit)
        anomaly = _anomaly_score_from_forward(forward_lp, t_len, k)

        viterbi_steps: list[TrajectoryViterbiStep] = []
        for ti, st_i in enumerate(path_idx):
            st = vocab[st_i]
            obs = observations[ti]
            viterbi_steps.append(
                TrajectoryViterbiStep(
                    unit_id=obs.unit_id,
                    state=st,
                    occurred_sort_at=obs.occurred_sort_at,
                    fact_preview=obs.fact_text[:400],
                )
            )

        last_state_idx = path_idx[-1] if path_idx else 0
        fc_idx = hmm.forecast_distribution(a_dense, last_state_idx, horizon)
        forecast_dist = {vocab[j]: float(p) for j, p in fc_idx.items()}

        vocab_hash = hashlib.sha256(json.dumps(vocab, sort_keys=True).encode()).hexdigest()[:32]

        transition_json = json.dumps(a_dense)
        viterbi_json = json.dumps([s.model_dump(mode="json") for s in viterbi_steps])
        forecast_json = json.dumps(forecast_dist)
        vocab_json = json.dumps(vocab)

        current_state = vocab[last_state_idx]

        await conn.execute(
            f"""
            INSERT INTO {fq_table("entity_trajectories")}
              (bank_id, entity_id, state_vocabulary, vocabulary_hash, transition_matrix,
               current_state, viterbi_path, forecast_horizon, forecast_distribution,
               forward_log_prob, anomaly_score, llm_model, prompt_version, computed_at)
            VALUES ($1, $2::uuid, $3::jsonb, $4, $5::jsonb, $6, $7::jsonb, $8, $9::jsonb, $10, $11, $12, $13, now())
            ON CONFLICT (bank_id, entity_id) DO UPDATE SET
              computed_at = now(),
              state_vocabulary = EXCLUDED.state_vocabulary,
              vocabulary_hash = EXCLUDED.vocabulary_hash,
              transition_matrix = EXCLUDED.transition_matrix,
              current_state = EXCLUDED.current_state,
              viterbi_path = EXCLUDED.viterbi_path,
              forecast_horizon = EXCLUDED.forecast_horizon,
              forecast_distribution = EXCLUDED.forecast_distribution,
              forward_log_prob = EXCLUDED.forward_log_prob,
              anomaly_score = EXCLUDED.anomaly_score,
              llm_model = EXCLUDED.llm_model,
              prompt_version = EXCLUDED.prompt_version
            """,
            bank_id,
            entity_id,
            vocab_json,
            vocab_hash,
            transition_json,
            current_state,
            viterbi_json,
            horizon,
            forecast_json,
            forward_lp,
            anomaly,
            model_name[:500],
            prompt_ver,
        )
        return True
