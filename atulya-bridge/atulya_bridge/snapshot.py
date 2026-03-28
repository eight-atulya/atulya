"""System snapshot helpers for the Atulya bridge CLI."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
from typing import Any


def _safe_run(command: list[str]) -> str | None:
    """Run a command and return its first output line."""
    executable = shutil.which(command[0])
    if executable is None:
        return None

    try:
        completed = subprocess.run(
            [executable, *command[1:]],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    output = (completed.stdout or completed.stderr).strip()
    if not output:
        return None

    return output.splitlines()[0].strip()


def _memory_gb() -> float | None:
    """Best-effort total memory estimate in gigabytes."""
    if hasattr(os, "sysconf"):
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            total = int(pages) * int(page_size)
            return round(total / (1024**3), 2)
        except (OSError, TypeError, ValueError):
            pass

    if platform.system() == "Darwin":
        memsize = _safe_run(["sysctl", "-n", "hw.memsize"])
        if memsize and memsize.isdigit():
            return round(int(memsize) / (1024**3), 2)

    return None


def _disk_summary_gb(path: Path) -> dict[str, float] | None:
    """Return total and free disk in gigabytes for a path."""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None

    return {
        "total_gb": round(usage.total / (1024**3), 2),
        "free_gb": round(usage.free / (1024**3), 2),
    }


def _toolchain_versions() -> dict[str, str]:
    """Collect a compact toolchain summary."""
    commands = {
        "python": ["python3", "--version"],
        "uv": ["uv", "--version"],
        "node": ["node", "--version"],
        "npm": ["npm", "--version"],
        "cargo": ["cargo", "--version"],
        "docker": ["docker", "--version"],
        "git": ["git", "--version"],
    }
    versions: dict[str, str] = {}
    for name, command in commands.items():
        value = _safe_run(command)
        if value:
            versions[name] = value
    return versions


def _primary_outbound_ip() -> str | None:
    """Return the preferred outbound local IP without sending payload traffic."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return None


def _network_scope(ip_address: str | None) -> str:
    """Return a privacy-preserving network summary."""
    if not ip_address:
        return "unavailable"
    if ip_address.startswith("127.") or ip_address == "::1":
        return "loopback"
    if ip_address.startswith("10.") or ip_address.startswith("192.168.") or ip_address.startswith("172."):
        return "private-network"
    return "public-or-routed"


def _local_addresses(hostname: str) -> list[str]:
    """Return deduplicated local interface addresses for the host."""
    addresses: set[str] = set()
    try:
        for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
            if family == socket.AF_INET:
                addresses.add(sockaddr[0])
            elif family == socket.AF_INET6:
                addresses.add(sockaddr[0])
    except socket.gaierror:
        return []

    return sorted(addresses)


def sanitize_bank_id(value: str) -> str:
    """Normalize text into a safe bank identifier."""
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    collapsed = "-".join(part for part in cleaned.split("-") if part)
    return collapsed or "local-system"


@dataclass(slots=True)
class SystemSnapshot:
    """Structured first-connection snapshot."""

    captured_at: str
    hostname: str
    platform: str
    system: str
    release: str
    machine: str
    processor: str
    python_version: str
    workspace_name: str
    cpu_count: int | None
    memory_gb: float | None
    home_disk_total_gb: float | None
    home_disk_free_gb: float | None
    network_scope: str
    has_ipv6: bool
    toolchain: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        """Return the snapshot as a JSON-friendly dict."""
        return asdict(self)


def collect_system_snapshot() -> SystemSnapshot:
    """Collect a safe machine summary for Atulya's first connection."""
    hostname = socket.gethostname()
    home_disk = _disk_summary_gb(Path.home())
    primary_ip = _primary_outbound_ip()
    local_addresses = _local_addresses(hostname)
    return SystemSnapshot(
        captured_at=datetime.now(UTC).isoformat(),
        hostname=hostname,
        platform=platform.platform(),
        system=platform.system(),
        release=platform.release(),
        machine=platform.machine(),
        processor=platform.processor(),
        python_version=platform.python_version(),
        workspace_name=Path.cwd().name,
        cpu_count=os.cpu_count(),
        memory_gb=_memory_gb(),
        home_disk_total_gb=home_disk["total_gb"] if home_disk else None,
        home_disk_free_gb=home_disk["free_gb"] if home_disk else None,
        network_scope=_network_scope(primary_ip),
        has_ipv6=any(":" in address for address in local_addresses),
        toolchain=_toolchain_versions(),
    )


def render_memory_content(snapshot: SystemSnapshot) -> str:
    """Render the first-connection snapshot as retainable markdown."""
    toolchain_lines = "\n".join(f"- {name}: {version}" for name, version in snapshot.toolchain.items()) or "- none detected"
    return (
        "# First connection snapshot\n\n"
        "Atulya attached to a machine and recorded a safe environment summary for future grounding.\n\n"
        "## Identity\n"
        f"- Captured at: {snapshot.captured_at}\n"
        f"- Hostname: {snapshot.hostname}\n"
        f"- Workspace name: {snapshot.workspace_name}\n\n"
        "## Platform\n"
        f"- Platform: {snapshot.platform}\n"
        f"- System: {snapshot.system}\n"
        f"- Release: {snapshot.release}\n"
        f"- Architecture: {snapshot.machine}\n"
        f"- Processor: {snapshot.processor or 'unknown'}\n"
        f"- Python: {snapshot.python_version}\n\n"
        "## Capacity\n"
        f"- CPU count: {snapshot.cpu_count if snapshot.cpu_count is not None else 'unknown'}\n"
        f"- Memory (GB): {snapshot.memory_gb if snapshot.memory_gb is not None else 'unknown'}\n"
        f"- Home disk total (GB): {snapshot.home_disk_total_gb if snapshot.home_disk_total_gb is not None else 'unknown'}\n"
        f"- Home disk free (GB): {snapshot.home_disk_free_gb if snapshot.home_disk_free_gb is not None else 'unknown'}\n\n"
        "## Network\n"
        f"- Network scope: {snapshot.network_scope}\n"
        f"- IPv6 available: {'yes' if snapshot.has_ipv6 else 'no'}\n\n"
        "## Toolchain\n"
        f"{toolchain_lines}\n"
    )
