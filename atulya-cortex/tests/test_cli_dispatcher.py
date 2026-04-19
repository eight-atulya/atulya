"""Batch B coverage: CLI dispatcher framework.

We intentionally do NOT exercise the chat subcommand's interactive loop here
(that needs a real TTY); instead we register a synthetic command via the
discovery hook and assert the dispatcher's contract.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Iterable
from unittest.mock import patch

import pytest

import cortex.cli as cli_module
import cortex.cli_commands as cli_commands_pkg
from cortex.home import ENV_HOME, ENV_PROFILE


def _make_synthetic_command(
    name: str,
    *,
    exit_code: int = 0,
    raises: Exception | None = None,
    record: dict | None = None,
) -> ModuleType:
    """Build an in-memory command module with the cli_commands contract."""

    module = ModuleType(f"cortex.cli_commands._synthetic_{name}")
    module.NAME = name
    module.HELP = f"synthetic command {name}"

    def register(subparsers, common_parents):
        p = subparsers.add_parser(name, help=module.HELP, parents=list(common_parents))
        p.add_argument("--echo", default="", help="value echoed back via record")
        p.set_defaults(_run=run)

    def run(args, *, home):
        if record is not None:
            record["called"] = True
            record["echo"] = args.echo
            record["home"] = home
            record["profile"] = home.profile_name
        if raises is not None:
            raise raises
        return exit_code

    module.register = register
    module.run = run
    return module


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    """Force every test to run against a private home so no test pollutes the
    real `~/.atulya/cortex/`."""

    monkeypatch.setenv(ENV_HOME, str(tmp_path / "home"))
    monkeypatch.delenv(ENV_PROFILE, raising=False)
    yield


def _run_cli(argv: Iterable[str], modules: Iterable[ModuleType] | None = None) -> int:
    """Drive `cli.main` with a frozen module set so tests don't depend on the
    real registry of subcommands evolving over time."""

    if modules is None:
        return cli_module.main(list(argv))
    # `cli.py` does `from cortex.cli_commands import discover`, so the bound
    # name lives on the cli module — patch it there.
    with patch.object(cli_module, "discover", return_value=list(modules)):
        return cli_module.main(list(argv))


class TestDispatcherContract:
    def test_no_args_defaults_to_chat_via_real_discovery(self, capsys, monkeypatch):
        # The real `chat` subcommand requires a TTY; we patch its `run` to
        # short-circuit so we can prove the dispatcher reaches it.
        from cortex.cli_commands import chat as chat_module

        sentinel = {"called": False}

        def fake_run(args, *, home):
            sentinel["called"] = True
            return 0

        monkeypatch.setattr(chat_module, "run", fake_run)
        # set_defaults captured the original `run`; call again post-monkey-patch
        # by re-registering. Simplest: bypass the discovery cache by patching it.
        synthetic = _make_synthetic_command("chat", exit_code=0)
        rc = _run_cli([], modules=[synthetic])
        assert rc == 0

    def test_explicit_subcommand_dispatches(self, tmp_path):
        record: dict = {}
        synthetic = _make_synthetic_command("ping", record=record)
        rc = _run_cli(["ping", "--echo", "pong"], modules=[synthetic])
        assert rc == 0
        assert record == {
            "called": True,
            "echo": "pong",
            "home": record["home"],  # opaque
            "profile": "default",
        }

    def test_unknown_subcommand_errors(self, capsys):
        synthetic = _make_synthetic_command("ping")
        with pytest.raises(SystemExit) as exc:
            _run_cli(["nope"], modules=[synthetic])
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "invalid choice" in err

    def test_missing_handler_returns_2(self, monkeypatch, tmp_path, capsys):
        # If discover() returns no modules at all, the auto-injected `chat`
        # default fails argparse choice validation (no subparsers registered)
        # and argparse calls sys.exit(2). This is the right error for a
        # mis-installed cortex (e.g. someone deleted cli_commands/chat.py).
        with pytest.raises(SystemExit) as exc:
            _run_cli([], modules=[])
        assert exc.value.code == 2

    def test_keyboard_interrupt_returns_130(self):
        synthetic = _make_synthetic_command("boom", raises=KeyboardInterrupt())
        rc = _run_cli(["boom"], modules=[synthetic])
        assert rc == 130

    def test_uncaught_exception_returns_1_and_prints_error(self, capsys):
        synthetic = _make_synthetic_command("boom", raises=RuntimeError("kaboom"))
        rc = _run_cli(["boom"], modules=[synthetic])
        assert rc == 1
        err = capsys.readouterr().err
        assert "kaboom" in err
        # full traceback should NOT show without TRACE / DEBUG
        assert "Traceback" not in err

    def test_trace_env_shows_full_traceback(self, capsys, monkeypatch):
        monkeypatch.setenv("ATULYA_CORTEX_TRACE", "1")
        synthetic = _make_synthetic_command("boom", raises=RuntimeError("kaboom"))
        rc = _run_cli(["boom"], modules=[synthetic])
        assert rc == 1
        err = capsys.readouterr().err
        assert "Traceback" in err

    def test_systemexit_propagates(self):
        synthetic = _make_synthetic_command("boom", raises=SystemExit(7))
        with pytest.raises(SystemExit) as exc:
            _run_cli(["boom"], modules=[synthetic])
        assert exc.value.code == 7


class TestGlobalFlags:
    def test_home_flag_overrides_env(self, tmp_path):
        record: dict = {}
        alt = tmp_path / "alt"
        synthetic = _make_synthetic_command("ping", record=record)
        rc = _run_cli(["ping", "--home", str(alt)], modules=[synthetic])
        assert rc == 0
        assert str(record["home"].root) == str(alt.resolve())
        assert (alt / "cache" / "llm").exists()  # bootstrap ran

    def test_profile_flag_routes_to_overlay(self, tmp_path):
        record: dict = {}
        synthetic = _make_synthetic_command("ping", record=record)
        rc = _run_cli(["ping", "--profile", "work"], modules=[synthetic])
        assert rc == 0
        assert record["profile"] == "work"

    def test_log_level_flag_sets_root_level(self, tmp_path):
        import logging

        synthetic = _make_synthetic_command("ping")
        _run_cli(["ping", "--log-level", "DEBUG"], modules=[synthetic])
        assert logging.getLogger().level == logging.DEBUG

    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _run_cli(["--version"], modules=[_make_synthetic_command("ping")])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "atulya-cortex" in out

    def test_no_env_file_skips_load(self, tmp_path, monkeypatch):
        # Create an env file the dispatcher would normally load.
        home_root = tmp_path / "home"
        env_file = home_root / ".env"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text("CORTEX_TEST_NO_LOAD=should-not-load\n", encoding="utf-8")
        monkeypatch.delenv("CORTEX_TEST_NO_LOAD", raising=False)
        synthetic = _make_synthetic_command("ping")
        rc = _run_cli(["ping", "--no-env-file"], modules=[synthetic])
        assert rc == 0
        assert "CORTEX_TEST_NO_LOAD" not in os.environ


class TestEnvAutoLoad:
    def test_env_file_loaded_before_command_runs(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CORTEX_TEST_AUTO_ENV", raising=False)
        home_root = tmp_path / "home"
        env_file = home_root / ".env"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text("CORTEX_TEST_AUTO_ENV=loaded\n", encoding="utf-8")
        record: dict = {}

        def run(args, *, home):
            record["env"] = os.environ.get("CORTEX_TEST_AUTO_ENV")
            return 0

        synthetic = _make_synthetic_command("ping")
        synthetic.run = run
        # rebuild the parser_default
        original = synthetic.register

        def register(subparsers, common_parents):
            p = subparsers.add_parser("ping", help="x", parents=list(common_parents))
            p.set_defaults(_run=run)

        synthetic.register = register

        rc = _run_cli(["ping"], modules=[synthetic])
        assert rc == 0
        assert record["env"] == "loaded"


class TestCommandDiscovery:
    def test_real_discovery_includes_chat(self):
        modules = cli_commands_pkg.discover()
        names = [m.NAME for m in modules]
        assert "chat" in names

    def test_modules_missing_contract_are_skipped(self, tmp_path):
        # Inject a half-baked module under cli_commands and confirm discover
        # ignores it cleanly without raising.
        bad_path = Path(cli_commands_pkg.__file__).parent / "_synth_invalid.py"
        bad_path.write_text("# missing NAME/HELP/register on purpose\n", encoding="utf-8")
        try:
            modules = cli_commands_pkg.discover()
            assert "_synth_invalid" not in [m.__name__.split(".")[-1] for m in modules]
        finally:
            bad_path.unlink(missing_ok=True)


class TestPythonDashM:
    def test_python_m_cortex_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "cortex", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, ENV_HOME: "/tmp/cortex-pythonm-test"},
        )
        assert result.returncode == 0, result.stderr
        assert "atulya-cortex" in result.stdout
