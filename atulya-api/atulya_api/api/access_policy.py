"""Canonical action mapping for the public HTTP surface."""

from __future__ import annotations


def required_action(method: str, path: str) -> str | None:
    """Return the action required by a core API route.

    Authentication, organization, platform, monitoring, and extension routes
    have their own explicit dependencies and are intentionally excluded.
    """

    method = method.upper()
    normalized = path.rstrip("/")
    if not normalized.startswith("/v1/"):
        return None
    if normalized.startswith(("/v1/auth", "/v1/orgs", "/v1/platform", "/v1/admin")):
        return None

    if "/webhooks" in normalized:
        return "webhook.manage"
    if "/forge" in normalized:
        if normalized.endswith("/export") or "/export/" in normalized:
            return "forge.export"
        return "forge.read" if method in {"GET", "HEAD"} else "forge.run"
    if "/brain" in normalized or "/mental-models" in normalized:
        return "brain.read" if method in {"GET", "HEAD"} else "brain.write"
    if "/reflect" in normalized:
        return "reflect.run"
    if "/recall" in normalized:
        return "memory.recall"
    if "/retain" in normalized or "/files" in normalized:
        return "memory.retain"
    if "/memories" in normalized or "/documents" in normalized or "/chunks" in normalized:
        if method == "DELETE":
            return "memory.delete"
        return "bank.read"

    if normalized == "/v1/banks":
        return "bank.read" if method in {"GET", "HEAD"} else "bank.write"
    if normalized.startswith("/v1/banks/"):
        if method == "DELETE":
            return "bank.delete"
        if "/config" in normalized or "/profile" in normalized and method not in {"GET", "HEAD"}:
            return "bank.config"
        return "bank.read" if method in {"GET", "HEAD"} else "bank.write"

    # Remaining v1 data routes are bank-bound operational surfaces.
    return "bank.read" if method in {"GET", "HEAD"} else "bank.write"


def bank_id_from_request(path_params: dict[str, str], query_params: dict[str, str]) -> str | None:
    return path_params.get("bank_id") or query_params.get("bank_id") or query_params.get("agent_id")


def bank_id_from_payload(payload: object) -> str | None:
    """Extract a bank boundary from common JSON request shapes."""
    if not isinstance(payload, dict):
        return None
    for key in ("bank_id", "agent_id", "source_bank_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    for key in ("request", "config", "payload"):
        nested = bank_id_from_payload(payload.get(key))
        if nested:
            return nested
    return None
