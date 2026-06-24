"""Exporter protocol and base helpers."""

from __future__ import annotations

from typing import Protocol

from ..models import AtulyaTrainingRecord, ExportManifest


class ForgeExporter(Protocol):
    adapter_id: str

    def export(self, records: list[AtulyaTrainingRecord], *, options: dict | None = None) -> ExportManifest: ...


def filter_exportable(
    records: list[AtulyaTrainingRecord],
    *,
    threshold: float | None = None,
) -> list[AtulyaTrainingRecord]:
    if threshold is None:
        return [r for r in records if r.quality.exportable]
    return [r for r in records if r.quality.overall >= threshold]
