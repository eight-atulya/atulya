"""
Graph Intelligence Closed-Loop Seed & Validate
================================================
Single source of truth for the fine-tuning bank lifecycle:

  Stage 1 — SEED    : Create bank + retain facts in semantic order (earliest first).
  Stage 2 — VALIDATE: Call graph/intelligence API, assert expected nodes/statuses.
  Stage 3 — DIAGNOSE: If validation fails, print structured root-cause diff.
  Stage 4 — HUMAN   : Human reviews diff, decides whether root is in memory logic
                       or bank/retain logic, marks stage as ACCEPTED / REJECTED.

Usage:
  # Full pipeline (seed → validate → report):
  python tests/graph_intelligence_seed.py \
      --api http://localhost:8888 \
      --key * \
      --stage all

  # Individual stages:
  python tests/graph_intelligence_seed.py --stage seed
  python tests/graph_intelligence_seed.py --stage validate
  python tests/graph_intelligence_seed.py --stage report

  # Re-seed from scratch (wipes existing bank):
  python tests/graph_intelligence_seed.py --stage seed --force

Metadata:

  @intent:  Closed-loop graph intelligence fine-tuning with human-in-the-loop
            validation at each stage.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

# ============================================================================
# CONFIG
# ============================================================================

BANK_ID    = "graph-intelligence-finetune"
BANK_LABEL = "Graph Intelligence Fine-tune Bank"
API_BASE   = "http://localhost:8888"
API_KEY    = "*"

# Retain units in semantic batches — ordering matters:
# 1. Origin/stable facts (fixed timestamps in the past)
# 2. Evolving states (state A → state B)
# 3. Contradictions (state A vs NOT-state-A)
# 4. Stale candidates (old state + changed neighbor)


# ============================================================================
# SEED CORPUS
# Facts are ordered: oldest first so temporal chain is correct.
# Each item maps directly to a MemoryItem on the API.
# ============================================================================

@dataclass
class SeedItem:
    """One unit to retain into the bank."""
    doc_id: str          # stable across re-seeds (used for update_mode=replace)
    content: str
    timestamp: str       # ISO-8601
    context: str
    tags: list[str]
    scenario: str        # S01..S15 — trace back to finetune test
    note: str = ""


# ── Helpers ─────────────────────────────────────────────────────────────────

def _iso(days_ago: int, hour: int = 10) -> str:
    """Deterministic ISO timestamp: anchor to 2026-04-28 minus days_ago."""
    from datetime import timedelta
    base = datetime(2026, 4, 28, hour, 0, 0, tzinfo=timezone.utc)
    return (base - timedelta(days=days_ago)).isoformat()


# ── S01: Kota batch origin (all same day — no temporal pairs) ────────────────
S01 = [
    SeedItem("s01_anurag_origin",
             "Anurag Atulya is from Jharkhand and moved to Kota, Rajasthan in 2014 for JEE preparation.",
             _iso(400), "biographical", ["kota-batch", "origin"], "S01"),
    SeedItem("s01_akshay_origin",
             "Akshay Bhandari is originally from Chennai but studied in Kota, Rajasthan from 2014.",
             _iso(400, 11), "biographical", ["kota-batch", "origin"], "S01"),
    SeedItem("s01_swastik_origin",
             "Swastik Katal came from Jammu to Kota, Rajasthan in 2014 to prepare for JEE.",
             _iso(400, 12), "biographical", ["kota-batch", "origin"], "S01"),
    SeedItem("s01_kota_friendship",
             "Anurag Atulya, Akshay Bhandari, and Swastik Katal became best friends during their Kota days in 2014 and remain close friends.",
             _iso(400, 13), "relationship", ["kota-batch", "friendship"], "S01",
             note="All three names must appear — prevents abbreviated name aliasing"),
]

# ── S02: SRM network ─────────────────────────────────────────────────────────
S02 = [
    SeedItem("s02_paritosh_shubham_srm",
             "Paritosh Sapre and Shubham Dawkhar were classmates at SRM University Chennai and became good friends.",
             _iso(300), "biographical", ["srm-batch", "friendship"], "S02"),
    SeedItem("s02_anurag_srm",
             "Anurag Atulya joined SRM University Chennai in August 2016.",
             _iso(280), "biographical", ["srm-batch"], "S02"),
    SeedItem("s02_antara_anurag_srm",
             "Antara Das met Anurag Atulya at SRM University Chennai in August 2016 during freshers orientation.",
             _iso(270), "relationship", ["srm-batch", "friendship"], "S02"),
    SeedItem("s02_swastik_paritosh_srm",
             "Swastik Katal joined SRM University for his final year project and met Paritosh Sapre there.",
             _iso(250), "relationship", ["srm-batch", "friendship"], "S02",
             note="Swastik bridges Kota-batch ↔ SRM-batch"),
]

# ── Shared birthday ──────────────────────────────────────────────────────────
S_BIRTHDAY = [
    SeedItem("shared_birthday_akshay_antara",
             "Akshay Bhandari and Antara Das share the same birth date: both born on the 8th of the month.",
             _iso(200), "biographical", ["birthday"], "S07"),
]

    # ── S03/S04: Career transitions ──────────────────────────────────────────────
S03 = [
    # Anurag: Kreator3d (old) → Sytolab (new)
    SeedItem("s03_anurag_kreator3d",
             "Anurag Atulya is the founding engineer at Kreator3d, leading the 3D rendering pipeline.",
             _iso(180), "career", ["career", "kreator3d"], "S03"),
    SeedItem("s03_anurag_kreator3d_context",
             "Kreator3d is a small startup and Anurag Atulya handles both product and engineering responsibilities.",
             _iso(150), "career", ["career", "kreator3d"], "S03"),
    SeedItem("s03_anurag_sytolab",
             "Anurag Atulya has joined Sytolab as a principal engineer, leaving Kreator3d behind.",
             _iso(10), "career", ["career", "sytolab"], "S03",
             note="MUST trigger change event: Kreator3d → Sytolab"),
    # Akshay: senior backend at Kreator3d → junior frontend at Sytolab
    SeedItem("s04_akshay_kreator3d",
             "Akshay Bhandari is the senior backend engineer at Kreator3d, based in Chennai.",
             _iso(90), "career", ["career", "kreator3d"], "S04"),
    SeedItem("s04_akshay_sytolab",
             "Akshay Bhandari joined Sytolab as a junior frontend developer, relocating to Bangalore.",
             _iso(5), "career", ["career", "sytolab"], "S04",
             note="Role + company + city flip — must detect change"),
]# ── S05: Negation contradiction ──────────────────────────────────────────────
S05 = [
    SeedItem("s05_zeeshan_remote",
             "Zeeshan Mallick is working remotely from Hyderabad full-time.",
             _iso(30), "work-mode", ["remote-work"], "S05"),
    SeedItem("s05_zeeshan_office",
             "Zeeshan Mallick is not working remotely; he returned to the office in Hyderabad.",
             _iso(3), "work-mode", ["remote-work"], "S05",
             note="'not' token + high embedding similarity → contradiction"),
]

# ── S06: Entity aliasing test data ───────────────────────────────────────────
S06 = [
    SeedItem("s06_anurag_atulya_project",
             "Anurag Atulya is building a memory OS called Atulya, designed for personal knowledge management.",
             _iso(60), "project", ["atulya-project"], "S06"),
    SeedItem("s06_anurag_maintainer",
             "Anurag Atulya is the primary maintainer of the Atulya codebase and reviews all pull requests.",
             _iso(45), "project", ["atulya-project"], "S06",
             note="Uses full name — avoids aliasing ambiguity"),
]

# ── S09: Stale detection ─────────────────────────────────────────────────────
S09 = [
    SeedItem("s09_shubham_kreator3d",
             "Shubham Dawkhar is working on the frontend team at Kreator3d alongside Paritosh Sapre.",
             _iso(80), "career", ["career", "kreator3d"], "S09",
             note="Old state — 80 days ago, no update since"),
    SeedItem("s09_paritosh_kreator3d_to_sytolab",
             "Paritosh Sapre moved from Kreator3d to Sytolab last week to lead the infrastructure team.",
             _iso(70), "career", ["career", "sytolab"], "S09"),
    SeedItem("s09_paritosh_sytolab_lead",
             "Paritosh Sapre is now the infrastructure team lead at Sytolab.",
             _iso(5), "career", ["career", "sytolab"], "S09",
             note="Recent update on connected node → should make Shubham stale"),
]

# ── S11: Learning topic cluster ──────────────────────────────────────────────
S11 = [
    SeedItem("s11_pritha_learning",
             "Pritha Maity completed the ML fundamentals course on Coursera.",
             _iso(60), "learning", ["learning"], "S11"),
    SeedItem("s11_kumari_learning",
             "Kumari Archana finished her deep learning specialization.",
             _iso(45), "learning", ["learning"], "S11"),
    SeedItem("s11_amit_learning",
             "Amit Kumar Das is enrolled in a distributed systems course.",
             _iso(30), "learning", ["learning"], "S11"),
    SeedItem("s11_ranjhana_learning",
             "Ranjhana Das is studying for her AWS Solutions Architect certification.",
             _iso(20), "learning", ["learning"], "S11"),
]

# ── S12: Triple role transition ──────────────────────────────────────────────
S12 = [
    SeedItem("s12_pritha_junior",
             "Pritha Maity is a junior data analyst at Sytolab.",
             _iso(120), "career", ["career", "sytolab"], "S12"),
    SeedItem("s12_pritha_senior",
             "Pritha Maity was promoted to senior data analyst at Sytolab.",
             _iso(60), "career", ["career", "sytolab"], "S12"),
    SeedItem("s12_pritha_lead",
             "Pritha Maity is now the data science team lead at Sytolab.",
             _iso(7), "career", ["career", "sytolab"], "S12",
             note="Latest state — must appear in current_state"),
]

# ── S13: Cross-entity ownership ──────────────────────────────────────────────
S13 = [
    SeedItem("s13_puja_pm",
             "Puja Bharti is the product manager for the Atulya mobile app.",
             _iso(40), "org", ["product", "atulya-project"], "S13"),
    SeedItem("s13_puja_ux",
             "Puja Bharti left the product manager role and moved to UX research at Sytolab.",
             _iso(8), "org", ["product", "sytolab"], "S13",
             note="Change is Puja's — Awadh untouched → stays stable"),
]

# ── S14: Minor numeric update (guard) ────────────────────────────────────────
S14 = [
    SeedItem("s14_ankita_12",
             "Ankita Das completed 12 user research sessions for the Atulya design sprint.",
             _iso(30), "design", ["design", "atulya-project"], "S14"),
    SeedItem("s14_ankita_14",
             "Ankita Das completed 14 user research sessions for the Atulya design sprint.",
             _iso(10), "design", ["design", "atulya-project"], "S14",
             note="High Jaccard — must NOT fire change event"),
]

# ── S15: Low-signal confidence floor ─────────────────────────────────────────
S15 = [
    SeedItem("s15_awadh_ops",
             "Awadh Bihari Purbey manages operations for Sytolab.",
             _iso(200), "org", [], "S15",
             note="Single old fact, zero tags — confidence should be low but above floor"),
]

# Full seed corpus — semantic order: biography → relationships → career → learning → org
ALL_ITEMS: list[SeedItem] = [
    *S01, *S02, *S_BIRTHDAY,
    *S03, *S05, *S06,
    *S09, *S11, *S12, *S13, *S14, *S15,
]


# ============================================================================
# VALIDATION SPECS
# Each spec maps to a graph intelligence assertion made against the live bank.
# ============================================================================

@dataclass
class ValidationSpec:
    scenario: str
    description: str
    # Node that MUST appear in graph intelligence response
    must_have_nodes: list[str] = field(default_factory=list)
    # Expected status for specific nodes
    expected_statuses: dict[str, str] = field(default_factory=dict)
    # At least one of these change_types must be present for the node
    expected_change_types: dict[str, list[str]] = field(default_factory=dict)
    # Nodes that must NOT appear
    must_not_nodes: list[str] = field(default_factory=list)
    # Root-cause hint if validation fails
    failure_hint: str = ""


VALIDATIONS: list[ValidationSpec] = [
    ValidationSpec(
        scenario="S01",
        description="Kota batch — all three friends present, Swastik stable (no career transition seeds)",
        must_have_nodes=["Anurag Atulya", "Akshay Bhandari", "Swastik Katal"],
        expected_statuses={"Swastik Katal": "stable"},
        failure_hint="Check: did retain extract full entity names? Are timestamps co-incident?",
    ),
    ValidationSpec(
        scenario="S02",
        description="SRM network — Antara + Paritosh present, Swastik connects both batches",
        must_have_nodes=["Antara Das", "Paritosh Sapre", "Shubham Dawkhar"],
        failure_hint="Check: entity extraction from narrative relationship text",
    ),
    ValidationSpec(
        scenario="S03",
        description="Anurag career change Kreator3d → Sytolab detected",
        must_have_nodes=["Anurag Atulya"],
        expected_statuses={"Anurag Atulya": "changed"},
        expected_change_types={"Anurag Atulya": ["change"]},
        failure_hint="Check: are timestamp deltas large enough? Is _leading_entity matching 'Anurag Atulya'?",
    ),
    ValidationSpec(
        scenario="S04",
        description="Akshay role+company flip detected",
        must_have_nodes=["Akshay Bhandari"],
        expected_statuses={"Akshay Bhandari": "changed"},
        expected_change_types={"Akshay Bhandari": ["change"]},
        failure_hint="Check: 'joined' verb not in negation set — may need to add 'joined' as state-exit for prior role",
    ),
    ValidationSpec(
        scenario="S05",
        description="Zeeshan remote/not-remote contradiction",
        must_have_nodes=["Zeeshan Mallick"],
        expected_statuses={"Zeeshan Mallick": "contradictory"},
        expected_change_types={"Zeeshan Mallick": ["contradiction"]},
        failure_hint="Check: embedding similarity computed? 'not' in negation set?",
    ),
    ValidationSpec(
        scenario="S09",
        description="Shubham stale (old node, changed neighbor Paritosh)",
        must_have_nodes=["Shubham Dawkhar", "Paritosh Sapre"],
        expected_statuses={"Paritosh Sapre": "changed", "Shubham Dawkhar": "stale"},
        expected_change_types={"Paritosh Sapre": ["change"]},
        failure_hint="Check: co-occurrence edge Shubham↔Paritosh exists? age_days >= 45?",
    ),
    ValidationSpec(
        scenario="S11",
        description="#learning topic node with 4 members",
        must_have_nodes=["#learning"],
        failure_hint="Check: all 4 items tagged 'learning'? Topic node requires >= 2 units.",
    ),
    ValidationSpec(
        scenario="S12",
        description="Pritha triple transition — current state = team lead",
        must_have_nodes=["Pritha Maity"],
        expected_statuses={"Pritha Maity": "changed"},
        failure_hint="Check: current_state must reference 'team lead'. Verify _sorted_distinct_units order.",
    ),
    ValidationSpec(
        scenario="S13",
        description="Puja changed/contradictory due to role exit (ownership isolation test)",
        must_have_nodes=["Puja Bharti"],
        expected_statuses={"Puja Bharti": "contradictory"},
        failure_hint="If Puja is 'stable', check: 'left' in _NEGATION_MARKERS? LLM paraphrased away the negation?",
    ),
    ValidationSpec(
        scenario="S14",
        description="Ankita: minor number update — no change event",
        must_have_nodes=["Ankita Das"],
        expected_statuses={"Ankita Das": "stable"},
        failure_hint="Check: Jaccard of '12 user research sessions' vs '14 user research sessions' — should be >= 0.55",
    ),
    ValidationSpec(
        scenario="S15",
        description="Awadh low-signal confidence in [0.2, 0.45]",
        must_have_nodes=["Awadh Bihari Purbey"],
        failure_hint="Check: _confidence_for_units floor = 0.2. Recency penalty for 200-day-old fact.",
    ),
]


# ============================================================================
# API CLIENT
# ============================================================================

class AtulyaClient:
    def __init__(self, base: str, key: str):
        self.base = base.rstrip("/")
        self.headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _url(self, path: str) -> str:
        return f"{self.base}{path}"

    def create_bank(self, bank_id: str) -> dict:
        r = httpx.put(self._url(f"/v1/default/banks/{bank_id}"),
                      headers=self.headers,
                      json={"retain_mission": "Store biographical, career, relationship, and project facts about the Atulya team."},
                      timeout=30)
        r.raise_for_status()
        return r.json()

    def delete_bank(self, bank_id: str) -> None:
        r = httpx.delete(self._url(f"/v1/default/banks/{bank_id}"),
                         headers=self.headers, timeout=30)
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    def retain(self, bank_id: str, items: list[dict]) -> dict:
        r = httpx.post(self._url(f"/v1/default/banks/{bank_id}/memories"),
                       headers=self.headers,
                       json={"items": items, "async": False},
                       timeout=180)
        r.raise_for_status()
        return r.json()

    def get_graph_intelligence(self, bank_id: str, confidence_min: float = 0.0,
                               limit: int = 40, window_days: int = 500) -> dict:
        params = f"confidence_min={confidence_min}&limit={limit}&window_days={window_days}"
        r = httpx.get(self._url(f"/v1/default/banks/{bank_id}/graph/intelligence?{params}"),
                      headers=self.headers, timeout=60)
        r.raise_for_status()
        return r.json()

    def health(self) -> bool:
        try:
            r = httpx.get(self._url("/health"), timeout=5)
            return r.status_code == 200
        except Exception:
            return False


# ============================================================================
# STAGE 1 — SEED
# ============================================================================

def stage_seed(client: AtulyaClient, force: bool = False) -> None:
    print("\n[seed] ──────────────────────────────────────────────────")
    if not client.health():
        print("[error] API not reachable at", client.base)
        sys.exit(1)

    if force:
        print(f"[seed] --force: deleting bank '{BANK_ID}'")
        client.delete_bank(BANK_ID)
        time.sleep(1)

    print(f"[seed] Creating bank '{BANK_ID}'")
    client.create_bank(BANK_ID)

    # Retain in semantic batches — each batch as one document
    batches: dict[str, list[SeedItem]] = {}
    for item in ALL_ITEMS:
        batches.setdefault(item.scenario, []).append(item)

    total = 0
    for scenario_id, items in batches.items():
        print(f"[seed] {scenario_id}: retaining {len(items)} items ...")
        for it in items:
            payload = [{
                "content": it.content,
                "timestamp": it.timestamp,
                "context": it.context,
                "tags": it.tags,
                "document_id": it.doc_id,
                "update_mode": "replace",
            }]
            print(f"  [{it.doc_id}] ...", end=" ", flush=True)
            try:
                client.retain(BANK_ID, payload)
                print("[success]")
                total += 1
            except httpx.HTTPStatusError as e:
                print(f"[error] {e.response.status_code}: {e.response.text[:200]}")
            except Exception as e:
                print(f"[error] {e}")

    print(f"[seed] Done — {total}/{len(ALL_ITEMS)} items retained into bank '{BANK_ID}'")
    print(f"[seed] View: http://localhost:9999/banks/{BANK_ID}?view=data")


# ============================================================================
# STAGE 2 — VALIDATE
# ============================================================================

@dataclass
class ValidationResult:
    scenario: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    node_dump: dict[str, Any] = field(default_factory=dict)  # {title: {status, confidence, change_score}}


def stage_validate(client: AtulyaClient) -> list[ValidationResult]:
    print("\n[validate] ──────────────────────────────────────────────")
    raw = client.get_graph_intelligence(BANK_ID, confidence_min=0.0, limit=100)
    nodes_by_title: dict[str, dict] = {n["title"]: n for n in raw.get("nodes", [])}
    events_by_node: dict[str, list[str]] = {}
    for ev in raw.get("change_events", []):
        events_by_node.setdefault(ev["node_id"], []).append(ev["change_type"])

    results: list[ValidationResult] = []

    for spec in VALIDATIONS:
        failures: list[str] = []
        warnings: list[str] = []
        node_dump: dict[str, Any] = {}

        for title in spec.must_have_nodes:
            node = nodes_by_title.get(title)
            if node is None:
                failures.append(f"[MISSING NODE] '{title}' not in graph intelligence response")
                continue
            node_dump[title] = {
                "status": node["status"],
                "confidence": node["confidence"],
                "change_score": node["change_score"],
                "evidence_count": node["evidence_count"],
            }

        for title, expected_status in spec.expected_statuses.items():
            node = nodes_by_title.get(title)
            if node is None:
                continue  # already reported above
            if node["status"] != expected_status:
                failures.append(
                    f"[STATUS] '{title}': expected={expected_status} got={node['status']}"
                )

        for title, expected_types in spec.expected_change_types.items():
            node = nodes_by_title.get(title)
            if node is None:
                continue
            node_id = node["id"]
            actual_types = set(events_by_node.get(node_id, []))
            missing = [t for t in expected_types if t not in actual_types]
            if missing:
                failures.append(
                    f"[EVENTS] '{title}': missing change_types={missing} (got {sorted(actual_types)})"
                )

        for title in spec.must_not_nodes:
            if title in nodes_by_title:
                failures.append(f"[SPURIOUS NODE] '{title}' should NOT appear")

        passed = len(failures) == 0
        status = "[success]" if passed else "[failure]"
        print(f"  {status} {spec.scenario}: {spec.description}")
        if failures:
            for f in failures:
                print(f"    ~~> {f}")
            print(f"    [hint] {spec.failure_hint}")

        results.append(ValidationResult(
            scenario=spec.scenario,
            passed=passed,
            failures=failures,
            warnings=warnings,
            node_dump=node_dump,
        ))

    passed_count = sum(1 for r in results if r.passed)
    print(f"\n[validate] {passed_count}/{len(results)} specs passed")
    return results


# ============================================================================
# STAGE 3 — REPORT (human-readable diff for root-cause analysis)
# ============================================================================

def stage_report(results: list[ValidationResult]) -> None:
    print("\n[report] ────────────────────────────────────────────────")
    failed = [r for r in results if not r.passed]
    if not failed:
        print("[success] All validations passed. Bank is consistent with spec.")
        return

    print(f"[failure] {len(failed)} scenario(s) need attention:\n")
    for r in failed:
        spec = next((s for s in VALIDATIONS if s.scenario == r.scenario), None)
        print(f"  Scenario : {r.scenario}")
        print(f"  Desc     : {spec.description if spec else '?'}")
        print(f"  Failures :")
        for f in r.failures:
            print(f"    {f}")
        if r.node_dump:
            print(f"  Node state:")
            for title, info in r.node_dump.items():
                print(f"    {title}: status={info['status']} confidence={info['confidence']:.3f} "
                      f"change_score={info['change_score']:.3f} evidence={info['evidence_count']}")
        if spec and spec.failure_hint:
            print(f"  [hint] {spec.failure_hint}")
        print()

    print("Root-cause classification (for human review):")
    print("  [A] Memory/retain logic  — fact extraction, entity resolution, embedding")
    print("  [B] Graph logic          — change detection, contradiction, stale scoring")
    print("  [C] API/schema           — endpoint shape, parameter mismatch")
    print()
    print("Mark each failure as A/B/C and commit to PCRM after root-cause confirmed.")


# ============================================================================
# STAGE 4 — DUMP JSONL (for LLM fine-tuning)
# ============================================================================

def stage_dump_jsonl(results: list[ValidationResult], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for r in results:
            spec = next((s for s in VALIDATIONS if s.scenario == r.scenario), None)
            row = {
                "scenario": r.scenario,
                "description": spec.description if spec else "",
                "passed": r.passed,
                "failures": r.failures,
                "node_state": r.node_dump,
                "seed_items": [
                    {"doc_id": it.doc_id, "content": it.content, "tags": it.tags}
                    for it in ALL_ITEMS if it.scenario == r.scenario
                ],
            }
            fh.write(json.dumps(row, default=str) + "\n")
    print(f"[dump] JSONL written → {path}")


# ============================================================================
# CLI
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api",   default=API_BASE, help="API base URL")
    parser.add_argument("--key",   default=API_KEY,  help="Bearer token")
    parser.add_argument("--stage", default="all",
                        choices=["seed", "validate", "report", "all"],
                        help="Pipeline stage to run")
    parser.add_argument("--force", action="store_true",
                        help="Delete and re-create bank before seeding")
    parser.add_argument("--jsonl", default=None, metavar="PATH",
                        help="Export validation results as JSONL for fine-tuning")
    args = parser.parse_args()

    client = AtulyaClient(args.api, args.key)
    results: list[ValidationResult] = []

    if args.stage in ("seed", "all"):
        stage_seed(client, force=args.force)
        time.sleep(2)  # brief pause for async indexing

    if args.stage in ("validate", "all"):
        results = stage_validate(client)

    if args.stage in ("report", "all") and results:
        stage_report(results)

    if args.jsonl and results:
        stage_dump_jsonl(results, args.jsonl)


if __name__ == "__main__":
    main()
