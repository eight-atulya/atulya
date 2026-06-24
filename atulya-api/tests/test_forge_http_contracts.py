"""HTTP route contract checks for Forge and Taste surfaces."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from atulya_api.api.http import ConsolidationResponse, create_app


def _mock_memory() -> MagicMock:
    memory = MagicMock()
    memory.close = AsyncMock()
    return memory


def _route_by_operation_id(app, operation_id: str):
    for route in app.routes:
        if getattr(route, "operation_id", None) == operation_id:
            return route
    raise AssertionError(f"Route not found: {operation_id}")


def test_taste_mixed_sync_async_routes_do_not_force_consolidation_response_model():
    app = create_app(_mock_memory(), initialize_memory=False, http_extension=None)

    generate_route = _route_by_operation_id(app, "generate_taste_variants")
    transform_route = _route_by_operation_id(app, "submit_taste_transform")

    assert generate_route.response_model is not ConsolidationResponse
    assert transform_route.response_model is not ConsolidationResponse


def test_async_only_submission_routes_keep_consolidation_response_model():
    app = create_app(_mock_memory(), initialize_memory=False, http_extension=None)

    forge_route = _route_by_operation_id(app, "submit_forge_job")
    consolidate_route = _route_by_operation_id(app, "trigger_consolidation")

    assert forge_route.response_model is ConsolidationResponse
    assert consolidate_route.response_model is ConsolidationResponse


def test_taste_routes_have_single_openapi_tag_for_client_generation():
    app = create_app(_mock_memory(), initialize_memory=False, http_extension=None)

    taste_route = _route_by_operation_id(app, "generate_taste_variants")
    forge_route = _route_by_operation_id(app, "submit_forge_job")

    assert taste_route.tags == ["Taste"]
    assert forge_route.tags == ["Forge"]


def test_taste_generate_route_returns_immediate_variant_payload():
    memory = _mock_memory()
    memory.submit_taste_generate = AsyncMock(
        return_value={
            "created_count": 1,
            "sets": [{"id": "set-variant", "set_key": "set_0001", "variant_index": 1}],
            "parent_count": 1,
            "count_per_parent": 1,
        }
    )
    app = create_app(memory, initialize_memory=False, http_extension=None)

    response = TestClient(app).post(
        "/v1/default/banks/bank-1/forge/taste/datasets/dataset-1/generate",
        json={"set_ids": ["set-1"], "count": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["created_count"] == 1
    assert payload["sets"][0]["id"] == "set-variant"


def test_taste_generate_route_returns_async_operation_payload():
    memory = _mock_memory()
    memory.submit_taste_generate = AsyncMock(return_value={"operation_id": "op-1", "deduplicated": False})
    app = create_app(memory, initialize_memory=False, http_extension=None)

    response = TestClient(app).post(
        "/v1/default/banks/bank-1/forge/taste/datasets/dataset-1/generate",
        json={"set_ids": ["set-1"], "count": 16},
    )

    assert response.status_code == 200
    assert response.json() == {"operation_id": "op-1", "deduplicated": False}
