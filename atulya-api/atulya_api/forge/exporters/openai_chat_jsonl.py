"""OpenAI chat fine-tuning JSONL exporter."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ..models import AtulyaTrainingRecord, ExportManifest, LineageBlock
from ..quality import summarize_quality
from .base import filter_exportable


class OpenAIChatJsonlExporter:
    adapter_id = "openai_chat_jsonl"
    adapter_version = "1"

    def export(self, records: list[AtulyaTrainingRecord], *, options: dict | None = None) -> ExportManifest:
        opts = options or {}
        threshold = opts.get("quality_threshold")
        selected = filter_exportable(records, threshold=threshold) if threshold is not None else records
        lines: list[str] = []

        for record in selected:
            messages: list[dict] = []
            system_context = _build_system_context(record)
            if system_context:
                messages.append({"role": "system", "content": system_context})

            for session in record.timeline.sessions:
                for turn in session.turns:
                    messages.append({"role": turn.role, "content": turn.content})

            for task in record.tasks:
                if task.query:
                    messages.append({"role": "user", "content": task.query})

            answer = record.labels.answer or record.labels.gold_answer
            if answer:
                messages.append({"role": "assistant", "content": answer})

            if len(messages) >= 2:
                lines.append(json.dumps({"messages": messages}, default=str))

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


def _build_system_context(record: AtulyaTrainingRecord) -> str:
    parts: list[str] = []
    if record.facts:
        parts.append("Relevant facts:")
        for fact in record.facts[:10]:
            parts.append(f"- {fact.text}")
    if record.observations:
        parts.append("Observations:")
        for obs in record.observations[:5]:
            parts.append(f"- {obs.text}")
    return "\n".join(parts)
