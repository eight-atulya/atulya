import time
from datetime import UTC, datetime

import pytest

from atulya_api.brain.models import BrainSnapshot, decode_brain_file, encode_brain_file, validate_brain_file
from atulya_api.brain.runtime import AtulyaBrainRuntime, BrainRuntimeConfig


def test_brain_binary_roundtrip():
    snapshot = BrainSnapshot(
        bank_id="bank-a",
        generated_at=datetime.now(UTC).isoformat(),
        source_snapshot_id="snap-1",
        mental_models=[{"id": "m1", "content": "model"}],
        full_copy=[],
        sub_conscious_memory={"mode": "incremental"},
        activity_model={"hourly_histogram": {"12": 1.0}, "sample_count": 1},
    )
    blob = encode_brain_file(snapshot)
    parsed = decode_brain_file(blob)
    assert parsed.bank_id == "bank-a"
    assert parsed.source_snapshot_id == "snap-1"
    assert parsed.sub_conscious_memory["mode"] == "incremental"
    assert parsed.model_signature == "histogram-v1"
    report = validate_brain_file(blob)
    assert report.valid is True


@pytest.mark.asyncio
async def test_runtime_build_status_and_prediction(tmp_path):
    runtime = AtulyaBrainRuntime(
        BrainRuntimeConfig(
            enabled=True,
            cache_dir=str(tmp_path),
            default_file_name="brain.atulya",
            native_library_path=None,
            circuit_breaker_threshold=3,
        )
    )
    now = datetime.now(UTC)
    result = await runtime.build_or_refresh(
        "bank-a",
        mental_models=[{"id": "m1"}],
        full_copy=[{"id": "f1"}],
        events=[now],
        mode="full_copy",
    )
    assert result["enabled"] is True
    status = await runtime.get_status("bank-a")
    assert status["exists"] is True
    assert status["size_bytes"] > 0
    assert status["format_version"] == 2
    predictions = await runtime.predict_activity_time("bank-a", horizon_hours=24)
    assert predictions["bank_id"] == "bank-a"
    assert isinstance(predictions["predictions"], list)
    assert predictions["model_signature"] == "histogram-v1"


@pytest.mark.asyncio
async def test_runtime_circuit_breaker_opens_after_threshold(tmp_path, monkeypatch):
    runtime = AtulyaBrainRuntime(
        BrainRuntimeConfig(
            enabled=True,
            cache_dir=str(tmp_path),
            default_file_name="brain.atulya",
            native_library_path=None,
            circuit_breaker_threshold=2,
        )
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("disk write failed")

    monkeypatch.setattr(runtime, "_write_snapshot_atomic", _boom)

    with pytest.raises(RuntimeError):
        await runtime.build_or_refresh("bank-a", mental_models=[], full_copy=[], events=[], mode="incremental")
    with pytest.raises(RuntimeError):
        await runtime.build_or_refresh("bank-a", mental_models=[], full_copy=[], events=[], mode="incremental")

    assert runtime.enabled is False


@pytest.mark.asyncio
async def test_runtime_import_export_and_validation(tmp_path):
    runtime = AtulyaBrainRuntime(
        BrainRuntimeConfig(
            enabled=True,
            cache_dir=str(tmp_path),
            default_file_name="brain.atulya",
            native_library_path=None,
            circuit_breaker_threshold=3,
            max_file_size_bytes=1024 * 1024,
        )
    )
    now = datetime.now(UTC)
    await runtime.build_or_refresh(
        "bank-a",
        mental_models=[{"id": "m1"}],
        full_copy=[],
        events=[now],
        mode="incremental",
    )
    exported = await runtime.export_snapshot("bank-a")
    report = await runtime.validate_import_payload(exported)
    assert report.valid is True
    imported = await runtime.import_snapshot("bank-a", exported)
    assert imported["bank_id"] == "bank-a"
    assert imported["size_bytes"] > 0


def test_legacy_v1_decode_supported():
    snapshot = BrainSnapshot.empty("bank-v1", "snap-v1")
    blob = encode_brain_file(snapshot, version=1)
    parsed = decode_brain_file(blob)
    assert parsed.bank_id == "bank-v1"


@pytest.mark.asyncio
async def test_runtime_perf_smoke(tmp_path):
    runtime = AtulyaBrainRuntime(
        BrainRuntimeConfig(
            enabled=True,
            cache_dir=str(tmp_path),
            default_file_name="brain.atulya",
            native_library_path=None,
            circuit_breaker_threshold=3,
        )
    )
    mental_models = [{"id": f"m{i}", "content": "x" * 128} for i in range(200)]
    full_copy = [{"id": f"f{i}", "text": "y" * 256, "type": "world"} for i in range(500)]
    events = [datetime.now(UTC) for _ in range(200)]

    start = time.perf_counter()
    await runtime.build_or_refresh(
        "bank-perf",
        mental_models=mental_models,
        full_copy=full_copy,
        events=events,
        mode="incremental",
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    # Performance guardrail: this is a smoke benchmark, not a hard SLA.
    assert elapsed_ms < 2000
