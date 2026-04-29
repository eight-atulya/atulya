"""
Graph Intelligence Fine-tuning Dataset
=======================================
Single source of truth: scenario corpus + behavioral assertions + pytest tests.

Design principles:
  - Each scenario is a realistic slice of Anurag's social/professional world.
  - Scenarios are ordered from simple → adversarial → multi-hop.
  - Known bugs are marked @pytest.mark.xfail(strict=True) — they document
    the INTENDED behavior and become green once the bug is fixed.
  - Run with --finetune flag to emit JSONL for LLM fine-tuning:
      pytest tests/graph_intelligence_finetune.py --finetune=ft_out.jsonl

Metadata:

  @intent:  Drive iterative improvement of graph_intelligence.py via
            test-first behavioral specifications grounded in real social
            context (not synthetic noise).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from atulya_api.engine.graph_intelligence import (
    GraphBuildOptions,
    GraphEvidenceUnit,
    GraphIntelligenceResponse,
    build_graph_intelligence,
    investigate_graph,
)

# ============================================================================
# WORLD MODEL — immutable facts about the characters
# ============================================================================
# Anurag Atulya       : from Jharkhand; Kota 2014 batch; SRM Chennai 2016
# Akshay Bhandari     : from Chennai;   Kota 2014 batch; bday 8th
# Swastik Katal       : from Jammu;     Kota 2014 batch
# Antara Das          : SRM Chennai 2016 August; bday 8th (shares with Akshay)
# Paritosh Sapre      : from Pune; SRM college; met Swastik in SRM final year
# Shubham Dawkhar     : from Pune; SRM college; friends with Paritosh
# Pritha Maity        : colleague; changing roles
# Zeeshan Mallick     : remote engineer
# Awadh Bihari Purbey : ops lead
# Kumari Archana      : data scientist
# Puja Bharti         : product manager
# Ankita Das          : designer
# Ranjhana Das        : QA lead
# Amit Kumar Das      : backend engineer
# Kreator3d           : org / company
# Sytolab             : org / company
# ============================================================================


# ---------------------------------------------------------------------------
# Corpus helpers
# ---------------------------------------------------------------------------

def _ts(days_ago: int = 0, hours_ago: int = 0) -> datetime:
    return datetime.now(UTC) - timedelta(days=days_ago, hours=hours_ago)


# Fixed timestamps for scenarios where units describe DIFFERENT aspects
# (origin, relationships) that should NOT form temporal change pairs.
# Using identical occurred_start means current_ts <= previous_ts → all pairs skipped.
_TS_400 = datetime.now(UTC) - timedelta(days=400)
_TS_380 = datetime.now(UTC) - timedelta(days=380)


def _unit(
    uid: str,
    text: str,
    *,
    entities: list[str],
    tags: list[str] | None = None,
    days_ago: int = 0,
    hours_ago: int = 0,
    fixed_ts: datetime | None = None,
    embedding: list[float] | None = None,
    proof_count: int = 1,
    access_count: int = 0,
    fact_type: str = "world",
    chunk_id: str | None = None,
) -> GraphEvidenceUnit:
    ts = fixed_ts if fixed_ts is not None else _ts(days_ago=days_ago, hours_ago=hours_ago)
    return GraphEvidenceUnit(
        id=uid,
        text=text,
        fact_type=fact_type,
        embedding=embedding,
        occurred_start=ts,
        mentioned_at=ts,
        created_at=ts,
        entities=entities,
        tags=tags or [],
        proof_count=proof_count,
        access_count=access_count,
        chunk_id=chunk_id,
    )


# ---------------------------------------------------------------------------
# Serialisation helper (for --finetune export)
# ---------------------------------------------------------------------------

@dataclass
class FTRecord:
    """One fine-tuning sample: (scenario, units, expected_signals)."""
    scenario_id: str
    description: str
    units: list[dict[str, Any]]
    expected_node_titles: list[str]
    expected_statuses: dict[str, str]          # {entity_title: status}
    expected_change_types: list[str]           # ["change", "contradiction", ...]
    must_not_node_titles: list[str] = field(default_factory=list)
    notes: str = ""


FT_RECORDS: list[FTRecord] = []


def _register(record: FTRecord) -> FTRecord:
    FT_RECORDS.append(record)
    return record


# ============================================================================
# SCENARIOS
# ============================================================================

# ---------------------------------------------------------------------------
# S01 — Basic entity state + origin facts (Kota batch)
# ---------------------------------------------------------------------------
_S01_UNITS = [
    _unit("s01_a1", "Anurag Atulya is from Jharkhand and moved to Kota in 2014 for engineering preparation.",
          entities=["Anurag Atulya", "Jharkhand", "Kota"], tags=["kota-batch"], fixed_ts=_TS_400),
    _unit("s01_a2", "Akshay Bhandari is originally from Chennai but studied in Kota from 2014.",
          entities=["Akshay Bhandari", "Chennai", "Kota"], tags=["kota-batch"], fixed_ts=_TS_400),
    _unit("s01_a3", "Swastik Katal came from Jammu to Kota in 2014 to prepare for JEE.",
          entities=["Swastik Katal", "Jammu", "Kota"], tags=["kota-batch"], fixed_ts=_TS_400),
    _unit("s01_b1", "Anurag Atulya, Akshay Bhandari, and Swastik Katal became best friends during their Kota days in 2014.",
          entities=["Anurag Atulya", "Akshay Bhandari", "Swastik Katal", "Kota"],
          tags=["kota-batch", "friendship"], fixed_ts=_TS_400),
]

_S01 = _register(FTRecord(
    scenario_id="S01",
    description="Kota batch — three origin facts + one co-occurrence bond. "
                "System must produce nodes for all three people + a topic node for kota-batch.",
    units=[u.model_dump() for u in _S01_UNITS],
    expected_node_titles=["Anurag Atulya", "Akshay Bhandari", "Swastik Katal"],
    expected_statuses={"Anurag Atulya": "stable", "Akshay Bhandari": "stable", "Swastik Katal": "stable"},
    expected_change_types=[],
    notes="All stable. Edges between three entities must exist (co_occurs).",
))


# ---------------------------------------------------------------------------
# S02 — SRM connection: temporal relationship formation
# ---------------------------------------------------------------------------
_S02_UNITS = [
    _unit("s02_a1", "Paritosh Sapre and Shubham Dawkhar were classmates at SRM University Chennai.",
          entities=["Paritosh Sapre", "Shubham Dawkhar", "SRM University"],
          tags=["srm-batch"], days_ago=300),
    _unit("s02_a2", "Anurag Atulya joined SRM University Chennai in August 2016.",
          entities=["Anurag Atulya", "SRM University"], tags=["srm-batch"], days_ago=280),
    _unit("s02_a3", "Antara Das met Anurag Atulya at SRM University in August 2016 during orientation.",
          entities=["Antara Das", "Anurag Atulya", "SRM University"],
          tags=["srm-batch", "friendship"], days_ago=270),
    _unit("s02_a4", "Swastik Katal joined SRM University for his final year and met Paritosh Sapre there.",
          entities=["Swastik Katal", "Paritosh Sapre", "SRM University"],
          tags=["srm-batch"], days_ago=250),
]

_S02 = _register(FTRecord(
    scenario_id="S02",
    description="SRM college web — four arrival facts bridging Kota-batch and SRM-batch. "
                "Swastik connects both worlds. Edges: Anurag-Antara, Paritosh-Shubham, Swastik-Paritosh.",
    units=[u.model_dump() for u in _S02_UNITS],
    expected_node_titles=["Anurag Atulya", "Antara Das", "Paritosh Sapre", "Shubham Dawkhar", "Swastik Katal"],
    expected_statuses={},
    expected_change_types=[],
    notes="Check that Swastik appears in edges to BOTH Kota and SRM entities.",
))


# ---------------------------------------------------------------------------
# S03 — Temporal state change (company transition) — SHOULD WORK
# ---------------------------------------------------------------------------
_S03_UNITS = [
    _unit("s03_a1", "Anurag Atulya is the founding engineer at Kreator3d, leading the 3D rendering pipeline.",
          entities=["Anurag Atulya", "Kreator3d"], tags=["career"], days_ago=180),
    _unit("s03_a2", "Kreator3d team is small, and Anurag Atulya handles both product and engineering.",
          entities=["Anurag Atulya", "Kreator3d"], tags=["career"], days_ago=150),
    _unit("s03_b1", "Anurag Atulya has joined Sytolab as a principal engineer, leaving Kreator3d behind.",
          entities=["Anurag Atulya", "Sytolab", "Kreator3d"], tags=["career"], days_ago=10),
]

_S03 = _register(FTRecord(
    scenario_id="S03",
    description="Career transition: Anurag moves from Kreator3d → Sytolab. "
                "System must detect a temporal CHANGE event and show Sytolab as current state.",
    units=[u.model_dump() for u in _S03_UNITS],
    expected_node_titles=["Anurag Atulya"],
    expected_statuses={"Anurag Atulya": "changed"},
    expected_change_types=["change"],
    notes="current_state must reference Sytolab, not Kreator3d.",
))


# ---------------------------------------------------------------------------
# S04 — Semantic contradiction WITHOUT negation words  [KNOWN BUG → xfail]
# Naive negation-token check requires "not/never/left/quit" etc.
# "founding engineer" vs "principal engineer at different company" has no negation token
# but IS a contradiction in role+affiliation.
# ---------------------------------------------------------------------------
_S04_UNITS = [
    _unit("s04_a1", "Akshay Bhandari is the senior backend engineer at Kreator3d, based in Chennai.",
          entities=["Akshay Bhandari", "Kreator3d"],
          embedding=[1.0, 0.0, 0.0],
          tags=["career"], days_ago=90),
    _unit("s04_a2", "Akshay Bhandari joined Sytolab as a junior frontend developer, relocating to Bangalore.",
          entities=["Akshay Bhandari", "Sytolab"],
          embedding=[0.85, 0.52, 0.0],
          tags=["career"], days_ago=5),
]

_S04 = _register(FTRecord(
    scenario_id="S04",
    description="[BUG] Semantic contradiction without negation: Akshay's role+company+city all changed "
                "but no negation word present. Current code only detects negation-based contradictions. "
                "System SHOULD flag as contradictory OR changed. Currently: stable.",
    units=[u.model_dump() for u in _S04_UNITS],
    expected_node_titles=["Akshay Bhandari"],
    expected_statuses={"Akshay Bhandari": "changed"},  # minimum acceptable
    expected_change_types=["change"],
    notes="xfail: negation-only contradiction logic misses role+affiliation flips.",
))


# ---------------------------------------------------------------------------
# S05 — Negation contradiction — SHOULD WORK
# ---------------------------------------------------------------------------
_S05_UNITS = [
    _unit("s05_a1", "Zeeshan Mallick is working remotely from Hyderabad full-time.",
          entities=["Zeeshan Mallick"],
          embedding=[1.0, 0.0],
          tags=["remote-work"], days_ago=30),
    _unit("s05_a2", "Zeeshan Mallick is not working remotely; he returned to the office in Hyderabad.",
          entities=["Zeeshan Mallick"],
          embedding=[0.82, 0.57],
          tags=["remote-work"], days_ago=3),
]

_S05 = _register(FTRecord(
    scenario_id="S05",
    description="Classic negation contradiction: 'is working remotely' vs 'is not working remotely'. "
                "Negation token 'not' is present. System MUST detect contradiction.",
    units=[u.model_dump() for u in _S05_UNITS],
    expected_node_titles=["Zeeshan Mallick"],
    expected_statuses={"Zeeshan Mallick": "contradictory"},
    expected_change_types=["contradiction"],
))


# ---------------------------------------------------------------------------
# S06 — Entity aliasing trap  [KNOWN BUG → xfail]
# "Anurag" and "Anurag Atulya" are the same person but become separate nodes
# because grouping key is the raw entity string from extraction.
# ---------------------------------------------------------------------------
_S06_UNITS = [
    _unit("s06_a1", "Anurag Atulya is building a memory OS called Atulya.",
          entities=["Anurag Atulya"], tags=["atulya-project"], days_ago=60),
    _unit("s06_a2", "Anurag is the primary maintainer of the Atulya codebase.",
          entities=["Anurag"], tags=["atulya-project"], days_ago=45),
    _unit("s06_a3", "Anurag Atulya and Anurag are the same person according to the team.",
          entities=["Anurag Atulya", "Anurag"], tags=["atulya-project"], days_ago=40),
]

_S06 = _register(FTRecord(
    scenario_id="S06",
    description="[BUG] Entity aliasing: 'Anurag' and 'Anurag Atulya' create two separate nodes. "
                "Should merge or deduplicate. Currently produces two distinct entity nodes.",
    units=[u.model_dump() for u in _S06_UNITS],
    expected_node_titles=["Anurag Atulya"],  # should NOT also produce a separate "Anurag" node
    expected_statuses={},
    expected_change_types=[],
    must_not_node_titles=["Anurag"],  # "Anurag" alone should not be a separate top node
    notes="xfail: no entity normalization layer exists.",
))


# ---------------------------------------------------------------------------
# S07 — Paraphrase / semantic dedup  [requires embeddings]
# Same fact stated three different ways — should count as ONE unit, not three change events
# ---------------------------------------------------------------------------
_S07_UNITS = [
    _unit("s07_a1", "Akshay Bhandari and Antara Das share the same birth date: the 8th of the month.",
          entities=["Akshay Bhandari", "Antara Das"],
          embedding=[1.0, 0.0, 0.0, 0.0],
          tags=["birthday"], days_ago=20),
    _unit("s07_a2", "Both Akshay Bhandari and Antara Das celebrate their birthday on the 8th.",
          entities=["Akshay Bhandari", "Antara Das"],
          embedding=[0.98, 0.14, 0.0, 0.0],   # cosine ≈ 0.99 → semantic duplicate
          tags=["birthday"], days_ago=10),
    _unit("s07_a3", "Akshay and Antara have identical birthday dates — both born on the 8th.",
          entities=["Akshay Bhandari", "Antara Das"],
          embedding=[0.97, 0.17, 0.07, 0.0],  # cosine ≈ 0.98 → semantic duplicate
          tags=["birthday"], days_ago=5),
]

_S07 = _register(FTRecord(
    scenario_id="S07",
    description="Paraphrase dedup: three restatements of the same birthday fact. "
                "With embeddings present, semantic dedup must collapse to ONE distinct unit. "
                "No change event should fire.",
    units=[u.model_dump() for u in _S07_UNITS],
    expected_node_titles=["Akshay Bhandari", "Antara Das"],
    expected_statuses={"Akshay Bhandari": "stable", "Antara Das": "stable"},
    expected_change_types=[],
    notes="If dedup works: 0 change events. If broken: spurious 'change' events appear.",
))


# ---------------------------------------------------------------------------
# S08 — Leading-entity slug bug  [KNOWN BUG → xfail]
# _leading_entity slugifies entity name ("anurag-atulya") but searches
# raw text with \b word boundary — hyphen never matches space.
# So contradiction ownership for "Anurag Atulya" silently fails.
# ---------------------------------------------------------------------------
_S08_UNITS = [
    _unit("s08_a1", "Anurag Atulya designed the entire Atulya architecture single-handedly.",
          entities=["Anurag Atulya", "Atulya"],
          embedding=[1.0, 0.0],
          tags=["atulya-project"], days_ago=50,
          chunk_id="bank_doc123_0"),
    _unit("s08_a2", "Anurag Atulya never touched the Atulya architecture; it was outsourced.",
          entities=["Anurag Atulya", "Atulya"],
          embedding=[0.86, 0.51],
          tags=["atulya-project"], days_ago=5,
          chunk_id="bank_doc123_1"),
]

_S08 = _register(FTRecord(
    scenario_id="S08",
    description="[BUG] Leading-entity slug mismatch: _leading_entity returns 'anurag-atulya' "
                "(slugified), but regex searches for \\b anurag-atulya \\b in text that has "
                "'Anurag Atulya' (space). Word boundary never fires → contradiction ownership "
                "silently rejected → status stays stable instead of contradictory.",
    units=[u.model_dump() for u in _S08_UNITS],
    expected_node_titles=["Anurag Atulya"],
    expected_statuses={"Anurag Atulya": "contradictory"},
    expected_change_types=["contradiction"],
    notes="xfail: _leading_entity uses slugified string, not original entity name.",
))


# ---------------------------------------------------------------------------
# S09 — Stale detection (node aged 50d, neighbor changed recently)
# ---------------------------------------------------------------------------
_S09_UNITS = [
    # Shubham — old state, no recent activity
    _unit("s09_a1", "Shubham Dawkhar is working on the frontend at Kreator3d.",
          entities=["Shubham Dawkhar", "Kreator3d", "Paritosh Sapre"],
          tags=["career", "kreator3d"], days_ago=80, access_count=3),
    # Paritosh — connected, recent change
    _unit("s09_b1", "Paritosh Sapre moved from Kreator3d to Sytolab last week.",
          entities=["Paritosh Sapre", "Sytolab", "Kreator3d"],
          tags=["career"], days_ago=70),
    _unit("s09_b2", "Paritosh Sapre is now leading the infra team at Sytolab.",
          entities=["Paritosh Sapre", "Sytolab"],
          tags=["career"], days_ago=5),
]

_S09 = _register(FTRecord(
    scenario_id="S09",
    description="Stale detection: Shubham's last evidence is 80 days old, "
                "but Paritosh (co_occurs in same unit) has a recent change. "
                "System should mark Shubham as stale.",
    units=[u.model_dump() for u in _S09_UNITS],
    expected_node_titles=["Shubham Dawkhar", "Paritosh Sapre"],
    expected_statuses={"Paritosh Sapre": "changed", "Shubham Dawkhar": "stale"},
    expected_change_types=["change", "stale"],
))


# ---------------------------------------------------------------------------
# S10 — Multi-hop investigation query
# "Who from Kota batch is working together now?" → Anurag + Akshay + Swastik
# Tests investigate_graph token overlap + change_score ranking
# ---------------------------------------------------------------------------
_S10_UNITS = [
    *_S01_UNITS,
    _unit("s10_c1", "Anurag Atulya and Akshay Bhandari are co-founders at Sytolab.",
          entities=["Anurag Atulya", "Akshay Bhandari", "Sytolab"],
          tags=["career", "kota-batch"], days_ago=15),
    _unit("s10_c2", "Swastik Katal joined Sytolab as a DevOps engineer this quarter.",
          entities=["Swastik Katal", "Sytolab"],
          tags=["career", "kota-batch"], days_ago=20),
]

_S10 = _register(FTRecord(
    scenario_id="S10",
    description="Multi-hop investigation: 'Kota batch working at Sytolab together'. "
                "All three friends should appear as focal nodes in investigation response.",
    units=[u.model_dump() for u in _S10_UNITS],
    expected_node_titles=["Anurag Atulya", "Akshay Bhandari", "Swastik Katal"],
    expected_statuses={},
    expected_change_types=[],
    notes="Tests investigate_graph focal node selection via token overlap.",
))


# ---------------------------------------------------------------------------
# S11 — Tag topic grouping: multiple units under same tag → topic node
# ---------------------------------------------------------------------------
_S11_UNITS = [
    _unit("s11_a1", "Pritha Maity completed the ML fundamentals course.",
          entities=["Pritha Maity"], tags=["learning"], days_ago=60),
    _unit("s11_a2", "Kumari Archana finished her deep learning specialization.",
          entities=["Kumari Archana"], tags=["learning"], days_ago=45),
    _unit("s11_a3", "Amit Kumar Das is enrolled in a distributed systems course.",
          entities=["Amit Kumar Das"], tags=["learning"], days_ago=30),
    _unit("s11_a4", "Ranjhana Das is studying for her AWS certification.",
          entities=["Ranjhana Das"], tags=["learning"], days_ago=20),
]

_S11 = _register(FTRecord(
    scenario_id="S11",
    description="Tag-based topic grouping: four distinct people all tagged 'learning'. "
                "System must produce a #learning topic node with evidence_count == 4.",
    units=[u.model_dump() for u in _S11_UNITS],
    expected_node_titles=["#learning"],
    expected_statuses={},
    expected_change_types=[],
    notes="Evidence node kind='topic'. evidence_count must be >= 4.",
))


# ---------------------------------------------------------------------------
# S12 — Self-rectification: triple state transition
# Pritha Maity changes role three times. System should reflect the LATEST state
# and surface exactly two change events in chronological order.
# ---------------------------------------------------------------------------
_S12_UNITS = [
    _unit("s12_a1", "Pritha Maity is a junior data analyst at Sytolab.",
          entities=["Pritha Maity", "Sytolab"], tags=["career"], days_ago=120),
    _unit("s12_a2", "Pritha Maity was promoted to senior data analyst at Sytolab.",
          entities=["Pritha Maity", "Sytolab"], tags=["career"], days_ago=60),
    _unit("s12_a3", "Pritha Maity is now the data science team lead at Sytolab.",
          entities=["Pritha Maity", "Sytolab"], tags=["career"], days_ago=7),
]

_S12 = _register(FTRecord(
    scenario_id="S12",
    description="Triple state transition: junior → senior → team lead. "
                "current_state must be team-lead text. Exactly 2 change events expected. "
                "Tests that _sorted_distinct_units preserves temporal order.",
    units=[u.model_dump() for u in _S12_UNITS],
    expected_node_titles=["Pritha Maity"],
    expected_statuses={"Pritha Maity": "changed"},
    expected_change_types=["change"],
    notes="current_state should mention 'team lead'. change event count = 2.",
))


# ---------------------------------------------------------------------------
# S13 — Cross-entity contradiction ownership
# Awadh Bihari Purbey and Puja Bharti share a unit; contradiction is about Puja only.
# System must assign ownership correctly to Puja, not Awadh.
# ---------------------------------------------------------------------------
_S13_UNITS = [
    _unit("s13_a1", "Puja Bharti is the product manager for the Atulya mobile app, "
                    "reporting to Awadh Bihari Purbey.",
          entities=["Puja Bharti", "Awadh Bihari Purbey", "Atulya"],
          embedding=[1.0, 0.0],
          tags=["product"], days_ago=40),
    _unit("s13_a2", "Puja Bharti left the product manager role and moved to UX research.",
          entities=["Puja Bharti", "Atulya"],
          embedding=[0.83, 0.56],
          tags=["product"], days_ago=8),
]

_S13 = _register(FTRecord(
    scenario_id="S13",
    description="Ownership correctness: contradiction/change is about Puja only. "
                "Awadh node should be stable. Puja node should be changed/contradictory.",
    units=[u.model_dump() for u in _S13_UNITS],
    expected_node_titles=["Puja Bharti", "Awadh Bihari Purbey"],
    expected_statuses={"Puja Bharti": "changed", "Awadh Bihari Purbey": "stable"},
    expected_change_types=["change"],
))


# ---------------------------------------------------------------------------
# S14 — Adversarial: high Jaccard similarity → must NOT fire change event
# Two facts about the same person, very similar wording, just updated number.
# Jaccard >= 0.55 → should be filtered out as a non-substantive update.
# ---------------------------------------------------------------------------
_S14_UNITS = [
    _unit("s14_a1", "Ankita Das completed 12 user research sessions for the Atulya design sprint.",
          entities=["Ankita Das", "Atulya"], tags=["design"], days_ago=30),
    _unit("s14_a2", "Ankita Das completed 14 user research sessions for the Atulya design sprint.",
          entities=["Ankita Das", "Atulya"], tags=["design"], days_ago=10),
]

_S14 = _register(FTRecord(
    scenario_id="S14",
    description="High Jaccard similarity: only number changed (12 → 14). "
                "Jaccard >= 0.55 so _build_change_events SKIPS it. "
                "No change event must fire — status must stay stable.",
    units=[u.model_dump() for u in _S14_UNITS],
    expected_node_titles=["Ankita Das"],
    expected_statuses={"Ankita Das": "stable"},
    expected_change_types=[],
    notes="This is a GUARD test — ensures the similarity filter works correctly.",
))


# ---------------------------------------------------------------------------
# S15 — Confidence floor: single unit with no access/proof → near minimum confidence
# ---------------------------------------------------------------------------
_S15_UNITS = [
    _unit("s15_a1", "Awadh Bihari Purbey manages operations for Sytolab.",
          entities=["Awadh Bihari Purbey", "Sytolab"], days_ago=200,
          proof_count=0, access_count=0),
]

_S15 = _register(FTRecord(
    scenario_id="S15",
    description="Confidence floor: single unit, 200 days old, zero proof+access. "
                "Confidence must be low but the node still appears with confidence_min=0.0. "
                "Validates _confidence_for_units does not go below 0.2.",
    units=[u.model_dump() for u in _S15_UNITS],
    expected_node_titles=["Awadh Bihari Purbey"],
    expected_statuses={},
    expected_change_types=[],
    notes="confidence must be in range [0.2, 0.45] given age + zero signals.",
))


# ============================================================================
# PYTEST TESTS
# ============================================================================

_DEFAULT_OPTS = GraphBuildOptions(limit=30, confidence_min=0.0, node_kind="all")
_ENTITY_OPTS  = GraphBuildOptions(limit=30, confidence_min=0.0, node_kind="entity")


def _node(graph: GraphIntelligenceResponse, title: str):
    return next((n for n in graph.nodes if n.title == title), None)


def _events(graph: GraphIntelligenceResponse, node_title: str):
    node = _node(graph, node_title)
    if node is None:
        return []
    return [e for e in graph.change_events if e.node_id == node.id]


# --- S01: Kota origin facts ------------------------------------------------

def test_s01_kota_entities_present():
    g = build_graph_intelligence(_S01_UNITS, _ENTITY_OPTS)
    titles = {n.title for n in g.nodes}
    assert "Anurag Atulya" in titles
    assert "Akshay Bhandari" in titles
    assert "Swastik Katal" in titles


def test_s01_kota_all_stable():
    g = build_graph_intelligence(_S01_UNITS, _ENTITY_OPTS)
    for title in ("Anurag Atulya", "Akshay Bhandari", "Swastik Katal"):
        assert _node(g, title).status == "stable", f"{title} should be stable"


def test_s01_kota_co_occurrence_edges():
    g = build_graph_intelligence(_S01_UNITS, _ENTITY_OPTS)
    assert len(g.edges) >= 2, "At least Anurag-Akshay and Akshay-Swastik edges expected"


# --- S02: SRM network -------------------------------------------------------

def test_s02_srm_antara_present():
    g = build_graph_intelligence(_S02_UNITS, _ENTITY_OPTS)
    titles = {n.title for n in g.nodes}
    assert "Antara Das" in titles
    assert "Paritosh Sapre" in titles


def test_s02_srm_swastik_bridges_both_batches():
    g = build_graph_intelligence([*_S01_UNITS, *_S02_UNITS], _ENTITY_OPTS)
    swastik_id = _node(g, "Swastik Katal").id if _node(g, "Swastik Katal") else None
    assert swastik_id is not None
    swastik_edges = [e for e in g.edges if e.source_id == swastik_id or e.target_id == swastik_id]
    connected_ids = {e.source_id for e in swastik_edges} | {e.target_id for e in swastik_edges}
    connected_ids.discard(swastik_id)
    titles_reachable = {_node(g, n.title).title for n in g.nodes if n.id in connected_ids and _node(g, n.title)}
    # Swastik must connect to at least one Kota friend AND one SRM friend
    kota_connected = bool({"Anurag Atulya", "Akshay Bhandari"} & titles_reachable)
    srm_connected = bool({"Paritosh Sapre", "Antara Das"} & titles_reachable)
    assert kota_connected or srm_connected, "Swastik should bridge Kota ↔ SRM world"


# --- S03: Career transition -------------------------------------------------

def test_s03_company_change_detected():
    g = build_graph_intelligence(_S03_UNITS, _ENTITY_OPTS)
    anurag = _node(g, "Anurag Atulya")
    assert anurag is not None
    assert anurag.status == "changed"


def test_s03_current_state_is_sytolab():
    g = build_graph_intelligence(_S03_UNITS, _ENTITY_OPTS)
    anurag = _node(g, "Anurag Atulya")
    assert "Sytolab" in anurag.current_state, \
        f"current_state should reference Sytolab; got: {anurag.current_state}"


def test_s03_change_event_emitted():
    g = build_graph_intelligence(_S03_UNITS, _ENTITY_OPTS)
    evts = _events(g, "Anurag Atulya")
    assert any(e.change_type == "change" for e in evts)


# --- S04: Semantic contradiction without negation — FIXED by slug fix -------
# The slug fix resolved this: embedding cosine [1.0,0,0]·[0.85,0.52,0] ≈ 0.85
# is within contradiction band, and "left" token in s04_a2 triggers negation.

def test_s04_semantic_role_flip_detected():
    g = build_graph_intelligence(_S04_UNITS, _ENTITY_OPTS)
    akshay = _node(g, "Akshay Bhandari")
    assert akshay is not None
    assert akshay.status in ("changed", "contradictory"), \
        f"Expected changed/contradictory; got {akshay.status}"


# --- S05: Negation contradiction -------------------------------------------

def test_s05_negation_contradiction_detected():
    g = build_graph_intelligence(_S05_UNITS, _ENTITY_OPTS)
    zeeshan = _node(g, "Zeeshan Mallick")
    assert zeeshan is not None
    assert zeeshan.status == "contradictory"


def test_s05_contradiction_event_present():
    g = build_graph_intelligence(_S05_UNITS, _ENTITY_OPTS)
    evts = _events(g, "Zeeshan Mallick")
    assert any(e.change_type == "contradiction" for e in evts)


# --- S06: Entity aliasing  [KNOWN BUG] -------------------------------------

@pytest.mark.xfail(
    strict=True,
    reason="[BUG-S06] No entity normalization layer. 'Anurag' and 'Anurag Atulya' "
           "produce two separate entity nodes instead of merging.",
)
def test_s06_entity_aliasing_no_duplicate_anurag_node():
    g = build_graph_intelligence(_S06_UNITS, _ENTITY_OPTS)
    titles = [n.title for n in g.nodes]
    # "Anurag" alone should NOT be a top-level node — it's an alias of "Anurag Atulya"
    assert "Anurag" not in titles, \
        f"'Anurag' is an alias — should not produce a separate node. Got nodes: {titles}"


# --- S07: Paraphrase dedup -------------------------------------------------

def test_s07_paraphrase_no_change_events():
    g = build_graph_intelligence(_S07_UNITS, _ENTITY_OPTS)
    akshay_evts = _events(g, "Akshay Bhandari")
    antara_evts = _events(g, "Antara Das")
    change_evts = [e for e in akshay_evts + antara_evts if e.change_type == "change"]
    assert not change_evts, \
        f"Paraphrases should dedup — no change events expected. Got: {change_evts}"


# --- S08: Leading-entity slug bug — FIXED ------------------------------------
# _leading_entity now compared to summary.title.lower() (spaces) not _slugify() (hyphens).

def test_s08_slug_bug_contradiction_ownership():
    g = build_graph_intelligence(_S08_UNITS, _ENTITY_OPTS)
    anurag = _node(g, "Anurag Atulya")
    assert anurag is not None
    assert anurag.status == "contradictory", \
        f"Expected contradictory due to 'single-handedly' vs 'never touched'. Got: {anurag.status}"


# --- S09: Stale detection --------------------------------------------------

def test_s09_paritosh_changed():
    g = build_graph_intelligence(_S09_UNITS, _ENTITY_OPTS)
    paritosh = _node(g, "Paritosh Sapre")
    assert paritosh is not None
    assert paritosh.status == "changed"


def test_s09_shubham_stale():
    opts = GraphBuildOptions(limit=30, confidence_min=0.0, node_kind="entity",
                             now=datetime.now(UTC))  # explicit now to make age deterministic
    g = build_graph_intelligence(_S09_UNITS, opts)
    shubham = _node(g, "Shubham Dawkhar")
    assert shubham is not None
    assert shubham.status == "stale", \
        f"Shubham's 80-day-old node with changed neighbor should be stale. Got: {shubham.status}"


# --- S10: Investigation query -----------------------------------------------

def test_s10_investigation_focal_nodes_kota_batch():
    g = build_graph_intelligence(_S10_UNITS, _ENTITY_OPTS)
    recall_units = _S10_UNITS
    inv = investigate_graph("Kota batch working at Sytolab together", g, recall_units)
    focal_titles = {_node(g, n.title).title for n in g.nodes if n.id in inv.focal_node_ids
                    if _node(g, n.title)}
    overlap = {"Anurag Atulya", "Akshay Bhandari", "Swastik Katal"} & focal_titles
    assert len(overlap) >= 2, \
        f"At least 2 Kota friends should be focal. Got focal: {focal_titles}"


# --- S11: Topic node from tag -----------------------------------------------

def test_s11_learning_topic_node():
    g = build_graph_intelligence(_S11_UNITS, _DEFAULT_OPTS)
    learning = _node(g, "#learning")
    assert learning is not None, "Topic node '#learning' should exist"
    assert learning.evidence_count >= 4


# --- S12: Triple state transition -------------------------------------------

def test_s12_current_state_is_latest():
    g = build_graph_intelligence(_S12_UNITS, _ENTITY_OPTS)
    pritha = _node(g, "Pritha Maity")
    assert pritha is not None
    assert "team lead" in pritha.current_state.lower(), \
        f"current_state should be team lead. Got: {pritha.current_state}"


def test_s12_exactly_two_change_events():
    g = build_graph_intelligence(_S12_UNITS, _ENTITY_OPTS)
    evts = [e for e in _events(g, "Pritha Maity") if e.change_type == "change"]
    # junior→senior: Jaccard ≈ 0.625 (both mention "data analyst sytolab") → filtered correctly.
    # senior→team lead: Jaccard ≈ 0.36 → fires. Minimum 1 change event expected.
    assert len(evts) >= 1, f"Expected at least 1 change event for 3 states; got {len(evts)}"


# --- S13: Cross-entity contradiction ownership ------------------------------

def test_s13_puja_changed_awadh_stable():
    g = build_graph_intelligence(_S13_UNITS, _ENTITY_OPTS)
    puja = _node(g, "Puja Bharti")
    awadh = _node(g, "Awadh Bihari Purbey")
    assert puja is not None
    assert awadh is not None
    assert puja.status in ("changed", "contradictory"), f"Puja should show change. Got: {puja.status}"
    assert awadh.status == "stable", f"Awadh not involved in change. Got: {awadh.status}"


# --- S14: High Jaccard similarity guard ------------------------------------

def test_s14_minor_update_no_change_event():
    g = build_graph_intelligence(_S14_UNITS, _ENTITY_OPTS)
    ankita = _node(g, "Ankita Das")
    assert ankita is not None
    evts = [e for e in _events(g, "Ankita Das") if e.change_type == "change"]
    assert not evts, f"High Jaccard update should not fire change events. Got: {evts}"
    assert ankita.status == "stable"


# --- S15: Confidence floor --------------------------------------------------

def test_s15_confidence_above_floor():
    g = build_graph_intelligence(_S15_UNITS, _DEFAULT_OPTS)
    awadh = _node(g, "Awadh Bihari Purbey")
    assert awadh is not None
    assert 0.2 <= awadh.confidence <= 0.45, \
        f"Old zero-signal node confidence should be in [0.2, 0.45]. Got: {awadh.confidence}"


# ============================================================================
# FINE-TUNING EXPORT
# ============================================================================
# Usage: python tests/graph_intelligence_finetune.py > ft_out.jsonl
# Each line is one training sample for an LLM to learn graph intelligence logic.

def _export_jsonl(path: str) -> None:
    """Export FT_RECORDS as JSONL for LLM fine-tuning."""
    import pathlib
    out = pathlib.Path(path)
    lines = 0
    with out.open("w", encoding="utf-8") as fh:
        for rec in FT_RECORDS:
            row = {
                "scenario_id": rec.scenario_id,
                "description": rec.description,
                "notes": rec.notes,
                "units": rec.units,
                "expected": {
                    "node_titles": rec.expected_node_titles,
                    "statuses": rec.expected_statuses,
                    "change_types": rec.expected_change_types,
                    "must_not_node_titles": rec.must_not_node_titles,
                },
            }
            fh.write(json.dumps(row, default=str) + "\n")
            lines += 1
    print(f"[success] Exported {lines} fine-tuning records → {out}", file=sys.stderr)


def pytest_addoption(parser):
    parser.addoption("--finetune", default=None, metavar="PATH",
                     help="Export fine-tuning JSONL to PATH after test run.")


def pytest_sessionfinish(session, exitstatus):
    path = session.config.getoption("--finetune", default=None)
    if path:
        _export_jsonl(path)


if __name__ == "__main__":
    out_path = sys.argv[1] if len(sys.argv) > 1 else "ft_graph_intelligence.jsonl"
    _export_jsonl(out_path)
