"""Console entrypoint for the Atulya bridge package."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .snapshot import SystemSnapshot, collect_system_snapshot, render_memory_content, sanitize_bank_id


def _default_profile() -> str:
    return os.getenv("ATULYA_BRIDGE_PROFILE") or os.getenv("ATULYA_EMBED_PROFILE") or "default"


def _default_bank_id(snapshot: SystemSnapshot) -> str:
    return sanitize_bank_id(f"system-{snapshot.hostname}")


def _resolve_llm_config(args: argparse.Namespace) -> dict[str, str | None]:
    provider = args.llm_provider or os.getenv("ATULYA_API_LLM_PROVIDER") or os.getenv("ATULYA_LLM_PROVIDER") or "openai"
    api_key = args.llm_api_key or os.getenv("ATULYA_API_LLM_API_KEY") or os.getenv("ATULYA_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = args.llm_model or os.getenv("ATULYA_API_LLM_MODEL") or os.getenv("ATULYA_LLM_MODEL") or "gpt-4o-mini"
    base_url = args.llm_base_url or os.getenv("ATULYA_API_LLM_BASE_URL") or os.getenv("ATULYA_LLM_BASE_URL")
    return {
        "provider": provider,
        "api_key": api_key,
        "model": model,
        "base_url": base_url,
    }


def _print_snapshot(snapshot: SystemSnapshot, bank_id: str, profile: str) -> None:
    print("Atulya first connection", flush=True)
    print(f"  profile: {profile}", flush=True)
    print(f"  bank_id: {bank_id}", flush=True)
    print(f"  host: {snapshot.hostname}", flush=True)
    print(f"  system: {snapshot.system} {snapshot.release} ({snapshot.machine})", flush=True)
    print(f"  python: {snapshot.python_version}", flush=True)
    print(f"  workspace_name: {snapshot.workspace_name}", flush=True)
    print(f"  cpu_count: {snapshot.cpu_count if snapshot.cpu_count is not None else 'unknown'}", flush=True)
    print(f"  memory_gb: {snapshot.memory_gb if snapshot.memory_gb is not None else 'unknown'}", flush=True)
    print(f"  home_disk_free_gb: {snapshot.home_disk_free_gb if snapshot.home_disk_free_gb is not None else 'unknown'}", flush=True)
    print(f"  network_scope: {snapshot.network_scope}", flush=True)
    print(f"  has_ipv6: {'yes' if snapshot.has_ipv6 else 'no'}", flush=True)
    if snapshot.toolchain:
        print("  toolchain:", flush=True)
        for name, version in snapshot.toolchain.items():
            print(f"    - {name}: {version}", flush=True)


def _retain_snapshot(args: argparse.Namespace, snapshot: SystemSnapshot, bank_id: str) -> tuple[str, str]:
    llm = _resolve_llm_config(args)
    api_key = llm["api_key"]
    if not api_key:
        return (
            "failed",
            "LLM credentials are not configured. Snapshot was captured locally only. "
            "Set ATULYA_API_LLM_API_KEY, ATULYA_API_LLM_PROVIDER, and ATULYA_API_LLM_MODEL to persist it.",
        )

    from atulya import AtulyaEmbedded

    client = AtulyaEmbedded(
        profile=args.profile,
        llm_provider=str(llm["provider"]),
        llm_api_key=str(api_key),
        llm_model=str(llm["model"]),
        llm_base_url=str(llm["base_url"]) if llm["base_url"] else None,
        log_level="warning",
    )

    try:
        client.create_bank(
            bank_id=bank_id,
            name=f"{snapshot.hostname} system bridge",
            reflect_mission="Remember this machine's environment so future reasoning stays grounded in real system constraints.",
            retain_mission="Extract durable facts about the machine, runtime, network surface, and available toolchain.",
            enable_observations=True,
            observations_mission="Consolidate recurring machine constraints, capabilities, and environmental patterns.",
        )
        response = client.retain(
            bank_id=bank_id,
            content=render_memory_content(snapshot),
            context="first_connection",
            document_id=f"first-connection-{snapshot.hostname}",
            metadata={
                "source": "atulya-cli",
                "event": "first_connection",
                "hostname": snapshot.hostname,
                "system": snapshot.system,
                "machine": snapshot.machine,
                "network_scope": snapshot.network_scope,
            },
            tags=["system", "bootstrap", "first-connection"],
        )
    except Exception as exc:  # noqa: BLE001
        return "failed", f"Snapshot capture succeeded but retain failed: {exc}"
    finally:
        client.close()

    if not response.success:
        return "failed", "Snapshot capture succeeded but retain did not report success."

    return "stored", f"Stored first connection memory in bank '{bank_id}' using profile '{args.profile}'."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atulya",
        description="Atulya bridge CLI - connect this machine to memory.",
    )
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Capture and optionally store the first connection snapshot.")
    init_parser.add_argument("--profile", default=_default_profile(), help="Atulya embed profile to use.")
    init_parser.add_argument("--bank-id", help="Bank ID to store the connection in.")
    init_parser.add_argument("--print-only", action="store_true", help="Capture and print the snapshot without storing it.")
    init_parser.add_argument("--store", action="store_true", help="Persist the snapshot into Atulya memory.")
    init_parser.add_argument("--json", action="store_true", help="Print the raw snapshot as JSON.")
    init_parser.add_argument("--llm-provider", help="Override the LLM provider for local retain.")
    init_parser.add_argument("--llm-api-key", help="Override the LLM API key for local retain.")
    init_parser.add_argument("--llm-model", help="Override the LLM model for local retain.")
    init_parser.add_argument("--llm-base-url", help="Override the LLM base URL for local retain.")

    snapshot_parser = subparsers.add_parser("snapshot", help="Alias for init.")
    for action in init_parser._actions[1:]:
        snapshot_parser._add_action(action)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        args = parser.parse_args(["init", *(argv or [])])

    snapshot = collect_system_snapshot()
    bank_id = args.bank_id or _default_bank_id(snapshot)

    if args.json:
        print(json.dumps(snapshot.as_dict(), indent=2, sort_keys=True))
    else:
        _print_snapshot(snapshot, bank_id=bank_id, profile=args.profile)

    if args.print_only:
        print("\nSnapshot captured without storing it.", flush=True)
        return 0

    if not args.store:
        print(
            "\nPreview only. Run `atulya init --store` after reviewing the snapshot if you want to persist it.",
            flush=True,
        )
        return 0

    print("\nPersisting snapshot into Atulya memory...", flush=True)
    status, message = _retain_snapshot(args, snapshot, bank_id)
    print(f"\n{message}", flush=True)
    return 1 if status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
