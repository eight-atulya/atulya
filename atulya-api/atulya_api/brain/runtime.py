"""
Runtime bridge for atulya-brain.

This runtime is intentionally fail-safe:
- PostgreSQL remains source of truth
- `.atulya` files are derived cache artifacts
- failures do not block core memory operations
"""

from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .activity_models import build_histogram, build_hmm, build_kalman, merge_activity_models
from .models import (
    BrainCompatibilityReport,
    BrainSnapshot,
    decode_brain_file,
    encode_brain_file,
    validate_brain_file,
)
from .remote import LearningType, RemoteBrainPayload, RemoteBrainSource, fetch_remote_brain

logger = logging.getLogger(__name__)

SubRoutineMode = Literal["warmup", "incremental", "full_copy"]


@dataclass(slots=True)
class BrainRuntimeConfig:
    enabled: bool
    cache_dir: str
    default_file_name: str
    native_library_path: str | None
    circuit_breaker_threshold: int
    max_file_size_bytes: int = 50 * 1024 * 1024
    hardware_tier: Literal["low", "balanced", "high"] = "balanced"
    prediction_mode: Literal["histogram", "kalman_lite", "hmm_lite"] = "histogram"


class AtulyaBrainRuntime:
    """Runtime manager for brain.atulya cache and sub_routine execution."""

    def __init__(self, config: BrainRuntimeConfig):
        self._config = config
        self._failure_count = 0
        self._circuit_open = False
        self._native = None
        self._metrics: Counter[str] = Counter()
        if self._config.enabled:
            self._native = self._load_native_library(config.native_library_path)

    @property
    def enabled(self) -> bool:
        return self._config.enabled and not self._circuit_open

    def _load_native_library(self, path: str | None):
        if not path:
            return None
        try:
            lib = ctypes.CDLL(path)
            logger.info("Loaded atulya-brain native library from %s", path)
            return lib
        except Exception as exc:
            logger.warning("Failed to load atulya-brain native library from %s: %s", path, exc)
            return None

    def _mark_failure(self, error: Exception):
        self._failure_count += 1
        self._metrics["runtime_failures"] += 1
        logger.warning("atulya-brain runtime error (%d): %s", self._failure_count, error)
        if self._failure_count >= self._config.circuit_breaker_threshold:
            self._circuit_open = True
            self._metrics["circuit_breaker_open"] += 1
            logger.error("atulya-brain circuit breaker opened after %d failures", self._failure_count)

    def _brain_path(self, bank_id: str) -> Path:
        base = Path(self._config.cache_dir).expanduser().resolve()
        safe_bank = bank_id.replace("/", "_")
        file_name = self._config.default_file_name if safe_bank == "default" else f"{safe_bank}.atulya"
        return base / file_name

    def _snapshot_id(self, bank_id: str, mental_models: list[dict[str, Any]], full_copy: list[dict[str, Any]]) -> str:
        digest = hashlib.sha256()
        digest.update(bank_id.encode("utf-8"))
        digest.update(str(len(mental_models)).encode("utf-8"))
        digest.update(str(len(full_copy)).encode("utf-8"))
        if mental_models:
            digest.update(str(mental_models[0].get("id", "")).encode("utf-8"))
        if full_copy:
            digest.update(str(full_copy[0].get("id", "")).encode("utf-8"))
        return digest.hexdigest()

    def _budget_for_tier(self) -> tuple[int, int]:
        if self._config.hardware_tier == "low":
            return 100, 100
        if self._config.hardware_tier == "high":
            return 400, 1000
        return 200, 500

    def _build_activity_model(
        self,
        events: list[datetime],
        *,
        prior: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._config.prediction_mode == "kalman_lite":
            return build_kalman(events, prior=prior)
        if self._config.prediction_mode == "hmm_lite":
            return build_hmm(events, prior=prior)
        return build_histogram(events)

    def _write_snapshot_atomic(self, path: Path, snapshot: BrainSnapshot) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = encode_brain_file(snapshot)
        if len(blob) > self._config.max_file_size_bytes:
            raise ValueError(
                f"brain snapshot too large ({len(blob)} bytes > {self._config.max_file_size_bytes} bytes max)"
            )
        with tempfile.NamedTemporaryFile("wb", delete=False, dir=path.parent, prefix=".brain-", suffix=".tmp") as tmp:
            tmp.write(blob)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)

    async def build_or_refresh(
        self,
        bank_id: str,
        *,
        mental_models: list[dict[str, Any]],
        full_copy: list[dict[str, Any]],
        events: list[datetime],
        mode: SubRoutineMode,
    ) -> dict[str, Any]:
        """
        Build or refresh `.atulya` cache for one bank.
        """
        if not self.enabled:
            return {"enabled": False, "reason": "disabled_or_circuit_open"}
        try:
            self._metrics["build_total"] += 1
            path = self._brain_path(bank_id)
            model_budget, copy_budget = self._budget_for_tier()
            bounded_mental_models = mental_models[:model_budget]
            bounded_full_copy = full_copy[:copy_budget]
            source_snapshot_id = self._snapshot_id(bank_id, mental_models, full_copy)
            snapshot = BrainSnapshot(
                bank_id=bank_id,
                generated_at=datetime.now(UTC).isoformat(),
                source_snapshot_id=source_snapshot_id,
                mental_models=bounded_mental_models,
                full_copy=bounded_full_copy if mode == "full_copy" else [],
                sub_conscious_memory={
                    "mode": mode,
                    "mental_model_count": len(bounded_mental_models),
                    "full_copy_count": len(bounded_full_copy),
                    "hardware_tier": self._config.hardware_tier,
                    "prediction_mode": self._config.prediction_mode,
                },
                activity_model=self._build_activity_model(events),
                model_signature=f"{self._config.prediction_mode}-v1",
                source_count=len(events),
            )
            self._write_snapshot_atomic(path, snapshot)
            self._metrics["build_success"] += 1
            return {
                "enabled": True,
                "bank_id": bank_id,
                "file_path": str(path),
                "source_snapshot_id": source_snapshot_id,
                "mental_model_count": len(snapshot.mental_models),
                "full_copy_count": len(snapshot.full_copy),
                "native_library_loaded": self._native is not None,
            }
        except Exception as exc:
            self._mark_failure(exc)
            self._metrics["build_failed"] += 1
            raise

    async def get_status(self, bank_id: str) -> dict[str, Any]:
        path = self._brain_path(bank_id)
        exists = path.exists()
        snapshot_id = None
        generated_at = None
        model_signature = None
        format_version = None
        compatibility: BrainCompatibilityReport | None = None
        if exists:
            try:
                raw = path.read_bytes()
                compatibility = validate_brain_file(raw)
                if compatibility.valid:
                    snapshot = decode_brain_file(raw)
                    format_version = compatibility.version
                else:
                    snapshot = None
                    logger.warning(
                        "Brain cache validation failed for bank %s: %s",
                        bank_id,
                        compatibility.reason,
                    )
                if snapshot is not None:
                    snapshot_id = snapshot.source_snapshot_id
                    generated_at = snapshot.generated_at
                    model_signature = snapshot.model_signature
            except Exception as exc:
                logger.warning("Failed to decode brain cache file for %s: %s", bank_id, exc)
        return {
            "enabled": self._config.enabled,
            "circuit_open": self._circuit_open,
            "failure_count": self._failure_count,
            "bank_id": bank_id,
            "file_path": str(path),
            "exists": exists,
            "size_bytes": path.stat().st_size if exists else 0,
            "last_modified_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat() if exists else None,
            "source_snapshot_id": snapshot_id,
            "generated_at": generated_at,
            "native_library_loaded": self._native is not None,
            "format_version": format_version,
            "model_signature": model_signature,
            "compatibility_reason": None if compatibility is None or compatibility.valid else compatibility.reason,
            "metrics": dict(self._metrics),
        }

    async def predict_activity_time(self, bank_id: str, horizon_hours: int = 24) -> dict[str, Any]:
        status = await self.get_status(bank_id)
        if not status["exists"]:
            return {"bank_id": bank_id, "horizon_hours": horizon_hours, "predictions": []}
        snapshot = decode_brain_file(Path(status["file_path"]).read_bytes())
        histogram = snapshot.activity_model.get("hourly_histogram", {})
        sorted_hours = sorted(histogram.items(), key=lambda x: x[1], reverse=True)
        top = sorted_hours[: min(5, len(sorted_hours))]
        return {
            "bank_id": bank_id,
            "horizon_hours": horizon_hours,
            "predictions": [{"hour_utc": int(hour), "score": score} for hour, score in top],
            "sample_count": snapshot.activity_model.get("sample_count", 0),
            "source_snapshot_id": snapshot.source_snapshot_id,
            "model_signature": snapshot.model_signature,
        }

    async def get_activity_histogram(self, bank_id: str) -> dict[str, Any]:
        status = await self.get_status(bank_id)
        if not status["exists"]:
            return {
                "bank_id": bank_id,
                "histogram": [{"hour_utc": hour, "score": 0.0} for hour in range(24)],
                "sample_count": 0,
                "source_snapshot_id": None,
                "model_signature": None,
            }
        snapshot = decode_brain_file(Path(status["file_path"]).read_bytes())
        raw_histogram = snapshot.activity_model.get("hourly_histogram", {})
        histogram = []
        for hour in range(24):
            value = raw_histogram.get(str(hour), raw_histogram.get(hour, 0.0))
            try:
                score = float(value)
            except (TypeError, ValueError):
                score = 0.0
            histogram.append({"hour_utc": hour, "score": score})
        return {
            "bank_id": bank_id,
            "histogram": histogram,
            "sample_count": snapshot.activity_model.get("sample_count", 0),
            "source_snapshot_id": snapshot.source_snapshot_id,
            "model_signature": snapshot.model_signature,
        }

    async def export_snapshot(self, bank_id: str) -> bytes:
        path = self._brain_path(bank_id)
        if not path.exists():
            raise FileNotFoundError(f"brain cache not found for bank {bank_id}")
        raw = path.read_bytes()
        report = validate_brain_file(raw)
        if not report.valid:
            raise ValueError(f"invalid brain file: {report.reason}")
        return raw

    async def validate_import_payload(self, raw: bytes) -> BrainCompatibilityReport:
        if len(raw) > self._config.max_file_size_bytes:
            return BrainCompatibilityReport(
                valid=False,
                version=None,
                reason=f"file too large ({len(raw)} bytes > {self._config.max_file_size_bytes} bytes max)",
            )
        return validate_brain_file(raw)

    async def import_snapshot(self, bank_id: str, raw: bytes) -> dict[str, Any]:
        report = await self.validate_import_payload(raw)
        if not report.valid:
            raise ValueError(report.reason or "invalid brain file")
        snapshot = decode_brain_file(raw)
        if snapshot.bank_id and snapshot.bank_id != bank_id:
            raise ValueError(f"brain file bank mismatch: expected {bank_id}, got {snapshot.bank_id}")
        path = self._brain_path(bank_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "wb", delete=False, dir=path.parent, prefix=".brain-import-", suffix=".tmp"
        ) as tmp:
            tmp.write(raw)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)
        self._metrics["import_success"] += 1
        return {
            "bank_id": bank_id,
            "file_path": str(path),
            "size_bytes": len(raw),
            "format_version": report.version,
        }

    async def delete_snapshot(self, bank_id: str) -> dict[str, Any]:
        """Delete derived .brain cache file for a bank, if present."""
        path = self._brain_path(bank_id)
        if not path.exists():
            return {"bank_id": bank_id, "deleted": False, "file_path": str(path)}
        path.unlink()
        self._metrics["delete_snapshot"] += 1
        return {"bank_id": bank_id, "deleted": True, "file_path": str(path)}

    async def learn_from_remote(
        self,
        bank_id: str,
        *,
        remote_endpoint: str,
        remote_bank_id: str,
        remote_api_key: str = "",
        local_mental_models: list[dict[str, Any]],
        local_full_copy: list[dict[str, Any]],
        local_events: list[datetime],
        learning_type: LearningType = "auto",
        mode: SubRoutineMode = "incremental",
    ) -> dict[str, Any]:
        """
        Learn from a remote brain: fetch its knowledge, merge with local
        data, build a fused activity model, and write the combined snapshot.

        This is the core brain-to-brain knowledge transfer pipeline:
        1. Connect to remote Atulya API, extract mental models + memories
        2. If remote has a .brain export, decode and use its activity model as prior
        3. Merge remote + local mental models (dedup by content hash)
        4. Build fused activity model using Kalman/HMM with remote as prior
        5. Write merged snapshot
        """
        if not self.enabled:
            return {"enabled": False, "reason": "disabled_or_circuit_open"}

        self._metrics["learn_total"] += 1
        try:
            model_budget, copy_budget = self._budget_for_tier()
            source = RemoteBrainSource(
                endpoint_url=remote_endpoint,
                bank_id=remote_bank_id,
                api_key=remote_api_key,
                label=f"learn:{remote_endpoint}",
            )
            remote = await fetch_remote_brain(
                source,
                model_limit=model_budget,
                memory_limit=copy_budget,
                learning_type=learning_type,
            )

            remote_prior: dict[str, Any] | None = None
            remote_snapshot: BrainSnapshot | None = None
            if remote.brain_snapshot_raw:
                try:
                    remote_snapshot = decode_brain_file(remote.brain_snapshot_raw)
                    remote_prior = remote_snapshot.activity_model
                    logger.info("[BRAIN_LEARN] Using remote .brain activity model as prior")
                except Exception as exc:
                    logger.warning("[BRAIN_LEARN] Could not decode remote .brain: %s", exc)

            seen_ids: set[str] = set()
            merged_models: list[dict[str, Any]] = []
            for model in local_mental_models:
                mid = str(model.get("id", ""))
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    merged_models.append(model)

            remote_models = remote.mental_models
            if remote_snapshot:
                remote_models = remote_snapshot.mental_models + remote_models
            for model in remote_models:
                mid = str(model.get("id", model.get("title", "")))
                content_key = hashlib.sha256(str(model.get("content", model.get("text", ""))).encode()).hexdigest()[:16]
                dedup_key = mid or content_key
                if dedup_key not in seen_ids:
                    seen_ids.add(dedup_key)
                    merged_models.append(model)

            all_events = list(local_events) + list(remote.events)
            if remote_snapshot:
                pass

            existing_prior = None
            path = self._brain_path(bank_id)
            if path.exists():
                try:
                    existing_snapshot = decode_brain_file(path.read_bytes())
                    existing_prior = existing_snapshot.activity_model
                except Exception:
                    pass

            final_prior = remote_prior
            if existing_prior and final_prior:
                final_prior = merge_activity_models(existing_prior, final_prior)
            elif existing_prior:
                final_prior = existing_prior

            merged_full_copy: list[dict[str, Any]] = []
            if mode == "full_copy":
                seen_copy_ids: set[str] = set()
                for item in local_full_copy:
                    iid = str(item.get("id", ""))
                    if iid and iid not in seen_copy_ids:
                        seen_copy_ids.add(iid)
                        merged_full_copy.append(item)
                for item in remote.memories:
                    iid = str(item.get("id", ""))
                    if iid and iid not in seen_copy_ids:
                        seen_copy_ids.add(iid)
                        merged_full_copy.append(item)

            bounded_models = merged_models[:model_budget]
            bounded_copy = merged_full_copy[:copy_budget]
            source_snapshot_id = self._snapshot_id(bank_id, bounded_models, bounded_copy)

            snapshot = BrainSnapshot(
                bank_id=bank_id,
                generated_at=datetime.now(UTC).isoformat(),
                source_snapshot_id=source_snapshot_id,
                mental_models=bounded_models,
                full_copy=bounded_copy if mode == "full_copy" else [],
                sub_conscious_memory={
                    "mode": mode,
                    "mental_model_count": len(bounded_models),
                    "full_copy_count": len(bounded_copy),
                    "hardware_tier": self._config.hardware_tier,
                    "prediction_mode": self._config.prediction_mode,
                    "learned_from": {
                        "endpoint": remote_endpoint,
                        "bank_id": remote_bank_id,
                        "remote_models": len(remote.mental_models),
                        "remote_memories": len(remote.memories),
                        "remote_entities": len(remote.entities),
                        "remote_brain_available": remote.brain_snapshot_raw is not None,
                        "fetched_at": remote.fetched_at,
                        "learning_type_requested": learning_type,
                        "learning_type_effective": remote.learning_type_effective,
                        "capabilities": remote.capabilities,
                        "errors": remote.errors,
                    },
                },
                activity_model=self._build_activity_model(all_events, prior=final_prior),
                model_signature=f"{self._config.prediction_mode}-v1",
                source_count=len(all_events),
            )
            self._write_snapshot_atomic(path, snapshot)
            self._metrics["learn_success"] += 1

            return {
                "enabled": True,
                "bank_id": bank_id,
                "file_path": str(path),
                "source_snapshot_id": source_snapshot_id,
                "local_model_count": len(local_mental_models),
                "remote_model_count": len(remote.mental_models),
                "merged_model_count": len(bounded_models),
                "remote_memory_count": len(remote.memories),
                "remote_entity_count": len(remote.entities),
                "total_events": len(all_events),
                "remote_brain_used": remote.brain_snapshot_raw is not None,
                "learning_type_requested": learning_type,
                "learning_type_effective": remote.learning_type_effective,
                "remote_capabilities": remote.capabilities,
                "errors": remote.errors,
                "_remote_memories": remote.memories,
                "_remote_mental_models": remote.mental_models,
                "_remote_entities": remote.entities,
            }
        except Exception as exc:
            self._mark_failure(exc)
            self._metrics["learn_failed"] += 1
            raise
