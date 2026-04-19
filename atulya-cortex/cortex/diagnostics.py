"""diagnostics.py — composable health checks.

`atulya-cortex doctor` and the future dashboard both render these. Each
check is a stateless function that takes `(home, config)` and returns a
`CheckResult`. Some checks return a `fix` callable; `doctor --fix`
invokes those.

Design rules:
- A check NEVER raises; it catches its own exceptions and returns a
  `fail` result with the message instead. The runner has a defensive
  catch as well, but checks should not rely on it.
- A check that depends on optional config (e.g. Telegram, WhatsApp) MUST
  return `skip` when that feature is disabled — never `fail`.
- A check that needs the network MUST honour `timeout_s` (default 1.5s)
  so doctor never hangs.

Adding a new check:
1. Write `async def check_<name>(home, config) -> CheckResult`.
2. Add it to `DEFAULT_CHECKS` (order matters — checks earlier in the
   list run first; dependencies should be ordered before dependents).
"""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal

import httpx

from cortex.config import CortexConfig
from cortex.config import seed as seed_config
from cortex.home import CortexHome

CheckStatus = Literal["ok", "warn", "fail", "skip"]


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    message: str
    fix: Callable[[CortexHome, CortexConfig], "CheckResult"] | None = None
    fixed: bool = False
    details: dict = field(default_factory=dict)

    @property
    def emoji(self) -> str:
        # No real emoji here; ASCII only so logs in CI / CRT terminals work.
        return {"ok": "OK ", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}[self.status]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "fixable": self.fix is not None,
            "fixed": self.fixed,
            "details": dict(self.details),
        }


CheckCallable = Callable[[CortexHome, CortexConfig], Awaitable[CheckResult]]


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


async def check_python_version(home: CortexHome, config: CortexConfig) -> CheckResult:
    minimum = (3, 11)
    actual = sys.version_info[:2]
    if actual < minimum:
        return CheckResult(
            "python>=3.11",
            "fail",
            f"need >= {minimum[0]}.{minimum[1]}, have {actual[0]}.{actual[1]}",
        )
    return CheckResult("python>=3.11", "ok", f"{actual[0]}.{actual[1]}")


async def check_required_imports(home: CortexHome, config: CortexConfig) -> CheckResult:
    required = ["pydantic", "httpx", "rich", "diskcache", "tomli_w"]
    missing: list[str] = []
    for name in required:
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    if missing:
        return CheckResult("required imports", "fail", f"missing: {', '.join(missing)}")
    return CheckResult("required imports", "ok", "all present")


async def check_home_layout(home: CortexHome, config: CortexConfig) -> CheckResult:
    expected = (
        home.root,
        home.profile_root,
        home.pairing_dir,
        home.state_dir,
        home.skills_dir,
        home.cron_dir,
        home.cache_root,
        home.llm_cache_dir,
        home.embedding_cache_dir,
        home.whatsapp_dir,
        home.whatsapp_session_dir,
        home.logs_dir,
        home.profiles_root,
    )
    missing = [str(p) for p in expected if not p.is_dir()]
    if missing:
        return CheckResult(
            "home directory layout",
            "warn",
            f"missing dirs: {', '.join(missing)}",
            fix=_fix_home_layout,
        )
    return CheckResult("home directory layout", "ok", str(home.root))


def _fix_home_layout(home: CortexHome, config: CortexConfig) -> CheckResult:
    home.bootstrap()
    return CheckResult("home directory layout", "ok", "bootstrapped", fixed=True)


async def check_config_present(home: CortexHome, config: CortexConfig) -> CheckResult:
    if not home.config_file.exists():
        return CheckResult(
            "config.toml present",
            "warn",
            f"missing at {home.config_file}; will be seeded by --fix",
            fix=_fix_seed_config,
        )
    return CheckResult("config.toml present", "ok", str(home.config_file))


def _fix_seed_config(home: CortexHome, config: CortexConfig) -> CheckResult:
    seed_config(home)
    return CheckResult("config.toml present", "ok", "seeded from template", fixed=True)


async def check_persona_present(home: CortexHome, config: CortexConfig) -> CheckResult:
    if not home.persona_file.exists():
        return CheckResult(
            "persona.md present",
            "warn",
            f"no persona at {home.persona_file}; run `atulya-cortex setup persona`",
        )
    return CheckResult("persona.md present", "ok", str(home.persona_file))


async def check_skills_installed(home: CortexHome, config: CortexConfig) -> CheckResult:
    if not home.skills_dir.exists():
        return CheckResult(
            "skills installed",
            "warn",
            "skills dir missing; run `atulya-cortex skills sync`",
            fix=_fix_skills_sync,
        )
    count = sum(1 for _ in home.skills_dir.glob("*.md"))
    if count == 0:
        return CheckResult(
            "skills installed",
            "warn",
            "no skills found; run `atulya-cortex skills sync`",
            fix=_fix_skills_sync,
        )
    return CheckResult("skills installed", "ok", f"{count} markdown skills")


def _fix_skills_sync(home: CortexHome, config: CortexConfig) -> CheckResult:
    from cortex.skills_sync import sync as sync_skills

    result = sync_skills(home)
    if result.errors:
        return CheckResult(
            "skills installed",
            "fail",
            "; ".join(result.errors),
            fixed=False,
        )
    return CheckResult(
        "skills installed",
        "ok",
        f"copied {len(result.copied)}, skipped {len(result.skipped)}",
        fixed=True,
    )


async def check_pairing_store(home: CortexHome, config: CortexConfig) -> CheckResult:
    from brainstem.reflexes import DMPairing

    try:
        store = DMPairing(home.pairing_store)
    except OSError as exc:
        return CheckResult("pairing store", "fail", str(exc))
    pending = store.pending()
    msg = f"{len(store.list())} pairings ({len(pending)} pending)"
    return CheckResult("pairing store", "ok", msg, details={"pending": pending})


async def check_atulya_api(home: CortexHome, config: CortexConfig) -> CheckResult:
    url = config.memory.api_url.rstrip("/") + "/health"
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(url)
        if resp.status_code == 200:
            return CheckResult("atulya-api reachable", "ok", url)
        return CheckResult(
            "atulya-api reachable",
            "warn",
            f"{url} returned status {resp.status_code} — memory recall will be unavailable",
        )
    except (httpx.RequestError, httpx.TimeoutException) as exc:
        return CheckResult(
            "atulya-api reachable",
            "warn",
            f"{url} unreachable ({exc.__class__.__name__}); memory recall will be unavailable",
        )


async def check_model_provider(home: CortexHome, config: CortexConfig) -> CheckResult:
    provider = config.model.provider
    if provider == "lm_studio":
        url = config.model.base_url.rstrip("/") + "/models"
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                resp = await client.get(url)
            if resp.status_code == 200:
                return CheckResult("model provider reachable", "ok", f"lm_studio at {url}")
            return CheckResult(
                "model provider reachable",
                "warn",
                f"{url} returned status {resp.status_code}",
            )
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            return CheckResult(
                "model provider reachable",
                "warn",
                f"{url} unreachable ({exc.__class__.__name__})",
            )
    elif provider == "ollama":
        url = config.model.base_url.rstrip("/v1").rstrip("/") + "/api/tags"
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                resp = await client.get(url)
            if resp.status_code == 200:
                return CheckResult("model provider reachable", "ok", f"ollama at {url}")
            return CheckResult(
                "model provider reachable",
                "warn",
                f"{url} returned status {resp.status_code}",
            )
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            return CheckResult(
                "model provider reachable",
                "warn",
                f"{url} unreachable ({exc.__class__.__name__})",
            )
    else:
        # For hosted providers, presence of the API key env var is the cheapest probe.
        key_env = config.model.api_key_env
        if key_env and not os.environ.get(key_env):
            return CheckResult(
                "model provider reachable",
                "warn",
                f"${key_env} not set; hosted provider {provider} will fail at first call",
            )
        return CheckResult("model provider reachable", "ok", f"{provider} key {key_env} is set")


async def check_telegram(home: CortexHome, config: CortexConfig) -> CheckResult:
    if not config.telegram.enabled:
        return CheckResult("telegram", "skip", "disabled in config")
    token = os.environ.get(config.telegram.token_env, "")
    if not token:
        return CheckResult(
            "telegram",
            "fail",
            f"${config.telegram.token_env} not set; cannot connect",
        )
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(url)
        if resp.status_code == 200 and resp.json().get("ok"):
            bot = resp.json().get("result", {}).get("username", "?")
            return CheckResult("telegram", "ok", f"bot @{bot} reachable")
        return CheckResult("telegram", "fail", f"getMe returned {resp.status_code}")
    except (httpx.RequestError, httpx.TimeoutException) as exc:
        return CheckResult("telegram", "warn", f"unreachable ({exc.__class__.__name__})")


async def check_whatsapp(home: CortexHome, config: CortexConfig) -> CheckResult:
    if not config.whatsapp.enabled:
        return CheckResult("whatsapp", "skip", "disabled in config")
    if config.whatsapp.backend == "cloud":
        for slot in (
            config.whatsapp.phone_number_id_env,
            config.whatsapp.access_token_env,
            config.whatsapp.verify_token_env,
        ):
            if not os.environ.get(slot, ""):
                return CheckResult("whatsapp", "fail", f"${slot} not set")
        return CheckResult("whatsapp", "ok", "cloud backend env vars present")
    # baileys
    if not home.whatsapp_session_dir.exists():
        return CheckResult(
            "whatsapp",
            "warn",
            "no Baileys session yet; run `atulya-cortex whatsapp --pair-only`",
        )
    return CheckResult("whatsapp", "ok", f"baileys session at {home.whatsapp_session_dir}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


DEFAULT_CHECKS: tuple[CheckCallable, ...] = (
    check_python_version,
    check_required_imports,
    check_home_layout,
    check_config_present,
    check_persona_present,
    check_skills_installed,
    check_pairing_store,
    check_atulya_api,
    check_model_provider,
    check_telegram,
    check_whatsapp,
)


async def run_checks(
    home: CortexHome,
    config: CortexConfig,
    *,
    checks: tuple[CheckCallable, ...] | None = None,
    apply_fixes: bool = False,
) -> list[CheckResult]:
    selected = checks if checks is not None else DEFAULT_CHECKS
    results: list[CheckResult] = []
    for check in selected:
        try:
            res = await check(home, config)
        except Exception as exc:
            res = CheckResult(name=check.__name__, status="fail", message=f"check crashed: {exc}")
        if apply_fixes and res.fix is not None and res.status in ("warn", "fail"):
            try:
                res = res.fix(home, config)
            except Exception as exc:
                res = CheckResult(
                    name=res.name,
                    status="fail",
                    message=f"fix crashed: {exc}",
                )
        results.append(res)
    return results


def aggregate_status(results: list[CheckResult]) -> CheckStatus:
    statuses = {r.status for r in results}
    for level in ("fail", "warn", "ok", "skip"):
        if level in statuses:
            return level  # type: ignore[return-value]
    return "ok"


__all__ = [
    "CheckCallable",
    "CheckResult",
    "CheckStatus",
    "DEFAULT_CHECKS",
    "aggregate_status",
    "run_checks",
]
