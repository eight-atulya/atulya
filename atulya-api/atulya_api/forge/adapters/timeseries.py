"""Normalize CSV/time-series rows into retain batch payloads."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Any

from ..models import RetainBatchItem


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return datetime.now(timezone.utc)


class ForgeTimeSeriesAdapter:
    """Convert dated fact rows into one retain item per row."""

    adapter_id = "timeseries"

    def normalize(self, payload: dict[str, Any]) -> list[RetainBatchItem]:
        tags = list(payload.get("tags") or [])
        context = payload.get("context", "forge timeseries ingest")
        key_field = payload.get("key_field", "key")
        value_field = payload.get("value_field", "value")
        timestamp_field = payload.get("timestamp_field", "timestamp")
        items: list[RetainBatchItem] = []

        rows: list[dict[str, Any]] = list(payload.get("rows") or [])
        if not rows and payload.get("csv_text"):
            reader = csv.DictReader(io.StringIO(payload["csv_text"]))
            rows = [dict(row) for row in reader]

        for idx, row in enumerate(rows):
            key = row.get(key_field) or row.get("key") or f"field_{idx}"
            value = row.get(value_field) or row.get("value") or ""
            ts = _parse_datetime(row.get(timestamp_field) or row.get("timestamp"))
            text = f"{key}: {value}"
            if row.get("unit"):
                text = f"{text} ({row['unit']})"
            document_id = row.get("id") or f"forge_ts_{idx}_{uuid.uuid4().hex[:8]}"
            items.append(
                {
                    "content": text,
                    "context": row.get("context") or context,
                    "event_date": ts,
                    "document_id": document_id,
                    "tags": tags + list(row.get("tags") or []),
                }
            )
        return items
