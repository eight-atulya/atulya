"""Canonical ATR JSONL exporter."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ..models import AtulyaTrainingRecord, ExportManifest, LineageBlock
from ..quality import summarize_quality
from .base import filter_exportable


class AtrJsonlExporter:
    adapter_id = "atr_jsonl"
    adapter_version = "1"

    def export(self, records: list[AtulyaTrainingRecord], *, options: dict | None = None) -> ExportManifest:
        opts = options or {}
        threshold = opts.get("quality_threshold")
        selected = filter_exportable(records, threshold=threshold) if threshold is not None else records
        lines = [json.dumps(r.model_dump(mode="json"), default=str) for r in selected]
        content = "\n".join(lines) + ("\n" if lines else "")
        lineage = LineageBlock(
            recipe_id=selected[0].recipe_id if selected else "unknown",
            adapter_version=self.adapter_version,
            exported_at=datetime.now(timezone.utc),
        )
        return ExportManifest(
            adapter_id=self.adapter_id,
            record_count=len(records),
            exportable_count=len(selected),
            content=content,
            lineage=lineage,
            quality_summary=summarize_quality(records),
        )
