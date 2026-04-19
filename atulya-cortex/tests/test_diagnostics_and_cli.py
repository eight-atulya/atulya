"""Batch D coverage: diagnostics + doctor / pairing / model / config / profile CLI."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from cortex import config as config_module
from cortex.cli import main as cli_main
from cortex.config import default_config
from cortex.diagnostics import (
    CheckResult,
    aggregate_status,
    check_config_present,
    check_home_layout,
    check_persona_present,
    check_python_version,
    check_required_imports,
    check_skills_installed,
    run_checks,
)
from cortex.home import ENV_HOME, ENV_PROFILE, CortexHome


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_HOME, str(tmp_path / "home"))
    monkeypatch.delenv(ENV_PROFILE, raising=False)
    for key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "ATULYA_API_KEY",
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_VERIFY_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def home(tmp_path):
    return CortexHome.resolve(root=tmp_path / "home").bootstrap()


# ---------------------------------------------------------------------------
# Individual diagnostics
# ---------------------------------------------------------------------------


class TestDiagnostics:
    def test_python_version_ok(self, home):
        cfg = default_config()
        result = asyncio.run(check_python_version(home, cfg))
        assert result.status == "ok"

    def test_required_imports_ok(self, home):
        cfg = default_config()
        result = asyncio.run(check_required_imports(home, cfg))
        assert result.status == "ok"

    def test_home_layout_warns_when_dir_missing(self, home):
        cfg = default_config()
        # Remove a directory the layout check looks for.
        for d in (home.skills_dir,):
            for child in d.iterdir() if d.exists() else []:
                child.unlink()
            if d.exists():
                d.rmdir()
        result = asyncio.run(check_home_layout(home, cfg))
        assert result.status == "warn"
        assert result.fix is not None
        # Fix re-bootstraps and brings us back to ok.
        fixed = result.fix(home, cfg)
        assert fixed.status == "ok"
        assert fixed.fixed

    def test_config_present_warns_then_fixes(self, home):
        cfg = default_config()
        if home.config_file.exists():
            home.config_file.unlink()
        result = asyncio.run(check_config_present(home, cfg))
        assert result.status == "warn"
        fixed = result.fix(home, cfg)
        assert fixed.status == "ok" and fixed.fixed
        assert home.config_file.exists()

    def test_persona_warn_when_missing(self, home):
        cfg = default_config()
        result = asyncio.run(check_persona_present(home, cfg))
        assert result.status == "warn"

    def test_skills_warn_when_empty(self, home):
        cfg = default_config()
        result = asyncio.run(check_skills_installed(home, cfg))
        assert result.status == "warn"
        # Fix runs the sync.
        fixed = result.fix(home, cfg)
        assert fixed.status == "ok" and fixed.fixed
        assert any(home.skills_dir.glob("*.md"))


class TestRunChecks:
    def test_skips_disabled_features(self, home):
        cfg = default_config()
        # Telegram + WhatsApp are disabled by default; their checks must skip.
        results = asyncio.run(run_checks(home, cfg))
        names = {r.name: r for r in results}
        assert names["telegram"].status == "skip"
        assert names["whatsapp"].status == "skip"

    def test_apply_fixes_idempotent(self, home):
        cfg = default_config()
        if home.config_file.exists():
            home.config_file.unlink()
        # 1st pass: warnings auto-fixed
        first = asyncio.run(run_checks(home, cfg, apply_fixes=True))
        # 2nd pass: nothing left to fix
        second = asyncio.run(run_checks(home, cfg, apply_fixes=True))
        # Same set of statuses in run 2 — no regressions
        first_status = {r.name: r.status for r in first}
        second_status = {r.name: r.status for r in second}
        for name in second_status:
            assert second_status[name] in (first_status.get(name, "ok"), "ok"), (
                f"check {name}: {first_status.get(name)} -> {second_status[name]}"
            )

    def test_aggregate_status_priority(self):
        results = [
            CheckResult("a", "ok", ""),
            CheckResult("b", "warn", ""),
            CheckResult("c", "skip", ""),
        ]
        assert aggregate_status(results) == "warn"
        results.append(CheckResult("d", "fail", ""))
        assert aggregate_status(results) == "fail"


# ---------------------------------------------------------------------------
# CLI: doctor
# ---------------------------------------------------------------------------


class TestDoctorCli:
    def test_doctor_exits_clean_after_setup(self, home, capsys):
        # Seed config + skills so doctor has nothing critical to report.
        config_module.seed(home)
        from cortex.skills_sync import sync as sync_skills

        sync_skills(home)
        rc = cli_main(["doctor", "--home", str(home.root)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "overall:" in out

    def test_doctor_json(self, home, capsys):
        config_module.seed(home)
        capsys.readouterr()
        rc = cli_main(["doctor", "--home", str(home.root), "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert "status" in payload and "results" in payload
        assert all("name" in r for r in payload["results"])

    def test_doctor_fix_seeds_missing_config(self, home, capsys):
        if home.config_file.exists():
            home.config_file.unlink()
        rc = cli_main(["doctor", "--home", str(home.root), "--fix"])
        # Seed config first via doctor --fix; it should now report ok.
        # If telegram/whatsapp configured-but-broken would push to fail; they aren't.
        assert rc == 0
        assert home.config_file.exists()


# ---------------------------------------------------------------------------
# CLI: pairing
# ---------------------------------------------------------------------------


class TestPairingCli:
    def test_list_empty(self, home, capsys):
        rc = cli_main(["pairing", "--home", str(home.root), "list"])
        assert rc == 0
        assert "no pairings" in capsys.readouterr().out

    def test_approve_then_list(self, home, capsys):
        rc = cli_main(["pairing", "--home", str(home.root), "approve", "telegram:42"])
        assert rc == 0
        capsys.readouterr()
        rc = cli_main(["pairing", "--home", str(home.root), "list", "--json"])
        assert rc == 0
        entries = json.loads(capsys.readouterr().out)
        assert any(e["channel"] == "telegram:42" and e["status"] == "approved" for e in entries)

    def test_revoke(self, home, capsys):
        cli_main(["pairing", "--home", str(home.root), "approve", "tui:local"])
        cli_main(["pairing", "--home", str(home.root), "revoke", "tui:local"])
        capsys.readouterr()
        rc = cli_main(["pairing", "--home", str(home.root), "list"])
        assert rc == 0
        assert "no pairings" in capsys.readouterr().out

    def test_pending(self, home, capsys):
        # Manually create a pending entry by constructing the store.
        from brainstem.reflexes import DMPairing
        from cortex.bus import Stimulus

        store = DMPairing(home.pairing_store)
        asyncio.run(store.evaluate(Stimulus(channel="telegram:7", sender="7")))
        rc = cli_main(["pairing", "--home", str(home.root), "pending"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "telegram:7" in out


# ---------------------------------------------------------------------------
# CLI: model
# ---------------------------------------------------------------------------


class TestModelCli:
    def test_show(self, home, capsys):
        config_module.seed(home)
        rc = cli_main(["model", "--home", str(home.root), "show"])
        assert rc == 0
        assert "provider" in capsys.readouterr().out

    def test_show_json(self, home, capsys):
        config_module.seed(home)
        capsys.readouterr()
        rc = cli_main(["model", "--home", str(home.root), "show", "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["provider"] == "lm_studio"

    def test_list_does_not_crash_when_nothing_reachable(self, home, capsys):
        # Even with no providers up, this should print the table and exit 0.
        rc = cli_main(["model", "--home", str(home.root), "list"])
        assert rc == 0


# ---------------------------------------------------------------------------
# CLI: config
# ---------------------------------------------------------------------------


class TestConfigCli:
    def test_path(self, home, capsys):
        rc = cli_main(["config", "--home", str(home.root), "path"])
        assert rc == 0
        assert str(home.config_file) in capsys.readouterr().out

    def test_show_then_check(self, home, capsys):
        config_module.seed(home)
        rc = cli_main(["config", "--home", str(home.root), "show"])
        assert rc == 0
        rc = cli_main(["config", "--home", str(home.root), "check"])
        assert rc == 0

    def test_get(self, home, capsys):
        config_module.seed(home)
        rc = cli_main(["config", "--home", str(home.root), "get", "model.provider"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "lm_studio"

    def test_get_unknown_key(self, home, capsys):
        config_module.seed(home)
        rc = cli_main(["config", "--home", str(home.root), "get", "model.no_such"])
        assert rc == 1

    def test_set_scalar(self, home, capsys):
        config_module.seed(home)
        rc = cli_main(["config", "--home", str(home.root), "set", "model.temperature", "0.7"])
        assert rc == 0
        cfg = config_module.load(home)
        assert cfg.model.temperature == 0.7

    def test_set_string(self, home, capsys):
        config_module.seed(home)
        rc = cli_main(["config", "--home", str(home.root), "set", "general.peer", '"laptop"'])
        assert rc == 0
        cfg = config_module.load(home)
        assert cfg.general.peer == "laptop"

    def test_set_validates_and_rolls_back(self, home, capsys):
        config_module.seed(home)
        before = home.config_file.read_text(encoding="utf-8")
        rc = cli_main(["config", "--home", str(home.root), "set", "general.log_level", '"BOGUS"'])
        assert rc == 1
        # File unchanged on failed validation.
        assert home.config_file.read_text(encoding="utf-8") == before

    def test_check_fails_on_corrupt(self, home, capsys):
        home.config_file.write_text('[general]\nlog_level = "BOGUS"\n', encoding="utf-8")
        rc = cli_main(["config", "--home", str(home.root), "check"])
        assert rc == 1

    def test_migrate_preserves_overrides(self, home, capsys):
        # User has a partial config that overrides one key.
        home.config_file.write_text('[general]\nname = "user-set"\n', encoding="utf-8")
        rc = cli_main(["config", "--home", str(home.root), "migrate"])
        assert rc == 0
        cfg = config_module.load(home)
        assert cfg.general.name == "user-set"
        # All other keys present too.
        assert cfg.dashboard.port == 9120


# ---------------------------------------------------------------------------
# CLI: profile
# ---------------------------------------------------------------------------


class TestProfileCli:
    def test_list_default_only(self, home, capsys):
        rc = cli_main(["profile", "--home", str(home.root), "list"])
        assert rc == 0
        assert "default" in capsys.readouterr().out

    def test_create_switch_show(self, home, capsys):
        rc = cli_main(["profile", "--home", str(home.root), "create", "work"])
        assert rc == 0
        rc = cli_main(["profile", "--home", str(home.root), "switch", "work"])
        assert rc == 0
        # `show` needs a fresh CortexHome resolution; the dispatcher does this for us.
        capsys.readouterr()
        rc = cli_main(["profile", "--home", str(home.root), "show"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "work"

    def test_delete_active_requires_force(self, home, capsys):
        cli_main(["profile", "--home", str(home.root), "create", "work"])
        cli_main(["profile", "--home", str(home.root), "switch", "work"])
        capsys.readouterr()
        rc = cli_main(["profile", "--home", str(home.root), "delete", "work"])
        assert rc == 1
        assert "currently active" in capsys.readouterr().out
        rc = cli_main(["profile", "--home", str(home.root), "delete", "work", "--force"])
        assert rc == 0

    def test_delete_default_refused(self, home, capsys):
        rc = cli_main(["profile", "--home", str(home.root), "delete", "default"])
        assert rc == 1
