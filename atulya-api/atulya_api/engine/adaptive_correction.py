"""
Adaptive correction actions for anomaly events.

Purpose
    Apply automatic, in-transaction remediations for open anomaly events
    immediately after detection during retain. Currently handles high-severity
    contradictions (confidence reduction) and causal flaws (suggestions only).

Trigger path
    - ``engine/retain/orchestrator.retain_batch`` after ``persist_anomalies``,
      passing new event IDs into ``apply_adaptive_corrections`` on the same conn.

Inputs
    - Open asyncpg ``conn``, ``bank_id``, list of ``anomaly_event_ids``.

Outputs
    - Count of corrections applied (inserts + status updates).

Side effects
    - UPDATE ``memory_units.confidence_score`` for contradiction auto-fix.
    - INSERT into ``anomaly_corrections`` audit table.
    - UPDATE ``anomaly_events.status`` to ``resolved`` or ``acknowledged``.

Mutability
    - Only ``unit_ids[0]`` is adjusted for contradictions (first unit in event).
    - Causal flaw types do not mutate memory — suggestion JSON only.

Impact radius
    - Recall ranking via confidence_score changes.
    - Operator views of anomaly resolution state.

Core logic
    - ``contradiction`` with severity >= 0.7: multiply confidence by
      ``(1 - severity * adaptive_alpha(severity))``, clamped [0, 1].
    - ``flaw_missing_step`` / ``flaw_temporal_violation``: insert
      ``chain_repair_suggestion`` and mark acknowledged.

Failure modes
    - Empty ID list returns 0 without queries.
    - Only processes rows with ``status = 'open'``.

Maintenance notes
    - Good: add a new branch with matching ``CorrectionType`` and audit row.
    - Bad: auto-delete memories or links without explicit product approval.
    - ``_adaptive_alpha`` increases adjustment aggressiveness above severity 0.5.
"""

from __future__ import annotations

import json

from atulya_api.engine.memory_engine import fq_table


def _adaptive_alpha(score: float, alpha_base: float = 0.35) -> float:
    """Scale correction strength; higher severity → slightly larger alpha."""
    return alpha_base * (1.0 + 0.2 * (score - 0.5))


async def apply_adaptive_corrections(
    conn,
    *,
    bank_id: str,
    anomaly_event_ids: list[str],
) -> int:
    """
    Apply in-transaction correction updates for high-severity open anomalies.

    Returns the number of anomalies that received a correction action.
    """
    if not anomaly_event_ids:
        return 0

    rows = await conn.fetch(
        f"""
        SELECT id, anomaly_type, severity, unit_ids
        FROM {fq_table("anomaly_events")}
        WHERE bank_id = $1
          AND id = ANY($2::uuid[])
          AND status = 'open'
        """,
        bank_id,
        anomaly_event_ids,
    )

    correction_count = 0
    for row in rows:
        anomaly_id = str(row["id"])
        anomaly_type = str(row["anomaly_type"])
        severity = float(row["severity"] or 0.0)
        unit_ids = [str(unit_id) for unit_id in (row["unit_ids"] or [])]

        if anomaly_type == "contradiction" and severity >= 0.7 and unit_ids:
            target_unit_id = unit_ids[0]
            current_confidence = await conn.fetchval(
                f"SELECT confidence_score FROM {fq_table('memory_units')} WHERE id = $1::uuid",
                target_unit_id,
            )
            old_conf = float(current_confidence if current_confidence is not None else 1.0)
            new_conf = max(0.0, min(1.0, old_conf * (1.0 - severity * _adaptive_alpha(severity))))

            await conn.execute(
                f"UPDATE {fq_table('memory_units')} SET confidence_score = $1 WHERE id = $2::uuid",
                new_conf,
                target_unit_id,
            )
            await conn.execute(
                f"""
                INSERT INTO {fq_table("anomaly_corrections")}
                (bank_id, anomaly_id, correction_type, target_unit_id, before_state, after_state, confidence_delta, applied_by)
                VALUES ($1, $2::uuid, 'confidence_adjustment', $3::uuid, $4::jsonb, $5::jsonb, $6, 'auto')
                """,
                bank_id,
                anomaly_id,
                target_unit_id,
                json.dumps({"confidence_score": old_conf}),
                json.dumps({"confidence_score": new_conf}),
                new_conf - old_conf,
            )
            await conn.execute(
                f"""
                UPDATE {fq_table("anomaly_events")}
                SET status = 'resolved', resolved_at = now(), resolved_by = 'auto'
                WHERE id = $1::uuid
                """,
                anomaly_id,
            )
            correction_count += 1
            continue

        if anomaly_type in {"flaw_missing_step", "flaw_temporal_violation"}:
            await conn.execute(
                f"""
                INSERT INTO {fq_table("anomaly_corrections")}
                (bank_id, anomaly_id, correction_type, before_state, after_state, applied_by)
                VALUES ($1, $2::uuid, 'chain_repair_suggestion', '{{}}'::jsonb, $3::jsonb, 'auto')
                """,
                bank_id,
                anomaly_id,
                json.dumps({"suggestion": "Add intermediary evidence or adjust causal ordering."}),
            )
            await conn.execute(
                f"""
                UPDATE {fq_table("anomaly_events")}
                SET status = 'acknowledged'
                WHERE id = $1::uuid
                """,
                anomaly_id,
            )
            correction_count += 1

    return correction_count
