"""
Binary schema and payload contracts for atulya-brain.

This module defines a compact, versioned container format for `.atulya` brain files.
The file remains a derived cache and is always reproducible from PostgreSQL state.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict

MAGIC = b"ATULYA\0\1"
LEGACY_FORMAT_VERSION = 1
FORMAT_VERSION = 2
HEADER_STRUCT = struct.Struct(">8sHIII")
SUPPORTED_VERSIONS = (LEGACY_FORMAT_VERSION, FORMAT_VERSION)


class SubRoutineTaskPayload(TypedDict, total=False):
    """Serialized payload for sub_routine task execution."""

    bank_id: str
    mode: Literal["warmup", "incremental", "full_copy"]
    force_rebuild: bool
    horizon_hours: int
    _tenant_id: str
    _api_key_id: str


@dataclass(slots=True)
class BrainHeader:
    """Header metadata for `.atulya` binary files."""

    magic: bytes
    version: int
    payload_len: int
    payload_crc32: int
    reserved: int = 0

    def to_bytes(self) -> bytes:
        return HEADER_STRUCT.pack(self.magic, self.version, self.payload_len, self.payload_crc32, self.reserved)

    @classmethod
    def from_bytes(cls, raw: bytes) -> "BrainHeader":
        if len(raw) < HEADER_STRUCT.size:
            raise ValueError("invalid brain file header: too short")
        magic, version, payload_len, payload_crc32, reserved = HEADER_STRUCT.unpack(raw[: HEADER_STRUCT.size])
        return cls(
            magic=magic,
            version=version,
            payload_len=payload_len,
            payload_crc32=payload_crc32,
            reserved=reserved,
        )


@dataclass(slots=True)
class BrainSnapshot:
    """
    Typed in-memory representation of a brain cache payload.

    Sections:
    - mental_models: copied/summarized mental-model content
    - full_copy: optional full memory copy for exact inheritance
    - sub_conscious_memory: compact pattern data for fast routine reasoning
    """

    bank_id: str
    generated_at: str
    source_snapshot_id: str
    mental_models: list[dict[str, Any]]
    full_copy: list[dict[str, Any]]
    sub_conscious_memory: dict[str, Any]
    activity_model: dict[str, Any]
    model_signature: str = "histogram-v1"
    source_count: int = 0
    file_checksum_sha256: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "bank_id": self.bank_id,
            "generated_at": self.generated_at,
            "source_snapshot_id": self.source_snapshot_id,
            "mental_models": self.mental_models,
            "full_copy": self.full_copy,
            "sub_conscious_memory": self.sub_conscious_memory,
            "activity_model": self.activity_model,
            "model_signature": self.model_signature,
            "source_count": self.source_count,
            "file_checksum_sha256": self.file_checksum_sha256,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "BrainSnapshot":
        return cls(
            bank_id=str(payload.get("bank_id", "")),
            generated_at=str(payload.get("generated_at", "")),
            source_snapshot_id=str(payload.get("source_snapshot_id", "")),
            mental_models=list(payload.get("mental_models", [])),
            full_copy=list(payload.get("full_copy", [])),
            sub_conscious_memory=dict(payload.get("sub_conscious_memory", {})),
            activity_model=dict(payload.get("activity_model", {})),
            model_signature=str(payload.get("model_signature", "histogram-v1")),
            source_count=int(payload.get("source_count", 0)),
            file_checksum_sha256=str(payload.get("file_checksum_sha256", "")),
        )

    @classmethod
    def empty(cls, bank_id: str, source_snapshot_id: str) -> "BrainSnapshot":
        now = datetime.now(UTC).isoformat()
        return cls(
            bank_id=bank_id,
            generated_at=now,
            source_snapshot_id=source_snapshot_id,
            mental_models=[],
            full_copy=[],
            sub_conscious_memory={},
            activity_model={},
            model_signature="histogram-v1",
            source_count=0,
            file_checksum_sha256="",
        )


def _canonicalize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _canonicalize(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, list):
        return [_canonicalize(v) for v in obj]
    return obj


def _to_canonical_json(payload: dict[str, Any]) -> bytes:
    canonical = _canonicalize(payload)
    return json.dumps(
        canonical,
        separators=(",", ":"),
        ensure_ascii=True,
        sort_keys=True,
    ).encode("utf-8")


@dataclass(slots=True)
class BrainCompatibilityReport:
    valid: bool
    version: int | None
    reason: str | None = None


def _encode_payload(snapshot: BrainSnapshot, include_hash: bool) -> bytes:
    payload = snapshot.to_payload()
    if include_hash:
        payload["file_checksum_sha256"] = ""
        raw = _to_canonical_json(payload)
        payload["file_checksum_sha256"] = hashlib.sha256(raw).hexdigest()
        return _to_canonical_json(payload)
    return _to_canonical_json(payload)


def encode_brain_file(snapshot: BrainSnapshot, *, version: int = FORMAT_VERSION) -> bytes:
    """Encode a snapshot into a versioned `.atulya` binary blob."""
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"unsupported brain file version: {version}")
    payload_raw = _encode_payload(snapshot, include_hash=(version >= FORMAT_VERSION))
    checksum = zlib.crc32(payload_raw) & 0xFFFFFFFF
    header = BrainHeader(
        magic=MAGIC,
        version=version,
        payload_len=len(payload_raw),
        payload_crc32=checksum,
    )
    return header.to_bytes() + payload_raw


def decode_brain_file(raw: bytes) -> BrainSnapshot:
    """Decode and validate a `.atulya` binary blob."""
    header = BrainHeader.from_bytes(raw)
    if header.magic != MAGIC:
        raise ValueError("invalid brain file header: bad magic")
    if header.version not in SUPPORTED_VERSIONS:
        raise ValueError(f"unsupported brain file version: {header.version}")

    payload = raw[HEADER_STRUCT.size : HEADER_STRUCT.size + header.payload_len]
    if len(payload) != header.payload_len:
        raise ValueError("invalid brain file payload: truncated")
    checksum = zlib.crc32(payload) & 0xFFFFFFFF
    if checksum != header.payload_crc32:
        raise ValueError("invalid brain file payload: checksum mismatch")
    parsed = json.loads(payload.decode("utf-8"))
    if header.version >= FORMAT_VERSION:
        expected = parsed.get("file_checksum_sha256", "")
        if not expected:
            raise ValueError("invalid brain file payload: missing sha256")
        parsed["file_checksum_sha256"] = ""
        actual = hashlib.sha256(_to_canonical_json(parsed)).hexdigest()
        if actual != expected:
            raise ValueError("invalid brain file payload: sha256 mismatch")
        parsed["file_checksum_sha256"] = expected
    return BrainSnapshot.from_payload(parsed)


def validate_brain_file(raw: bytes) -> BrainCompatibilityReport:
    try:
        header = BrainHeader.from_bytes(raw)
    except Exception as exc:
        return BrainCompatibilityReport(valid=False, version=None, reason=str(exc))

    if header.magic != MAGIC:
        return BrainCompatibilityReport(valid=False, version=header.version, reason="bad magic")
    if header.version not in SUPPORTED_VERSIONS:
        return BrainCompatibilityReport(valid=False, version=header.version, reason="unsupported version")
    try:
        decode_brain_file(raw)
    except Exception as exc:
        return BrainCompatibilityReport(valid=False, version=header.version, reason=str(exc))
    return BrainCompatibilityReport(valid=True, version=header.version, reason=None)
