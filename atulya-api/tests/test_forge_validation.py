"""Validation and error-path tests for Data Forge."""

from __future__ import annotations

import pytest

from atulya_api.forge.adapters.chat import ForgeChatAdapter
from atulya_api.forge.adapters.scenario import ForgeScenarioAdapter
from atulya_api.forge.adapters.timeseries import ForgeTimeSeriesAdapter
from atulya_api.forge.engine import _parse_operation_uuid
from atulya_api.forge.errors import ForgeExportError, ForgeValidationError
from atulya_api.forge.job import parse_forge_request
from atulya_api.forge.models import ForgeExportRequest, ForgeIngestSource, ForgeJobRequest
from atulya_api.forge.registry import get_exporter, get_recipe
from atulya_api.forge.validation import (
    normalize_ingest_source_sync,
    validate_export_request,
    validate_forge_job_request,
    validate_ingest_source,
)


def test_unknown_source_type_raises():
    with pytest.raises(ForgeValidationError) as exc:
        validate_ingest_source({"source_type": "rss_feed", "payload": {}})
    assert exc.value.field == "source.source_type"
    assert "rss_feed" in exc.value.message


def test_empty_sessions_raises():
    with pytest.raises(ForgeValidationError) as exc:
        validate_ingest_source({"source_type": "sessions", "payload": {"sessions": []}})
    assert "empty" in exc.value.message.lower()


def test_chat_missing_shape_raises():
    with pytest.raises(ForgeValidationError):
        validate_ingest_source({"source_type": "chat", "payload": {"foo": "bar"}})


def test_chat_bad_turn_raises():
    adapter = ForgeChatAdapter()
    with pytest.raises(ValueError, match="Unsupported turn"):
        adapter.normalize({"turns": [{"foo": "bar"}]})


def test_timeseries_empty_rows_produces_nothing():
    with pytest.raises(ForgeValidationError):
        validate_ingest_source({"source_type": "timeseries", "payload": {"rows": []}})


def test_timeseries_csv_text():
    adapter = ForgeTimeSeriesAdapter()
    items = adapter.normalize(
        {
            "csv_text": "key,value,timestamp\nrate,5%,2026-01-01\n",
            "key_field": "key",
            "value_field": "value",
        }
    )
    assert len(items) == 1
    assert "rate" in items[0]["content"]


def test_scenario_empty_facts_skipped():
    adapter = ForgeScenarioAdapter()
    items = adapter.normalize({"scenarios": [{"id": "x", "facts": []}]})
    assert items == []


def test_bank_only_source_allowed():
    items = validate_ingest_source(ForgeIngestSource(source_type="bank_only", payload={}))
    assert items == []


def test_synthetic_expand_requires_source_or_options():
    with pytest.raises(ForgeValidationError):
        validate_forge_job_request(ForgeJobRequest(recipe_id="synthetic_expand", domain_tags=["synthetic"]))


def test_synthetic_expand_with_scenario_payload_in_options():
    items = validate_forge_job_request(
        ForgeJobRequest(
            recipe_id="synthetic_expand",
            options={"scenario_payload": {"scenarios": [{"id": "s", "facts": []}]}},
        )
    )
    assert items == []


def test_consolidation_pairs_bank_only_ok():
    items = validate_forge_job_request(ForgeJobRequest(recipe_id="consolidation_pairs", source=None))
    assert items == []


def test_unknown_recipe_raises():
    request = ForgeJobRequest.model_construct(recipe_id="not_a_recipe")
    with pytest.raises(ForgeValidationError):
        validate_forge_job_request(request)


def test_parse_forge_request_invalid():
    with pytest.raises(ForgeValidationError):
        parse_forge_request({"recipe_id": 123})


def test_parse_operation_uuid_invalid_raises_validation_error():
    with pytest.raises(ForgeValidationError) as exc:
        _parse_operation_uuid("not-a-uuid")

    assert exc.value.field == "operation_id"
    assert exc.value.details == {"operation_id": "not-a-uuid"}


def test_export_no_records_raises():
    with pytest.raises(ForgeExportError, match="No training records"):
        validate_export_request(
            ForgeExportRequest(operation_id="00000000-0000-0000-0000-000000000001"),
            record_count=0,
            exportable_count=0,
        )


def test_export_threshold_blocks_all():
    with pytest.raises(ForgeExportError, match="quality threshold"):
        validate_export_request(
            ForgeExportRequest(
                operation_id="00000000-0000-0000-0000-000000000001",
                quality_threshold=0.9,
            ),
            record_count=5,
            exportable_count=0,
        )


def test_get_recipe_unknown():
    with pytest.raises(ValueError, match="Unknown forge recipe"):
        get_recipe("missing_recipe")


def test_get_exporter_unknown():
    with pytest.raises(ValueError, match="Unknown forge exporter"):
        get_exporter("missing_exporter")


def test_normalize_ingest_bank_only():
    assert normalize_ingest_source_sync({"source_type": "bank_only", "payload": {}}) == []


def test_scenario_valid_ingest():
    items = validate_ingest_source(
        {
            "source_type": "scenario",
            "payload": {
                "scenarios": [
                    {
                        "id": "t1",
                        "facts": [
                            {
                                "id": "f1",
                                "key": "region",
                                "value": "us-east-1",
                                "timestamp": "2026-01-05T09:00:00Z",
                            }
                        ],
                    }
                ]
            },
        }
    )
    assert len(items) == 1


def test_get_recipe_returns_instance():
    recipe = get_recipe("consolidation_pairs")
    assert recipe.recipe_id == "consolidation_pairs"
