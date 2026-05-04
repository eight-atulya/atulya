"""
Typed metadata models for async operations.

These dataclasses define the structure of result_metadata for different operation types.
The metadata is exposed in the API for debugging purposes and may change without notice.
"""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class BatchRetainParentMetadata:
    """Metadata for parent batch_retain operations (when split into sub-batches)."""

    items_count: int
    total_tokens: int
    num_sub_batches: int
    completed_sub_batches: int = 0
    failed_sub_batches: int = 0
    progress_current: int = 0
    progress_total: int | None = None
    progress_unit: str = "sub_batches"
    progress_label: str = "Sub-batches finished"
    is_parent: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        payload = asdict(self)
        if payload["progress_total"] is None:
            payload["progress_total"] = self.num_sub_batches
        return payload


@dataclass
class BatchRetainChildMetadata:
    """Metadata for child batch_retain operations (individual sub-batches)."""

    items_count: int
    parent_operation_id: str
    sub_batch_index: int
    total_sub_batches: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return asdict(self)


@dataclass
class RetainMetadata:
    """Metadata for regular retain operations (non-batched, deprecated async path)."""

    items_count: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return asdict(self)


@dataclass
class ConsolidationMetadata:
    """Metadata for consolidation operations."""

    # Currently empty, but structure for future fields
    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return asdict(self)


@dataclass
class RefreshMentalModelMetadata:
    """Metadata for mental model refresh operations."""

    mental_model_id: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return asdict(self)


@dataclass
class CodebaseOperationMetadata:
    """Metadata for queued codebase import, refresh, and approval operations."""

    codebase_id: str
    snapshot_id: str
    source_type: str
    source_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return asdict(self)
