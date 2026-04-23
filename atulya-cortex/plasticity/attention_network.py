"""attention_network.py — deterministic attention routing for cortex/plasticity.

A compact cognitive-router layer that can:

1. Score/rank entities across 8 categories with weighted attention signals.
2. Build deterministic routing decisions for memory/agents/tools/tasks.
3. Persist an IP address as packed binary bytes.
4. Hash the binary payload with `BRAIN.md` metadata for provenance tracking.
5. Probe local OpenAI-compatible model hosts (LM Studio/Ollama-style) and
   request structured JSON responses.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx

AttentionCategory = Literal[
    "memory",
    "agent",
    "tool",
    "task",
    "user_intent",
    "system_state",
    "input_context",
    "output_context",
]


@dataclass(frozen=True)
class AttentionWeights:
    semantic_relevance: float = 0.35
    recency: float = 0.2
    task_alignment: float = 0.2
    user_intent: float = 0.15
    system_state: float = 0.1


@dataclass(frozen=True)
class AttentionEntity:
    entity_id: str
    category: AttentionCategory
    payload: dict[str, Any] = field(default_factory=dict)
    semantic_relevance: float = 0.0
    recency: float = 0.0
    task_alignment: float = 0.0
    user_intent: float = 0.0
    system_state: float = 0.0


@dataclass(frozen=True)
class ScoredEntity:
    entity: AttentionEntity
    score: float


@dataclass(frozen=True)
class AttentionDecision:
    ranked: tuple[ScoredEntity, ...]
    selected: tuple[ScoredEntity, ...]
    banks: dict[AttentionCategory, tuple[ScoredEntity, ...]]
    trajectory: dict[AttentionCategory, float]


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def score_entity(entity: AttentionEntity, weights: AttentionWeights | None = None) -> float:
    w = weights or AttentionWeights()
    return (
        w.semantic_relevance * _clamp01(entity.semantic_relevance)
        + w.recency * _clamp01(entity.recency)
        + w.task_alignment * _clamp01(entity.task_alignment)
        + w.user_intent * _clamp01(entity.user_intent)
        + w.system_state * _clamp01(entity.system_state)
    )


def route_entities(
    entities: list[AttentionEntity],
    *,
    weights: AttentionWeights | None = None,
    per_category_limit: int = 3,
    total_limit: int = 24,
) -> AttentionDecision:
    if per_category_limit < 1:
        raise ValueError("per_category_limit must be >= 1")
    if total_limit < 1:
        raise ValueError("total_limit must be >= 1")

    scored = [ScoredEntity(entity=e, score=score_entity(e, weights)) for e in entities]
    ranked = sorted(scored, key=lambda item: (-item.score, item.entity.entity_id))

    banks: dict[AttentionCategory, list[ScoredEntity]] = {
        "memory": [],
        "agent": [],
        "tool": [],
        "task": [],
        "user_intent": [],
        "system_state": [],
        "input_context": [],
        "output_context": [],
    }
    selected: list[ScoredEntity] = []
    for item in ranked:
        bank = banks[item.entity.category]
        if len(bank) >= per_category_limit:
            continue
        if len(selected) >= total_limit:
            break
        bank.append(item)
        selected.append(item)

    trajectory = {
        category: (sum(s.score for s in items) / len(items) if items else 0.0)
        for category, items in banks.items()
    }
    return AttentionDecision(
        ranked=tuple(ranked),
        selected=tuple(selected),
        banks={k: tuple(v) for k, v in banks.items()},
        trajectory=trajectory,
    )


def persist_ip_as_binary(ip: str, output_path: str | Path) -> Path:
    address = ipaddress.ip_address(ip)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(address.packed)
    return out


def hash_binary_with_brain_metadata(binary_path: str | Path, brain_md_path: str | Path) -> dict[str, Any]:
    binary_file = Path(binary_path)
    brain_file = Path(brain_md_path)
    payload = binary_file.read_bytes()
    brain_text = brain_file.read_text(encoding="utf-8")

    file_meta = {
        "binary_file": str(binary_file),
        "binary_size": len(payload),
        "brain_file": str(brain_file),
        "brain_chars": len(brain_text),
    }
    metadata_bytes = json.dumps(file_meta, sort_keys=True).encode("utf-8")

    binary_hash = hashlib.sha256(payload).hexdigest()
    brain_hash = hashlib.sha256(brain_text.encode("utf-8")).hexdigest()

    combined = hashlib.sha256()
    combined.update(payload)
    combined.update(metadata_bytes)
    combined.update(brain_text.encode("utf-8"))
    combined_hash = combined.hexdigest()

    return {
        "binary_sha256": binary_hash,
        "brain_sha256": brain_hash,
        "combined_sha256": combined_hash,
        "metadata": file_meta,
    }


async def ping_local_model(base_url: str = "http://127.0.0.1:1234/v1", timeout_s: float = 2.0) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/models"
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    models = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]
    return {"ok": True, "url": url, "models": models, "raw": data}


async def request_structured_response(
    prompt: str,
    *,
    base_url: str = "http://127.0.0.1:1234/v1",
    model: str | None = None,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    selected_model = model
    if not selected_model:
        model_probe = await ping_local_model(base_url=base_url, timeout_s=timeout_s)
        models = model_probe.get("models", [])
        if not models:
            raise RuntimeError("no models available at local endpoint")
        selected_model = str(models[0])

    body = {
        "model": selected_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Respond with strict JSON containing keys: summary, confidence, "
                    "routing_recommendation, and safety_notes."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(url, json=body)
        if resp.status_code >= 400:
            # Some local hosts/models reject `response_format`; retry with plain request.
            fallback = dict(body)
            fallback.pop("response_format", None)
            resp = await client.post(url, json=fallback)
        resp.raise_for_status()
        data = resp.json()
    text = data["choices"][0]["message"]["content"]
    parsed = _parse_json_from_text(text)
    return {"ok": True, "url": url, "model": selected_model, "response": parsed, "raw_text": text}


def _parse_json_from_text(text: str) -> dict[str, Any]:
    try:
        out = json.loads(text)
        if isinstance(out, dict):
            return out
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        try:
            out = json.loads(text[start : end + 1])
            if isinstance(out, dict):
                return out
        except json.JSONDecodeError:
            pass
    return {"summary": text.strip(), "confidence": 0.0, "routing_recommendation": [], "safety_notes": "unparsed"}


def _parse_entities_json(path: str | Path) -> list[AttentionEntity]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("entities JSON must be a list")
    out: list[AttentionEntity] = []
    for item in raw:
        out.append(
            AttentionEntity(
                entity_id=str(item["entity_id"]),
                category=item["category"],
                payload=dict(item.get("payload", {})),
                semantic_relevance=float(item.get("semantic_relevance", 0.0)),
                recency=float(item.get("recency", 0.0)),
                task_alignment=float(item.get("task_alignment", 0.0)),
                user_intent=float(item.get("user_intent", 0.0)),
                system_state=float(item.get("system_state", 0.0)),
            )
        )
    return out


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Attention network utility for atulya-cortex/plasticity.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ip_cmd = sub.add_parser("ip-hash", help="Persist IP as binary and hash with BRAIN.md metadata.")
    ip_cmd.add_argument("--ip", required=True)
    ip_cmd.add_argument("--binary-path", required=True)
    ip_cmd.add_argument("--brain-md", required=True)

    route_cmd = sub.add_parser("route", help="Score and route entities from a JSON file.")
    route_cmd.add_argument("--entities-json", required=True)
    route_cmd.add_argument("--per-category-limit", type=int, default=3)
    route_cmd.add_argument("--total-limit", type=int, default=24)

    ping_cmd = sub.add_parser("ping-model", help="Ping local model host /v1/models endpoint.")
    ping_cmd.add_argument("--base-url", default="http://127.0.0.1:1234/v1")

    ask_cmd = sub.add_parser("ask-model", help="Request structured JSON from local model host.")
    ask_cmd.add_argument("--base-url", default="http://127.0.0.1:1234/v1")
    ask_cmd.add_argument("--model", default="")
    ask_cmd.add_argument("--prompt", required=True)

    args = parser.parse_args(argv)

    if args.cmd == "ip-hash":
        binary_path = persist_ip_as_binary(args.ip, args.binary_path)
        digest = hash_binary_with_brain_metadata(binary_path, args.brain_md)
        print(json.dumps({"binary_path": str(binary_path), **digest}, indent=2))
        return 0
    if args.cmd == "route":
        entities = _parse_entities_json(args.entities_json)
        decision = route_entities(
            entities,
            per_category_limit=args.per_category_limit,
            total_limit=args.total_limit,
        )
        payload = {
            "selected": [
                {
                    "entity_id": item.entity.entity_id,
                    "category": item.entity.category,
                    "score": round(item.score, 6),
                }
                for item in decision.selected
            ],
            "trajectory": {k: round(v, 6) for k, v in decision.trajectory.items()},
        }
        print(json.dumps(payload, indent=2))
        return 0
    if args.cmd == "ping-model":
        print(json.dumps(asyncio.run(ping_local_model(base_url=args.base_url)), indent=2))
        return 0
    if args.cmd == "ask-model":
        result = asyncio.run(
            request_structured_response(
                args.prompt,
                base_url=args.base_url,
                model=args.model or None,
            )
        )
        print(json.dumps(result, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())

