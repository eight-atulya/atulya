"""Batch C coverage: SetupWizard sections + skills_sync + CLI shells."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import cortex.skills_sync as skills_sync_module
from cortex import config as config_module
from cortex import skills_sync
from cortex.home import ENV_HOME, ENV_PROFILE, CortexHome
from cortex.setup_wizard import (
    ConsolePrompter,
    NonInteractiveError,
    ProviderProbe,
    ScriptedPrompter,
    SetupWizard,
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_HOME, str(tmp_path / "home"))
    monkeypatch.delenv(ENV_PROFILE, raising=False)
    # Ensure no real env keys leak into the wizard
    for key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "ATULYA_API_KEY",
        "GROQ_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def home(tmp_path):
    h = CortexHome.resolve(root=tmp_path / "home").bootstrap()
    return h


def _mock_probe(**kwargs):
    return lambda: ProviderProbe(**kwargs)


# ---------------------------------------------------------------------------
# SetupWizard.run_home
# ---------------------------------------------------------------------------


class TestRunHome:
    def test_creates_config_file_first_time(self, home):
        wizard = SetupWizard(home, ScriptedPrompter(), probe_fn=_mock_probe())
        result = wizard.run_home()
        assert result.ok
        assert home.config_file.exists()
        assert str(home.config_file) in result.changed

    def test_idempotent_second_call(self, home):
        wizard = SetupWizard(home, ScriptedPrompter(), probe_fn=_mock_probe())
        wizard.run_home()
        result = wizard.run_home()
        assert result.ok
        assert result.changed == []
        assert str(home.config_file) in result.skipped


# ---------------------------------------------------------------------------
# SetupWizard.run_model
# ---------------------------------------------------------------------------


class TestRunModel:
    def test_lm_studio_path(self, home):
        prompter = ScriptedPrompter(
            choices=["lm_studio"],
            answers=["http://localhost:1234/v1", "google/gemma-3-4b"],
        )
        wizard = SetupWizard(home, prompter, probe_fn=_mock_probe(lm_studio=True))
        result = wizard.run_model()
        assert result.ok, result.errors
        cfg = config_module.load(home)
        assert cfg.model.provider == "lm_studio"
        assert cfg.model.base_url == "http://localhost:1234/v1"
        assert cfg.model.model == "google/gemma-3-4b"
        # No secret should be written for a local provider.
        assert not home.env_file.exists() or "OPENAI_API_KEY=" not in home.env_file.read_text(encoding="utf-8")

    def test_openai_path_writes_secret(self, home):
        prompter = ScriptedPrompter(
            choices=["openai"],
            answers=["https://api.openai.com/v1", "gpt-4o-mini", "OPENAI_API_KEY"],
            secrets=["sk-test-1234"],
        )
        wizard = SetupWizard(home, prompter, probe_fn=_mock_probe(openai_key=True))
        result = wizard.run_model()
        assert result.ok, result.errors
        assert "OPENAI_API_KEY" in result.secrets_recorded
        env_text = home.env_file.read_text(encoding="utf-8")
        assert "OPENAI_API_KEY=sk-test-1234" in env_text
        assert os.environ["OPENAI_API_KEY"] == "sk-test-1234"

    def test_skip_choice_makes_no_changes(self, home):
        prompter = ScriptedPrompter(choices=["skip"])
        wizard = SetupWizard(home, prompter, probe_fn=_mock_probe())
        result = wizard.run_model()
        assert result.ok
        assert result.changed == []

    def test_reachable_providers_promoted_first(self, home):
        captured: dict = {}

        class CapturingPrompter(ScriptedPrompter):
            def ask_choice(self, prompt, choices, *, default_index=0):
                captured["choices"] = list(choices)
                return super().ask_choice(prompt, choices, default_index=default_index)

        prompter = CapturingPrompter(choices=["skip"])
        wizard = SetupWizard(home, prompter, probe_fn=_mock_probe(ollama=True))
        wizard.run_model()
        # Reachable provider should appear before unreachable ones.
        assert captured["choices"][0] == "ollama"


# ---------------------------------------------------------------------------
# SetupWizard.run_persona
# ---------------------------------------------------------------------------


class TestRunPersona:
    def test_writes_persona_with_substituted_fields(self, home):
        prompter = ScriptedPrompter(
            answers=["Anurag", "Atulya", "warm but terse", "curious, practical, honest"],
            yes_nos=[True],
        )
        wizard = SetupWizard(home, prompter, probe_fn=_mock_probe())
        result = wizard.run_persona()
        assert result.ok
        text = home.persona_file.read_text(encoding="utf-8")
        assert "Anurag" in text
        assert "Atulya" in text
        assert "warm but terse" in text
        assert "- curious" in text
        assert "{{" not in text  # all template tokens substituted

    def test_overwrite_declined(self, home):
        home.persona_file.write_text("# original", encoding="utf-8")
        prompter = ScriptedPrompter(yes_nos=[False])
        wizard = SetupWizard(home, prompter, probe_fn=_mock_probe())
        result = wizard.run_persona()
        assert result.ok
        assert str(home.persona_file) in result.skipped
        assert home.persona_file.read_text(encoding="utf-8") == "# original"


# ---------------------------------------------------------------------------
# SetupWizard.run_bank
# ---------------------------------------------------------------------------


class TestRunBank:
    def test_no_token_path(self, home):
        prompter = ScriptedPrompter(
            answers=["my-bank", "http://localhost:8888"],
            choices=["api"],
            yes_nos=[False],
        )
        wizard = SetupWizard(home, prompter, probe_fn=_mock_probe())
        result = wizard.run_bank()
        assert result.ok
        cfg = config_module.load(home)
        assert cfg.memory.bank_id == "my-bank"
        assert cfg.memory.peer_banks_backend == "api"
        assert result.secrets_recorded == []

    def test_with_token_path(self, home):
        prompter = ScriptedPrompter(
            answers=["my-bank", "http://api.local:8000", "ATULYA_API_KEY"],
            choices=["embedded"],
            yes_nos=[True],
            secrets=["secret-token"],
        )
        wizard = SetupWizard(home, prompter, probe_fn=_mock_probe())
        result = wizard.run_bank()
        assert result.ok
        assert "ATULYA_API_KEY" in result.secrets_recorded
        env_text = home.env_file.read_text(encoding="utf-8")
        assert "ATULYA_API_KEY=secret-token" in env_text


# ---------------------------------------------------------------------------
# SetupWizard.run_skills
# ---------------------------------------------------------------------------


class TestRunSkills:
    def test_first_run_copies_all(self, home):
        wizard = SetupWizard(home, ScriptedPrompter(), probe_fn=_mock_probe())
        result = wizard.run_skills()
        assert result.ok, result.errors
        copied = sorted(p.name for p in home.skills_dir.glob("*.md"))
        assert {"summarise.md", "translate.md", "debug.md", "brainstorm.md", "plan.md"}.issubset(set(copied))
        for name in copied:
            assert any(name in line for line in result.changed)

    def test_second_run_is_noop(self, home):
        wizard = SetupWizard(home, ScriptedPrompter(), probe_fn=_mock_probe())
        wizard.run_skills()
        result = wizard.run_skills()
        assert result.changed == []
        assert len(result.skipped) >= 5


# ---------------------------------------------------------------------------
# SetupWizard.run_telegram / run_whatsapp
# ---------------------------------------------------------------------------


class TestRunTelegram:
    def test_disable(self, home):
        prompter = ScriptedPrompter(yes_nos=[False])
        wizard = SetupWizard(home, prompter, probe_fn=_mock_probe())
        result = wizard.run_telegram()
        assert result.ok
        assert config_module.load(home).telegram.enabled is False

    def test_enable_with_secret_and_allowlist(self, home):
        prompter = ScriptedPrompter(
            yes_nos=[True],
            answers=["TELEGRAM_BOT_TOKEN", "111,222"],
            secrets=["bot-token-xyz"],
        )
        wizard = SetupWizard(home, prompter, probe_fn=_mock_probe())
        result = wizard.run_telegram()
        assert result.ok, result.errors
        cfg = config_module.load(home)
        assert cfg.telegram.enabled is True
        assert cfg.telegram.allowed_users == [111, 222]
        env = home.env_file.read_text(encoding="utf-8")
        assert "TELEGRAM_BOT_TOKEN=bot-token-xyz" in env

    def test_invalid_user_id_recorded_as_error(self, home):
        prompter = ScriptedPrompter(
            yes_nos=[True],
            answers=["TELEGRAM_BOT_TOKEN", "111,abc"],
            secrets=[""],
        )
        wizard = SetupWizard(home, prompter, probe_fn=_mock_probe())
        result = wizard.run_telegram()
        assert not result.ok
        assert any("abc" in e for e in result.errors)


class TestRunWhatsapp:
    def test_disable(self, home):
        prompter = ScriptedPrompter(yes_nos=[False])
        wizard = SetupWizard(home, prompter, probe_fn=_mock_probe())
        result = wizard.run_whatsapp()
        assert result.ok
        assert config_module.load(home).whatsapp.enabled is False

    def test_baileys_enable_no_secrets(self, home):
        prompter = ScriptedPrompter(yes_nos=[True], choices=["baileys"])
        wizard = SetupWizard(home, prompter, probe_fn=_mock_probe())
        result = wizard.run_whatsapp()
        assert result.ok, result.errors
        cfg = config_module.load(home)
        assert cfg.whatsapp.enabled is True
        assert cfg.whatsapp.backend == "baileys"
        assert result.secrets_recorded == []

    def test_cloud_enable_writes_three_secrets(self, home):
        prompter = ScriptedPrompter(
            yes_nos=[True],
            choices=["cloud"],
            answers=[
                "WHATSAPP_PHONE_NUMBER_ID",
                "WHATSAPP_ACCESS_TOKEN",
                "WHATSAPP_VERIFY_TOKEN",
            ],
            secrets=["phone-1", "tok-1", "verify-1"],
        )
        wizard = SetupWizard(home, prompter, probe_fn=_mock_probe())
        result = wizard.run_whatsapp()
        assert result.ok, result.errors
        assert set(result.secrets_recorded) == {
            "WHATSAPP_PHONE_NUMBER_ID",
            "WHATSAPP_ACCESS_TOKEN",
            "WHATSAPP_VERIFY_TOKEN",
        }


# ---------------------------------------------------------------------------
# SetupWizard.run_all
# ---------------------------------------------------------------------------


class TestRunAll:
    def test_full_flow(self, home):
        # Section call order on a fresh home:
        # home  -> 0 prompts
        # model -> 1 choice, 2 answers (lm_studio base_url, model)
        # persona -> 4 answers (operator, brain, voice, traits) — no overwrite prompt because persona file does not exist yet
        # bank -> 2 answers (bank_id, api_url), 1 choice (backend), 1 yes_no (no token)
        # skills -> 0 prompts
        # telegram -> 1 yes_no (disable)
        # whatsapp -> 1 yes_no (disable)
        prompter = ScriptedPrompter(
            choices=["lm_studio", "embedded"],
            answers=[
                "http://localhost:1234/v1",
                "google/gemma-3-4b",
                "Anurag",
                "Atulya",
                "warm but terse",
                "curious, practical, honest",
                "atulya-cortex",
                "http://localhost:8888",
            ],
            yes_nos=[False, False, False],
        )
        wizard = SetupWizard(home, prompter, probe_fn=_mock_probe(lm_studio=True))
        results = wizard.run_all()
        for r in results:
            assert r.ok, f"section {r.name} failed: {r.errors}"
        # Verify side effects
        cfg = config_module.load(home)
        assert cfg.model.provider == "lm_studio"
        assert cfg.memory.bank_id == "atulya-cortex"
        assert home.persona_file.exists()
        assert (home.skills_dir / "summarise.md").exists()


# ---------------------------------------------------------------------------
# Non-interactive prompter behaviour
# ---------------------------------------------------------------------------


class TestNonInteractive:
    def test_console_prompter_refuses_when_non_interactive(self):
        prompter = ConsolePrompter(interactive=False)
        with pytest.raises(NonInteractiveError):
            prompter.ask("anything")
        with pytest.raises(NonInteractiveError):
            prompter.ask_secret("anything")
        with pytest.raises(NonInteractiveError):
            prompter.ask_yes_no("anything")
        with pytest.raises(NonInteractiveError):
            prompter.ask_choice("anything", ["a", "b"])

    def test_run_all_collects_non_interactive_errors(self, home):
        prompter = ConsolePrompter(interactive=False)
        wizard = SetupWizard(home, prompter, probe_fn=_mock_probe())
        results = wizard.run_all()
        # home section needs no prompts and must succeed.
        home_result = next(r for r in results if r.name == "home")
        assert home_result.ok
        # Every other section that asks for input must fail with a clear msg.
        failing = [r for r in results if not r.ok]
        assert any(r.name == "model" for r in failing)


# ---------------------------------------------------------------------------
# skills_sync corner cases (beyond the wizard's happy path)
# ---------------------------------------------------------------------------


class TestSkillsSync:
    def test_user_edit_is_preserved_on_re_sync(self, home, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "x.md").write_text("# original\n", encoding="utf-8")
        skills_sync.sync(home, source_dir=src)
        # User edits their copy
        dst = home.skills_dir / "x.md"
        dst.write_text("# user-edited\n", encoding="utf-8")
        # Re-sync without force should preserve user edit
        result = skills_sync.sync(home, source_dir=src)
        assert "x.md" in result.preserved
        assert dst.read_text(encoding="utf-8") == "# user-edited\n"

    def test_force_overwrites_user_edit(self, home, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "x.md").write_text("# original\n", encoding="utf-8")
        skills_sync.sync(home, source_dir=src)
        dst = home.skills_dir / "x.md"
        dst.write_text("# user-edited\n", encoding="utf-8")
        result = skills_sync.sync(home, source_dir=src, force=True)
        assert "x.md" in result.copied
        assert dst.read_text(encoding="utf-8") == "# original\n"

    def test_bundled_change_re_copies(self, home, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "x.md").write_text("# v1\n", encoding="utf-8")
        skills_sync.sync(home, source_dir=src)
        # Bump bundled version; user has not touched their copy
        (src / "x.md").write_text("# v2\n", encoding="utf-8")
        os.utime(src / "x.md", (10**10, 10**10))  # force a different mtime
        result = skills_sync.sync(home, source_dir=src)
        assert "x.md" in result.copied
        assert (home.skills_dir / "x.md").read_text(encoding="utf-8") == "# v2\n"

    def test_missing_source_recorded_as_error(self, home, tmp_path):
        result = skills_sync.sync(home, source_dir=tmp_path / "doesnotexist")
        assert result.errors and "missing" in result.errors[0]

    def test_corrupt_manifest_tolerated(self, home, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "x.md").write_text("# x\n", encoding="utf-8")
        home.skills_manifest.parent.mkdir(parents=True, exist_ok=True)
        home.skills_manifest.write_text("not json", encoding="utf-8")
        result = skills_sync.sync(home, source_dir=src)
        assert result.errors == []
        assert "x.md" in result.copied


# ---------------------------------------------------------------------------
# CLI surface smoke
# ---------------------------------------------------------------------------


class TestCliSurface:
    def test_setup_help(self, capsys):
        from cortex.cli import main

        with pytest.raises(SystemExit) as exc:
            main(["setup", "--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "section" in out

    def test_skills_help(self, capsys):
        from cortex.cli import main

        with pytest.raises(SystemExit) as exc:
            main(["skills", "--help"])
        assert exc.value.code == 0

    def test_skills_list_runs_against_empty_home(self, capsys, home):
        from cortex.cli import main

        rc = main(["--home", str(home.root), "skills", "list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "bundled skills" in out

    def test_skills_sync_runs(self, capsys, home):
        from cortex.cli import main

        rc = main(["--home", str(home.root), "skills", "sync"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "copied:" in out
        assert (home.skills_dir / "summarise.md").exists()

    def test_setup_non_interactive_runs_home_only_cleanly(self, capsys, home):
        from cortex.cli import main

        rc = main(["--home", str(home.root), "setup", "home", "--non-interactive"])
        assert rc == 0, capsys.readouterr().err
        assert home.config_file.exists()
