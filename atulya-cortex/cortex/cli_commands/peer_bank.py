"""peer_bank — inspect and manage per-peer bank mental models.

This command is for operator workflows where each remote contact maps to a
stable bank id (``cortex_<profile>_<peer>``) and the bank's mental model is
used as top-level prompt context during channel conversations.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from cortex import config as config_module
from cortex.peer_banks import peer_bank_id
from cortex.peer_mental_model_store import BankEntitySnapshot, MentalModelSnapshot, sync_peer_mental_model_file

NAME = "peer-bank"
HELP = "Manage per-peer bank mental models."


def register(subparsers, common_parents) -> None:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=list(common_parents),
        description="Inspect/set mental models for a peer-specific bank.",
    )
    sub = parser.add_subparsers(dest="peer_bank_command", metavar="<action>")

    p_resolve = sub.add_parser("resolve", help="Resolve bank_id from peer key.")
    p_resolve.add_argument("peer", help="Peer key or channel key, e.g. 255@lid or whatsapp:255@lid")
    p_resolve.set_defaults(_peer_bank_run=_run_resolve)

    p_get = sub.add_parser("get", help="Show bank and matching mental models.")
    p_get.add_argument("peer", help="Peer key or channel key, e.g. whatsapp:255@lid")
    p_get.add_argument("--name", default="", help="Filter by mental model name.")
    p_get.add_argument("--json", action="store_true", help="Emit JSON.")
    p_get.set_defaults(_peer_bank_run=_run_get)

    p_set = sub.add_parser("set", help="Create/update one named mental model for this peer bank.")
    p_set.add_argument("peer", help="Peer key or channel key, e.g. whatsapp:255@lid")
    p_set.add_argument("--name", default="peer_profile", help="Mental model name.")
    p_set.add_argument("--content", required=True, help="Mental model content.")
    p_set.add_argument("--json", action="store_true", help="Emit JSON.")
    p_set.set_defaults(_peer_bank_run=_run_set)

    parser.set_defaults(_run=run)


def run(args: argparse.Namespace, *, home) -> int:
    handler = getattr(args, "_peer_bank_run", None)
    if handler is None:
        return _run_resolve(args, home=home)
    return handler(args, home=home)


def _run_resolve(args: argparse.Namespace, *, home) -> int:
    peer = _peer_only(args.peer)
    bank_id = peer_bank_id(home.profile_name, peer)
    print(bank_id)
    return 0


def _run_get(args: argparse.Namespace, *, home) -> int:
    cfg = _load_config_or_die(home)
    if cfg is None:
        return 2
    peer = _peer_only(args.peer)
    bank_id = peer_bank_id(home.profile_name, peer)
    emb = _embedded_for_config(cfg, home.profile_name)
    try:
        _ensure_bank(emb, bank_id)
        models = _models_for_bank(emb, bank_id)
        if args.name:
            models = [m for m in models if _pick(m, "name") == args.name]
        _sync_whatsapp_file(home, peer, bank_id, models)
        payload = {
            "peer": peer,
            "bank_id": bank_id,
            "mental_models": [{"id": _pick(m, "id"), "name": _pick(m, "name"), "content": _pick(m, "content")} for m in models],
        }
        if args.json:
            print(json.dumps(payload, indent=2))
            return 0
        print(f"peer:    {peer}")
        print(f"bank_id: {bank_id}")
        if not models:
            print("(no mental models)")
            return 0
        for m in payload["mental_models"]:
            preview = m["content"] if len(m["content"]) <= 180 else m["content"][:177] + "..."
            print(f"- {m['name']} ({m['id']})")
            print(f"  {preview}")
        return 0
    finally:
        _close_safely(emb)


def _run_set(args: argparse.Namespace, *, home) -> int:
    cfg = _load_config_or_die(home)
    if cfg is None:
        return 2
    peer = _peer_only(args.peer)
    bank_id = peer_bank_id(home.profile_name, peer)
    emb = _embedded_for_config(cfg, home.profile_name)
    try:
        _ensure_bank(emb, bank_id)
        target_name = (args.name or "peer_profile").strip() or "peer_profile"
        content = str(args.content or "").strip()
        if not content:
            print("error: --content cannot be empty", file=sys.stderr)
            return 2

        existing = None
        for m in _models_for_bank(emb, bank_id):
            if _pick(m, "name") == target_name:
                existing = m
                break
        if existing is not None:
            model_id = _pick(existing, "id")
            out = _update_mental_model_compat(
                emb,
                bank_id=bank_id,
                mental_model_id=model_id,
                name=target_name,
                content=content,
            )
            status = "updated"
        else:
            out = _create_mental_model_compat(
                emb,
                bank_id=bank_id,
                name=target_name,
                content=content,
            )
            status = "created"
        _sync_whatsapp_file(home, peer, bank_id, _models_for_bank(emb, bank_id))

        payload = {
            "status": status,
            "peer": peer,
            "bank_id": bank_id,
            "name": target_name,
            "mental_model_id": _pick(out, "id"),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"{status} {target_name} for {peer} in {bank_id}")
        return 0
    finally:
        _close_safely(emb)


def _peer_only(peer_or_channel: str) -> str:
    value = (peer_or_channel or "").strip()
    if not value:
        raise ValueError("peer is required")
    if ":" in value:
        _, tail = value.split(":", 1)
        return tail.strip()
    return value


def _load_config_or_die(home):
    try:
        return config_module.load(home)
    except config_module.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None


def _embedded_for_config(config, cortex_profile: str):
    from atulya import AtulyaClient, AtulyaEmbedded

    backend = (getattr(config.memory, "peer_banks_backend", "embedded") or "embedded").strip().lower()
    if backend == "api":
        import os

        api_key_env = (getattr(config.memory, "api_key_env", "") or "").strip()
        api_key = os.environ.get(api_key_env, "") if api_key_env else ""
        return AtulyaClient(base_url=config.memory.api_url, api_key=api_key or None)
    ep = (getattr(config.memory, "embed_profile", "") or "").strip() or cortex_profile
    return AtulyaEmbedded(profile=ep)


def _ensure_bank(emb: Any, bank_id: str) -> None:
    try:
        emb.banks.create(
            bank_id=bank_id,
            mission="Store conversational turns and durable facts about this person.",
        )
    except Exception:
        # Bank creation is idempotent in spirit; ignore "already exists" style failures.
        pass


def _models_for_bank(emb: Any, bank_id: str) -> list[Any]:
    listed = emb.mental_models.list(bank_id)
    return list(getattr(listed, "items", []) or [])


def _pick(obj: Any, key: str) -> str:
    if isinstance(obj, dict):
        value = obj.get(key, "")
    else:
        value = getattr(obj, key, "")
    return str(value or "").strip()


def _close_safely(emb: Any) -> None:
    try:
        emb.close()
    except Exception:
        pass


def _create_mental_model_compat(emb: Any, *, bank_id: str, name: str, content: str) -> Any:
    try:
        return emb.mental_models.create(bank_id, name=name, content=content)
    except TypeError:
        # Newer atulya-api shape uses source_query instead of content.
        try:
            return emb.client.create_mental_model(
                bank_id=bank_id,
                name=name,
                source_query=content,
            )
        except TypeError:
            return emb.client.create_mental_model(
                bank_id=bank_id,
                name=name,
                content=content,
            )


def _update_mental_model_compat(
    emb: Any,
    *,
    bank_id: str,
    mental_model_id: str,
    name: str,
    content: str,
) -> Any:
    try:
        return emb.mental_models.update(
            bank_id,
            mental_model_id,
            name=name,
            content=content,
        )
    except TypeError:
        try:
            return emb.client.update_mental_model(
                bank_id=bank_id,
                mental_model_id=mental_model_id,
                name=name,
                source_query=content,
            )
        except TypeError:
            return emb.client.update_mental_model(
                bank_id=bank_id,
                mental_model_id=mental_model_id,
                name=name,
                content=content,
            )


def _sync_whatsapp_file(home, peer: str, bank_id: str, models: list[Any]) -> None:
    snapshots: list[MentalModelSnapshot] = []
    for m in models:
        snapshots.append(
            MentalModelSnapshot(
                model_id=_pick(m, "id") or _pick(m, "name") or "mental-model",
                name=_pick(m, "name") or "mental-model",
                content=_pick(m, "content"),
            )
        )
    listed = _models_and_entities_for_file(models)
    sync_peer_mental_model_file(
        directory=home.whatsapp_mental_models_dir,
        peer_key=peer,
        bank_id=bank_id,
        models=snapshots,
        entities=listed,
    )


def _models_and_entities_for_file(models: list[Any]) -> list[BankEntitySnapshot]:
    # CLI path doesn't fetch memory entities from DB to keep this command fast.
    # It still writes an entities section (possibly empty) so file schema is stable.
    return []


__all__ = ["NAME", "HELP", "register", "run"]

