from __future__ import annotations

import json
from pathlib import Path

import pytest

from cortex.bus import Recollection, Stimulus
from cortex.peer_memory import PeerMemoryBridge


class _Embedded:
    async def acreate_bank(self, bank_id: str, retain_mission: str = ""):
        return None

    async def aretain(self, **kwargs):
        return {"ok": True}


class _Hip:
    async def encode(self, *args, **kwargs):
        return {"ok": True}


class _Rec:
    async def recall(self, *args, **kwargs):
        return [
            Recollection(kind="episodic", text="hello from memory", score=0.9, source="mem-1"),
        ]


@pytest.mark.asyncio
async def test_recall_and_retain_write_raw_backup(tmp_path: Path) -> None:
    bridge = PeerMemoryBridge(
        embedded=_Embedded(),
        hippocampus=_Hip(),
        recall=_Rec(),
        recall_top_k=4,
        whatsapp_memory_raw_dir=tmp_path,
    )
    bank = "cortex_default_test_peer"
    out = await bridge.cortex_recall("hello", "episodic", bank)
    assert out and out[0].text == "hello from memory"

    stim = Stimulus(channel="whatsapp:test", sender="test", text="hello")
    await bridge.retain_turn(stim, "hi", "there", bank)

    files = list(tmp_path.glob("*.jsonl"))
    assert files, "expected raw backup file"
    body = files[0].read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line)["event"] for line in body]
    assert "recall" in events
    assert "retain" in events

