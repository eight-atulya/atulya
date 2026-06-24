"""Graph intelligence fine-tuning JSONL exporter."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ..models import AtulyaTrainingRecord, ExportManifest, LineageBlock
from ..quality import summarize_quality
from .base import filter_exportable


class GraphIntelligenceJsonlExporter:
    adapter_id = "graph_intelligence_jsonl"
    adapter_version = "1"

    def export(self, records: list[AtulyaTrainingRecord], *, options: dict | None = None) -> ExportManifest:
        opts = options or {}
        threshold = opts.get("quality_threshold")
        selected = filter_exportable(records, threshold=threshold) if threshold is not None else records
        lines: list[str] = []

        for record in selected:
            if not record.graph:
                continue
            units = [
                {
                    "id": f.id,
                    "text": f.text,
                    "fact_type": f.fact_type,
                    "proof_count": 0,
                    "source_memory_ids": [],
                    "tags": f.tags,
                    "entities": [],
                }
                for f in record.facts
            ]
            expected = record.labels.expected_graph or {
                "node_titles": [n.title for n in record.graph.nodes],
                "statuses": {n.title: n.status for n in record.graph.nodes},
                "change_types": [e.change_type for e in record.graph.change_events],
            }
            row = {
                "scenario_id": record.record_id,
                "description": f"forge:{record.recipe_id}",
                "notes": record.domain_tags,
                "units": units,
                "expected": expected,
            }
            lines.append(json.dumps(row, default=str))

        content = "\n".join(lines) + ("\n" if lines else "")
        lineage = LineageBlock(
            recipe_id=selected[0].recipe_id if selected else "graph_state",
            adapter_version=self.adapter_version,
            exported_at=datetime.now(timezone.utc),
        )
        return ExportManifest(
            adapter_id=self.adapter_id,
            record_count=len(records),
            exportable_count=len(lines),
            content=content,
            lineage=lineage,
            quality_summary=summarize_quality(records),
        )
