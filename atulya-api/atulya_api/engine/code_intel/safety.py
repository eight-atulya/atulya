"""Safety-tag classifier.

Two layers, both opt-in:

  1) Lightweight built-in pattern scanner that flags chunks containing
     auth/crypto/sql/eval/deserialization tokens. Always available, no
     deps. Good enough for v1 to surface safety-critical chunks.

  2) Optional Semgrep pass: if `semgrep` is installed and the codebase
     has a curated rulepack configured, we shell out and merge findings.
     Disabled by default to keep the pipeline fast and dependency-light.

Both return a normalized list of safety tag strings: e.g.
['auth', 'crypto', 'sql_string'].
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class SafetyFinding:
    chunk_key: str
    tags: tuple[str, ...]
    rule_ids: tuple[str, ...]


_PATTERNS: dict[str, re.Pattern[str]] = {
    "auth": re.compile(
        r"\b(login|logout|authenticate|authorise|authorize|jwt|oauth|password|hash_password|"
        r"verify_password|access_token|refresh_token|bearer|session|csrf|saml|sso|api_key)\b",
        re.IGNORECASE,
    ),
    "crypto": re.compile(
        r"\b(encrypt|decrypt|aes|rsa|ecdsa|ed25519|sha256|sha512|hmac|cipher|nonce|"
        r"private_key|public_key|crypto|fernet|kms|kdf|pbkdf2|scrypt|argon2|bcrypt)\b",
        re.IGNORECASE,
    ),
    "sql_string": re.compile(
        r"(SELECT|INSERT|UPDATE|DELETE|CREATE TABLE|ALTER TABLE|DROP TABLE)\s",
        re.IGNORECASE,
    ),
    "eval": re.compile(r"\b(eval|exec|compile|Function\s*\()\s*\(", re.IGNORECASE),
    "deserialization": re.compile(
        r"\b(pickle\.loads?|cPickle\.loads?|yaml\.load\s*\(|marshal\.loads?|"
        r"jsonpickle\.decode|fromXmlString)\b",
        re.IGNORECASE,
    ),
    "subprocess": re.compile(
        r"\b(subprocess\.(?:Popen|call|check_output|run|getoutput)|os\.system|os\.popen|"
        r"shell\s*=\s*True)\b",
        re.IGNORECASE,
    ),
    "network": re.compile(
        r"\b(requests\.(?:get|post|put|delete|patch)|httpx\.(?:get|post|put|delete|patch)|"
        r"urllib\.request|fetch\s*\(|axios\.(?:get|post))\b",
        re.IGNORECASE,
    ),
}


def scan_text_for_safety_tags(text: str) -> list[str]:
    """Run the built-in safety-tag patterns over a chunk's text.

    Returns a sorted, deduplicated list of tag strings.
    """

    if not text:
        return []
    hits: set[str] = set()
    for tag, pattern in _PATTERNS.items():
        if pattern.search(text):
            hits.add(tag)
    return sorted(hits)


def safety_priority(tags: Iterable[str]) -> float:
    """Normalize a tag set to a 0..1 priority for the significance score.

    auth/crypto/eval/deserialization weigh more than sql/network because
    they're the categories where AI agents most need context before
    suggesting changes.
    """

    weights = {
        "auth": 0.9,
        "crypto": 0.9,
        "eval": 0.85,
        "deserialization": 0.85,
        "sql_string": 0.55,
        "subprocess": 0.55,
        "network": 0.4,
    }
    score = 0.0
    for tag in tags:
        score = max(score, weights.get(tag, 0.0))
    return score


def run_semgrep_curated(
    *,
    repo_dir: str,
    rulepack: str | None = None,
    timeout_seconds: int = 60,
) -> list[SafetyFinding]:
    """Optional: call out to the `semgrep` CLI with a curated rulepack.

    Returns [] silently if semgrep isn't installed or the call fails.
    The caller maps `SafetyFinding.chunk_key` by joining `path:line` to
    the chunk index (line is 1-based)."""

    if not rulepack:
        return []
    try:
        proc = subprocess.run(
            ["semgrep", "--config", rulepack, "--json", "--quiet", "--timeout", str(timeout_seconds), repo_dir],
            capture_output=True,
            timeout=timeout_seconds + 5,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []
    except Exception:
        return []
    if proc.returncode not in (0, 1):
        return []

    import json

    try:
        payload = json.loads(proc.stdout or "{}")
    except Exception:
        return []

    findings: list[SafetyFinding] = []
    for result in payload.get("results", []):
        path = result.get("path") or ""
        line = result.get("start", {}).get("line", 1)
        rule_id = result.get("check_id", "semgrep_rule")
        tag = _semgrep_rule_to_tag(rule_id)
        chunk_key = f"{path}:{line}"
        findings.append(SafetyFinding(chunk_key=chunk_key, tags=(tag,), rule_ids=(rule_id,)))
    return findings


def _semgrep_rule_to_tag(rule_id: str) -> str:
    """Best-effort map a semgrep rule id to one of our normalized tags."""

    lower = rule_id.lower()
    if "auth" in lower or "jwt" in lower or "session" in lower:
        return "auth"
    if "crypto" in lower or "cipher" in lower or "hash" in lower:
        return "crypto"
    if "sql" in lower:
        return "sql_string"
    if "eval" in lower:
        return "eval"
    if "deserial" in lower or "pickle" in lower or "yaml" in lower:
        return "deserialization"
    if "subprocess" in lower or "shell" in lower or "command" in lower:
        return "subprocess"
    return "safety"
