"""Tests for Data Forge module."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from atulya_api.forge.adapters.chat import ForgeChatAdapter
from atulya_api.forge.adapters.scenario import ForgeScenarioAdapter
from atulya_api.forge.adapters.timeseries import ForgeTimeSeriesAdapter
from atulya_api.forge.exporters.atr_jsonl import AtrJsonlExporter
from atulya_api.forge.exporters.graph_intelligence_jsonl import GraphIntelligenceJsonlExporter
from atulya_api.forge.exporters.openai_chat_jsonl import OpenAIChatJsonlExporter
from atulya_api.forge.metadata import DOMAIN_PROFILES, RECIPE_METADATA
from atulya_api.forge.models import (
    AtulyaTrainingRecord,
    FactSnapshot,
    ForgeIngestSource,
    ForgeJobRequest,
    GraphNodeSnapshot,
    GraphSnapshot,
    LineageBlock,
    ObsSnapshot,
    QualityScore,
    TimelineEpisode,
    TimelineSession,
    TimelineTurn,
    TrainingLabels,
    TrainingTask,
)
from atulya_api.forge.quality import audit_record, summarize_quality
from atulya_api.forge.registry import forge_catalog_payload, get_exporter, get_recipe, list_recipes, suggest_recipes


def _sample_record(*, exportable: bool = True, recipe_id: str = "consolidation_pairs") -> AtulyaTrainingRecord:
    fact = FactSnapshot(id="fact-1", text="Alice works at Google", fact_type="world")
    record = AtulyaTrainingRecord(
        record_id="rec-1",
        forge_job_id="job-1",
        bank_id="bank-1",
        recipe_id=recipe_id,
        timeline=TimelineEpisode(
            sessions=[
                TimelineSession(
                    session_id="s1",
                    event_date=datetime(2026, 1, 5, tzinfo=timezone.utc),
                    turns=[TimelineTurn(role="user", content="Hello")],
                )
            ]
        ),
        facts=[fact],
        observations=[
            ObsSnapshot(
                id="obs-1",
                text="Alice is at Google",
                proof_count=1,
                source_memory_ids=["fact-1"],
            )
        ],
        labels=TrainingLabels(
            answer="test",
            cited_memory_ids=["fact-1"],
            cited_observation_ids=["obs-1"],
        ),
        provenance=__import__("atulya_api.forge.models", fromlist=["ProvenanceBlock"]).ProvenanceBlock(
            document_ids=["doc-1"]
        ),
        lineage=LineageBlock(recipe_id=recipe_id),
    )
    record.quality = QualityScore(overall=0.9 if exportable else 0.2, exportable=exportable)
    return record


# --- Adapters ---


def test_chat_adapter_normalizes_sessions():
    adapter = ForgeChatAdapter()
    items = adapter.normalize(
        {
            "sessions": [
                {
                    "session_id": "s1",
                    "event_date": "2026-01-05T09:00:00Z",
                    "turns": [{"role": "user", "content": "Hi"}],
                }
            ]
        }
    )
    assert len(items) == 1
    assert "content" in items[0]
    assert items[0]["document_id"]
    turns = json.loads(items[0]["content"])
    assert turns[0]["role"] == "user"


def test_chat_adapter_locomo_conversation_shape():
    adapter = ForgeChatAdapter()
    items = adapter.normalize(
        {
            "conversation": {
                "session_1_date_time": "2026-01-05T09:00:00Z",
                "session_1": [{"speaker": "Alice", "text": "Hi"}],
            }
        }
    )
    assert len(items) == 1


def test_timeseries_adapter_rows():
    adapter = ForgeTimeSeriesAdapter()
    items = adapter.normalize(
        {
            "rows": [
                {"key": "gdp", "value": "2.1%", "timestamp": "2026-01-01"},
            ]
        }
    )
    assert len(items) == 1
    assert "gdp" in items[0]["content"]


def test_scenario_adapter_supersedes():
    adapter = ForgeScenarioAdapter()
    items = adapter.normalize(
        {
            "scenarios": [
                {
                    "id": "t1",
                    "query": "Where to deploy?",
                    "facts": [
                        {
                            "id": "f1",
                            "key": "region",
                            "value": "us-east-1",
                            "timestamp": "2026-01-05T09:00:00Z",
                            "supersedes": ["f0"],
                        }
                    ],
                    "expected": {"answer": "us-east-1"},
                }
            ]
        }
    )
    assert len(items) == 1
    assert "supersedes" in items[0]["content"]


# --- Quality audit ---


def test_quality_audit_flags_missing_citations():
    record = _sample_record()
    record.recipe_id = "temporal_qa"
    record.labels.cited_memory_ids = []
    record.labels.answer = "answer without cites"
    audited = audit_record(record, threshold=0.6)
    assert audited.quality.overall < 1.0
    assert not audited.quality.exportable
    assert any("citation" in issue.lower() for issue in audited.quality.issues)


def test_quality_audit_agent_trace_requires_memory_cites():
    record = _sample_record(recipe_id="agent_trace")
    record.labels.cited_memory_ids = []
    record.labels.cited_observation_ids = ["obs-1"]
    record.labels.answer = "trace answer"
    audited = audit_record(record, threshold=0.6)
    assert not audited.quality.provenance_complete
    assert not audited.quality.exportable


def test_quality_audit_invalid_citation_id():
    record = _sample_record()
    record.labels.cited_memory_ids = ["missing-id"]
    audited = audit_record(record, threshold=0.6)
    assert not audited.quality.citation_valid
    assert not audited.quality.exportable


def test_quality_audit_contradiction_blocks_export():
    record = _sample_record()
    record.graph = GraphSnapshot(nodes=[GraphNodeSnapshot(title="Deploy", node_kind="topic", status="contradictory")])
    audited = audit_record(record, threshold=0.3)
    assert audited.quality.contradiction_unresolved
    assert not audited.quality.exportable


def test_quality_audit_belief_update_allows_contradiction():
    record = _sample_record(recipe_id="belief_update")
    record.graph = GraphSnapshot(nodes=[GraphNodeSnapshot(title="Deploy", node_kind="topic", status="contradictory")])
    record.labels.belief_update = {"previous_text": "old", "updated_text": "new"}
    audited = audit_record(record, threshold=0.3)
    assert audited.quality.exportable or not audited.quality.contradiction_unresolved


def test_quality_audit_empty_record():
    record = AtulyaTrainingRecord(
        record_id="empty",
        forge_job_id="j",
        bank_id="b",
        recipe_id="consolidation_pairs",
        lineage=LineageBlock(recipe_id="consolidation_pairs"),
    )
    audited = audit_record(record)
    assert any("no facts" in i.lower() or "provenance" in i.lower() for i in audited.quality.issues)


def test_summarize_quality_includes_issue_counts():
    r1 = _sample_record(exportable=True)
    r1.quality.issues = ["issue a"]
    r2 = _sample_record(exportable=False)
    r2.quality.issues = ["issue a", "issue b"]
    summary = summarize_quality([r1, r2])
    assert summary["held_back"] == 1
    assert summary["issue_counts"]["issue a"] == 2


# --- Exporters ---


def test_atr_jsonl_exporter():
    records = [_sample_record(), _sample_record(exportable=False)]
    manifest = AtrJsonlExporter().export(records)
    assert manifest.record_count == 2
    assert manifest.content
    lines = [ln for ln in manifest.content.strip().split("\n") if ln]
    assert len(lines) == 2


def test_atr_jsonl_exporter_with_threshold():
    records = [_sample_record(exportable=True), _sample_record(exportable=False)]
    manifest = AtrJsonlExporter().export(records, options={"quality_threshold": 0.5})
    lines = [ln for ln in (manifest.content or "").strip().split("\n") if ln]
    assert manifest.exportable_count == 1
    assert len(lines) == 1


def test_openai_chat_exporter():
    record = _sample_record()
    record.labels.answer = "Assistant reply"
    record.tasks = [TrainingTask(task_type="qa", query="What do we know?")]
    manifest = OpenAIChatJsonlExporter().export([record])
    assert "messages" in manifest.content
    parsed = json.loads(manifest.content.strip().split("\n")[0])
    assert any(m["role"] == "assistant" for m in parsed["messages"])


def test_graph_intelligence_exporter_skips_non_graph():
    record = _sample_record()
    record.graph = None
    manifest = GraphIntelligenceJsonlExporter().export([record])
    assert manifest.exportable_count == 0
    assert manifest.content == ""


def test_graph_intelligence_exporter_with_graph():
    record = _sample_record()
    record.graph = GraphSnapshot(
        nodes=[GraphNodeSnapshot(title="Alice", node_kind="entity", status="stable")],
        change_events=[],
    )
    record.labels.expected_graph = {"node_titles": ["Alice"]}
    manifest = GraphIntelligenceJsonlExporter().export([record])
    assert manifest.content
    row = json.loads(manifest.content.strip())
    assert row["expected"]["node_titles"] == ["Alice"]


# --- Registry & metadata ---


def test_registry_lists_recipes_and_exporters():
    recipes = list_recipes()
    assert any(r["recipe_id"] == "consolidation_pairs" for r in recipes)
    assert recipes[0].get("title")
    assert get_recipe("graph_state").recipe_id == "graph_state"
    assert get_exporter("atr_jsonl").adapter_id == "atr_jsonl"
    assert "temporal_qa" in suggest_recipes(["startup_ops"])


def test_catalog_payload_has_profiles_and_stages():
    catalog = forge_catalog_payload(["family_office"])
    assert catalog["domain_profiles"]
    assert catalog["stages"]
    assert "belief_update" in catalog["suggested_recipes"]


def test_all_recipes_have_metadata():
    for recipe_id in (
        "consolidation_pairs",
        "temporal_qa",
        "agent_trace",
        "graph_state",
        "belief_update",
        "synthetic_expand",
    ):
        assert recipe_id in RECIPE_METADATA
        assert RECIPE_METADATA[recipe_id].get("title")


def test_domain_profiles_suggestions_match_registry():
    for tag, profile in DOMAIN_PROFILES.items():
        suggested = suggest_recipes([tag])
        for recipe in profile.get("suggested_recipes", []):
            if recipe in RECIPE_METADATA:
                assert recipe in suggested


# --- Job flow (mocked) ---


@pytest.mark.asyncio
async def test_run_forge_job_validates_before_retain():
    from atulya_api.forge.job import run_forge_job
    from atulya_api.models import RequestContext

    memory = MagicMock()
    memory.retain_batch_async = AsyncMock()
    memory.submit_async_consolidation = AsyncMock()
    memory.get_bank_stats = AsyncMock(return_value={"pending_consolidation": 0})

    request = ForgeJobRequest(
        recipe_id="consolidation_pairs",
        source=None,
    )
    ctx = RequestContext(internal=True)

    with patch("atulya_api.forge.job.get_recipe") as mock_get:
        mock_recipe = MagicMock()
        mock_recipe.run = AsyncMock(return_value=MagicMock(records=[]))
        mock_get.return_value = mock_recipe

        result = await run_forge_job(
            memory,
            "bank-1",
            request,
            operation_id="op-1",
            request_context=ctx,
        )

    assert result["records_total"] == 0
    memory.retain_batch_async.assert_not_called()


@pytest.mark.asyncio
async def test_run_forge_job_ingests_when_source_provided():
    from atulya_api.forge.job import run_forge_job
    from atulya_api.models import RequestContext

    memory = MagicMock()
    memory.retain_batch_async = AsyncMock()
    memory.submit_async_consolidation = AsyncMock()
    memory.get_bank_stats = AsyncMock(return_value={"pending_consolidation": 0})

    request = ForgeJobRequest(
        recipe_id="consolidation_pairs",
        source=ForgeIngestSource(
            source_type="scenario",
            payload={
                "scenarios": [
                    {
                        "id": "t1",
                        "facts": [
                            {
                                "id": "f1",
                                "key": "k",
                                "value": "v",
                                "timestamp": "2026-01-05T09:00:00Z",
                            }
                        ],
                    }
                ]
            },
        ),
        wait_consolidation=False,
    )
    ctx = RequestContext(internal=True)

    with patch("atulya_api.forge.job.get_recipe") as mock_get:
        mock_recipe = MagicMock()
        mock_recipe.run = AsyncMock(return_value=MagicMock(records=[_sample_record()]))
        mock_get.return_value = mock_recipe

        result = await run_forge_job(
            memory,
            "bank-1",
            request,
            operation_id="op-2",
            request_context=ctx,
        )

    memory.retain_batch_async.assert_called_once()
    assert result["records_total"] == 1
    assert result["records_exportable"] >= 0
