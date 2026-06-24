"""Quality audit for Atulya Training Records."""

from __future__ import annotations

from datetime import datetime

from .models import AtulyaTrainingRecord, QualityScore


def _ids_in_record(record: AtulyaTrainingRecord) -> set[str]:
    ids: set[str] = set()
    for fact in record.facts:
        ids.add(fact.id)
    for obs in record.observations:
        ids.add(obs.id)
    return ids


def _temporal_coherent(record: AtulyaTrainingRecord) -> tuple[bool, list[str]]:
    if record.query_anchor is None:
        return True, []
    anchor = record.query_anchor
    issues: list[str] = []
    bounds: list[datetime] = []
    for fact in record.facts:
        for ts in (fact.occurred_start, fact.mentioned_at):
            if ts:
                bounds.append(ts)
    if not bounds:
        return True, issues
    min_ts = min(bounds)
    max_ts = max(bounds)
    if anchor < min_ts:
        issues.append("query_anchor precedes earliest fact timestamp")
    if anchor > max_ts:
        # query after all facts is valid for temporal reasoning
        pass
    return len(issues) == 0, issues


def _provenance_complete(record: AtulyaTrainingRecord) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if record.labels.answer or record.labels.gold_answer:
        if record.recipe_id in {"temporal_qa", "agent_trace"}:
            if not record.labels.cited_memory_ids:
                issues.append("answer present without memory citations")
        elif not record.labels.cited_memory_ids and not record.labels.cited_observation_ids:
            issues.append("answer present without citations")
    for obs in record.observations:
        if obs.proof_count > 0 and not obs.source_memory_ids:
            issues.append(f"observation {obs.id} missing source_memory_ids")
    if record.provenance.document_ids or record.provenance.chunk_ids or record.facts:
        return len(issues) == 0, issues
    issues.append("no provenance anchors")
    return False, issues


def _citation_valid(record: AtulyaTrainingRecord) -> tuple[bool, list[str]]:
    valid_ids = _ids_in_record(record)
    issues: list[str] = []
    for mid in record.labels.cited_memory_ids:
        if mid not in valid_ids:
            issues.append(f"cited memory {mid} not in record facts/observations")
    for oid in record.labels.cited_observation_ids:
        if oid not in valid_ids:
            issues.append(f"cited observation {oid} not in record")
    return len(issues) == 0, issues


def _contradiction_unresolved(record: AtulyaTrainingRecord) -> bool:
    if not record.graph:
        return False
    contradictory = [n for n in record.graph.nodes if n.status == "contradictory"]
    if not contradictory:
        return False
    if record.recipe_id == "belief_update" and record.labels.belief_update:
        return False
    return True


def audit_record(record: AtulyaTrainingRecord, *, threshold: float = 0.6) -> AtulyaTrainingRecord:
    """Score and annotate a single ATR record."""
    issues: list[str] = []

    if not record.facts and not record.observations and not record.labels.answer and not record.graph:
        issues.append("record has no facts, observations, labels, or graph content")

    prov_ok, prov_issues = _provenance_complete(record)
    issues.extend(prov_issues)
    temp_ok, temp_issues = _temporal_coherent(record)
    issues.extend(temp_issues)
    cite_ok, cite_issues = _citation_valid(record)
    issues.extend(cite_issues)
    contradiction = _contradiction_unresolved(record)
    if contradiction:
        issues.append("unresolved contradictory graph nodes")

    score = 1.0
    if not prov_ok:
        score -= 0.25
    if not temp_ok:
        score -= 0.2
    if not cite_ok:
        score -= 0.25
    if contradiction:
        score -= 0.15

    score = max(0.0, min(1.0, score))
    exportable = score >= threshold and prov_ok and cite_ok and not contradiction

    record.quality = QualityScore(
        overall=score,
        provenance_complete=prov_ok,
        temporal_coherent=temp_ok,
        citation_valid=cite_ok,
        contradiction_unresolved=contradiction,
        judge_score=None,
        exportable=exportable,
        issues=issues,
    )
    return record


def summarize_quality(records: list[AtulyaTrainingRecord]) -> dict[str, float | int]:
    if not records:
        return {
            "total": 0,
            "exportable": 0,
            "held_back": 0,
            "pass_rate": 0.0,
            "avg_score": 0.0,
            "issue_counts": {},
        }
    exportable = sum(1 for r in records if r.quality.exportable)
    avg = sum(r.quality.overall for r in records) / len(records)
    issue_counts: dict[str, int] = {}
    for record in records:
        for issue in record.quality.issues:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
    return {
        "total": len(records),
        "exportable": exportable,
        "held_back": len(records) - exportable,
        "pass_rate": exportable / len(records),
        "avg_score": avg,
        "issue_counts": issue_counts,
    }
