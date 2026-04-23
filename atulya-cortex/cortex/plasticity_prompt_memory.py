"""plasticity_prompt_memory.py — adaptive prompt guidance + genome distillation."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DIRECTIVE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(concise|short|brief)\b", re.IGNORECASE), "Keep replies concise."),
    (re.compile(r"\b(no emoji|without emoji|stop emoji)\b", re.IGNORECASE), "Avoid emojis unless asked."),
    (re.compile(r"\b(casual|human|natural)\b", re.IGNORECASE), "Use natural human conversational tone."),
    (re.compile(r"\b(step by step|steps)\b", re.IGNORECASE), "Prefer step-by-step structure when useful."),
    (re.compile(r"\b(execute|run command|run this)\b", re.IGNORECASE), "If execution is restricted, clearly say limits and next action."),
)
logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PlasticityPromptSettings:
    enabled: bool = False
    per_user_enabled: bool = True
    system_enabled: bool = True
    max_directives: int = 6
    time_context_enabled: bool = True
    distill_enabled: bool = True
    distill_min_updates: int = 5
    distill_cooldown_s: float = 300.0
    distill_max_versions: int = 16


class PlasticityPromptMemory:
    def __init__(self, path: Path, settings: PlasticityPromptSettings) -> None:
        self._path = path
        self._settings = settings

    def record_turn(self, *, peer_key: str | None, user_text: str, assistant_text: str) -> None:
        if not self._settings.enabled:
            return
        directives = self._extract_directives(user_text or "")
        if not directives:
            return
        data = self._load()
        if self._settings.system_enabled:
            bucket = data.setdefault("system", [])
            for d in directives:
                self._upsert(bucket, d)
            data["system_pending_updates"] = int(data.get("system_pending_updates", 0)) + len(directives)
        if self._settings.per_user_enabled and peer_key:
            peers = data.setdefault("peers", {})
            bucket = peers.setdefault(peer_key, [])
            for d in directives:
                self._upsert(bucket, d)
            pending = data.setdefault("peer_pending_updates", {})
            pending[peer_key] = int(pending.get(peer_key, 0)) + len(directives)
        self._save(data)

    def prompt_block(self, *, peer_key: str | None) -> str:
        if not self._settings.enabled:
            return ""
        data = self._load()
        lines: list[str] = []
        if self._settings.system_enabled:
            top = self._top_directives(data.get("system", []), self._settings.max_directives)
            if top:
                lines.append("Adaptive system guidance:")
                lines.extend(f"- {item['directive']}" for item in top)
            system_genome = str(data.get("system_genome", "")).strip()
            if system_genome:
                lines.append("System prompt genome:")
                lines.append(system_genome)
        if self._settings.per_user_enabled and peer_key:
            peers = data.get("peers", {})
            top_peer = self._top_directives(peers.get(peer_key, []), self._settings.max_directives)
            if top_peer:
                lines.append("Adaptive peer guidance:")
                lines.extend(f"- {item['directive']}" for item in top_peer)
            peer_genome = str(data.get("peer_genomes", {}).get(peer_key, "")).strip()
            if peer_genome:
                lines.append("Peer prompt genome:")
                lines.append(peer_genome)
        return "\n".join(lines).strip()

    @property
    def time_context_enabled(self) -> bool:
        return bool(self._settings.time_context_enabled)

    @property
    def distill_enabled(self) -> bool:
        return bool(self._settings.enabled and self._settings.distill_enabled)

    async def distill_if_due(
        self,
        *,
        language: Any | None,
        provider: str | None,
        model: str | None,
        temperature: float,
        max_tokens: int | None,
        peer_key: str | None,
    ) -> None:
        if not self.distill_enabled or language is None:
            return
        data = self._load()
        now = datetime.now(timezone.utc)

        if self._settings.system_enabled:
            await self._distill_scope_if_due(
                data=data,
                scope="system",
                directives=self._top_directives(data.get("system", []), self._settings.max_directives),
                pending_updates=int(data.get("system_pending_updates", 0)),
                last_key="system_last_distilled_at",
                versions_key="system_genome_versions",
                genome_setter=lambda genome: data.__setitem__("system_genome", genome),
                pending_clearer=lambda: data.__setitem__("system_pending_updates", 0),
                now=now,
                language=language,
                provider=provider,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        if self._settings.per_user_enabled and peer_key:
            peers = data.get("peers", {})
            peer_items = self._top_directives(peers.get(peer_key, []), self._settings.max_directives)
            pending = data.setdefault("peer_pending_updates", {})
            pending_count = int(pending.get(peer_key, 0))
            peer_genomes = data.setdefault("peer_genomes", {})
            versions_root = data.setdefault("peer_genome_versions", {})
            await self._distill_scope_if_due(
                data=data,
                scope=f"peer:{peer_key}",
                directives=peer_items,
                pending_updates=pending_count,
                last_key=f"peer_last_distilled_at:{peer_key}",
                versions_key=f"peer_versions:{peer_key}",
                genome_setter=lambda genome: peer_genomes.__setitem__(peer_key, genome),
                pending_clearer=lambda: pending.__setitem__(peer_key, 0),
                now=now,
                language=language,
                provider=provider,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                versions_store=versions_root,
            )
        self._save(data)

    def rollback(self, *, peer_key: str | None = None) -> bool:
        data = self._load()
        if peer_key:
            versions_root = data.get("peer_genome_versions", {})
            versions = versions_root.get(peer_key, [])
            if len(versions) < 2:
                return False
            versions.pop()
            prior = versions[-1]
            data.setdefault("peer_genomes", {})[peer_key] = prior.get("genome", "")
            self._save(data)
            return True
        versions = data.get("system_genome_versions", [])
        if len(versions) < 2:
            return False
        versions.pop()
        prior = versions[-1]
        data["system_genome"] = prior.get("genome", "")
        self._save(data)
        return True

    @staticmethod
    def _extract_directives(text: str) -> list[str]:
        out: list[str] = []
        for pattern, directive in _DIRECTIVE_RULES:
            if pattern.search(text) and directive not in out:
                out.append(directive)
        return out

    @staticmethod
    def _upsert(bucket: list[dict[str, Any]], directive: str) -> None:
        now = _now_iso()
        for item in bucket:
            if item.get("directive") == directive:
                item["count"] = int(item.get("count", 0)) + 1
                item["updated_at"] = now
                return
        bucket.append({"directive": directive, "count": 1, "updated_at": now})

    @staticmethod
    def _top_directives(bucket: list[dict[str, Any]], max_items: int) -> list[dict[str, Any]]:
        items = list(bucket or [])
        items.sort(
            key=lambda x: (
                -int(x.get("count", 0)),
                str(x.get("updated_at", "")),
                str(x.get("directive", "")),
            )
        )
        return items[: max(1, int(max_items))]

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {
                "schema_version": 2,
                "system": [],
                "peers": {},
                "system_pending_updates": 0,
                "peer_pending_updates": {},
                "system_genome": "",
                "peer_genomes": {},
                "system_genome_versions": [],
                "peer_genome_versions": {},
            }
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            payload.setdefault("schema_version", 2)
            payload.setdefault("system", [])
            payload.setdefault("peers", {})
            payload.setdefault("system_pending_updates", 0)
            payload.setdefault("peer_pending_updates", {})
            payload.setdefault("system_genome", "")
            payload.setdefault("peer_genomes", {})
            payload.setdefault("system_genome_versions", [])
            payload.setdefault("peer_genome_versions", {})
            return payload
        except Exception:
            return {
                "schema_version": 2,
                "system": [],
                "peers": {},
                "system_pending_updates": 0,
                "peer_pending_updates": {},
                "system_genome": "",
                "peer_genomes": {},
                "system_genome_versions": [],
                "peer_genome_versions": {},
            }

    def _save(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    async def _distill_scope_if_due(
        self,
        *,
        data: dict[str, Any],
        scope: str,
        directives: list[dict[str, Any]],
        pending_updates: int,
        last_key: str,
        versions_key: str,
        genome_setter,
        pending_clearer,
        now: datetime,
        language: Any,
        provider: str | None,
        model: str | None,
        temperature: float,
        max_tokens: int | None,
        versions_store: dict[str, Any] | None = None,
    ) -> None:
        if pending_updates < int(self._settings.distill_min_updates):
            return
        last_iso = str(data.get(last_key, "")).strip()
        if last_iso:
            try:
                last_dt = datetime.fromisoformat(last_iso)
                elapsed = max(0.0, (now - last_dt).total_seconds())
                if elapsed < float(self._settings.distill_cooldown_s):
                    return
            except ValueError:
                pass
        if not directives:
            return
        genome = await self._distill_with_llm(
            language=language,
            scope=scope,
            directives=directives,
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not genome:
            return
        genome_setter(genome)
        data[last_key] = _now_iso()
        pending_clearer()
        entry = {"at": _now_iso(), "genome": genome}
        if versions_store is None:
            versions = data.setdefault(versions_key, [])
        else:
            versions = versions_store.setdefault(scope.split("peer:", 1)[-1], [])
        versions.append(entry)
        keep = max(1, int(self._settings.distill_max_versions))
        if len(versions) > keep:
            del versions[:-keep]

    async def _distill_with_llm(
        self,
        *,
        language: Any,
        scope: str,
        directives: list[dict[str, Any]],
        provider: str | None,
        model: str | None,
        temperature: float,
        max_tokens: int | None,
    ) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "Compress prompt directives into a compact prompt genome.\n"
                    "Return strict JSON: {\"genome\":\"...\"}.\n"
                    "Genome must be 3-6 short bullets, each imperative and non-redundant."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "scope": scope,
                        "directives": [
                            {"directive": d.get("directive", ""), "count": int(d.get("count", 0))}
                            for d in directives
                        ],
                    },
                    ensure_ascii=True,
                ),
            },
        ]
        try:
            utt = await language.think(
                messages,
                provider=provider,
                model=model,
                temperature=min(float(temperature), 0.2),
                max_tokens=min(int(max_tokens or 256), 256),
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("plasticity distill failed scope=%s: %s", scope, exc)
            return ""
        payload = self._parse_json_dict(str(getattr(utt, "text", "") or "").strip())
        genome = str(payload.get("genome", "")).strip()
        return genome

    @staticmethod
    def _parse_json_dict(text: str) -> dict[str, Any]:
        if not text:
            return {}
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
        return {}


__all__ = ["PlasticityPromptMemory", "PlasticityPromptSettings"]
