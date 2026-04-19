"""Batch A coverage: CortexHome, Profile, env_loader, config, and the
production-hardening fixes that landed alongside (DMPairing atomic write,
Allowlist type-tightened default_decision)."""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

import pytest

from cortex import (
    CortexConfig,
    CortexHome,
    Profile,
    load_env_file,
    sanitize_value,
    write_env_file,
)
from cortex.config import (
    ConfigError,
    deep_merge,
    expand_env,
    load,
    load_raw,
    save,
    seed,
    template_dict,
    template_path,
    write_raw,
)
from cortex.home import (
    DEFAULT_PROFILE_NAME,
    ENV_HOME,
    ENV_PROFILE,
    default_home_root,
)

# ---------------------------------------------------------------------------
# CortexHome
# ---------------------------------------------------------------------------


class TestCortexHome:
    def test_default_home_root_uses_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_HOME, str(tmp_path / "alt"))
        assert default_home_root() == (tmp_path / "alt").resolve()

    def test_default_home_root_falls_back_to_homedir(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_HOME, raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        root = default_home_root()
        assert root == (tmp_path / ".atulya" / "cortex").resolve()

    def test_resolve_uses_default_profile_when_no_pointer(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_PROFILE, raising=False)
        home = CortexHome.resolve(root=tmp_path)
        assert home.profile_name == DEFAULT_PROFILE_NAME
        assert home.is_default_profile

    def test_resolve_honors_env_profile(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_PROFILE, "work")
        home = CortexHome.resolve(root=tmp_path)
        assert home.profile_name == "work"
        assert not home.is_default_profile

    def test_resolve_reads_current_profile_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_PROFILE, raising=False)
        (tmp_path / "current_profile").write_text("personal", encoding="utf-8")
        home = CortexHome.resolve(root=tmp_path)
        assert home.profile_name == "personal"

    def test_resolve_explicit_profile_wins_over_env_and_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_PROFILE, "work")
        (tmp_path / "current_profile").write_text("personal", encoding="utf-8")
        home = CortexHome.resolve(root=tmp_path, profile="explicit")
        assert home.profile_name == "explicit"

    def test_default_profile_uses_root_paths(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path, profile=DEFAULT_PROFILE_NAME)
        assert home.config_file == tmp_path / "config.toml"
        assert home.persona_file == tmp_path / "persona.md"
        assert home.pairing_store == tmp_path / "pairing" / "pairings.json"
        assert home.state_file == tmp_path / "state" / "state.json"

    def test_named_profile_shifts_to_overlay(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path, profile="work")
        prefix = tmp_path / "profiles" / "work"
        assert home.config_file == prefix / "config.toml"
        assert home.persona_file == prefix / "persona.md"
        assert home.pairing_store == prefix / "pairing" / "pairings.json"
        # caches & whatsapp session stay shared regardless of profile
        assert home.llm_cache_dir == tmp_path / "cache" / "llm"
        assert home.whatsapp_session_dir == tmp_path / "whatsapp" / "session"
        assert home.dashboard_lock == tmp_path / "dashboard.lock"

    def test_bootstrap_creates_all_dirs_idempotently(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path, profile="work")
        home.bootstrap()
        for d in (
            tmp_path,
            tmp_path / "profiles" / "work",
            tmp_path / "profiles" / "work" / "pairing",
            tmp_path / "profiles" / "work" / "state",
            tmp_path / "profiles" / "work" / "skills",
            tmp_path / "profiles" / "work" / "cron",
            tmp_path / "cache" / "llm",
            tmp_path / "cache" / "embedding",
            tmp_path / "whatsapp" / "session",
            tmp_path / "logs",
            tmp_path / "profiles",
        ):
            assert d.exists() and d.is_dir(), d
        # second call must not raise
        home.bootstrap()

    def test_resolve_log_path_anchors_relative(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        assert home.resolve_log_path("foo.log") == tmp_path / "logs" / "foo.log"
        absolute = tmp_path / "elsewhere" / "x.log"
        assert home.resolve_log_path(absolute) == absolute

    def test_invalid_profile_name_rejected(self, tmp_path):
        for bad in ("", "../escape", "side/load", ".hidden"):
            with pytest.raises(ValueError):
                CortexHome.resolve(root=tmp_path, profile=bad)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


class TestProfile:
    def test_list_returns_default_only_on_fresh_home(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        names = [p.name for p in Profile.list(home)]
        assert names == [DEFAULT_PROFILE_NAME]

    def test_create_new_profile(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        Profile.create(home, "work")
        assert (tmp_path / "profiles" / "work").is_dir()
        assert (tmp_path / "profiles" / "work" / "pairing").is_dir()
        names = [p.name for p in Profile.list(home)]
        assert names == [DEFAULT_PROFILE_NAME, "work"]

    def test_create_default_rejected(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        with pytest.raises(ValueError):
            Profile.create(home, DEFAULT_PROFILE_NAME)

    def test_create_duplicate_rejected(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        Profile.create(home, "work")
        with pytest.raises(ValueError):
            Profile.create(home, "work")

    def test_switch_persists_pointer(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        Profile.create(home, "work")
        Profile.switch(home, "work")
        assert (tmp_path / "current_profile").read_text(encoding="utf-8").strip() == "work"
        # re-resolve to pick up the active profile
        rehome = CortexHome.resolve(root=tmp_path)
        assert rehome.profile_name == "work"

    def test_switch_unknown_profile_rejected(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        with pytest.raises(ValueError):
            Profile.switch(home, "ghost")

    def test_delete_default_rejected(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        with pytest.raises(ValueError):
            Profile.delete(home, DEFAULT_PROFILE_NAME)

    def test_delete_active_rejected_without_flag(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        Profile.create(home, "work")
        Profile.switch(home, "work")
        active = CortexHome.resolve(root=tmp_path)
        with pytest.raises(ValueError):
            Profile.delete(active, "work")

    def test_delete_clears_active_pointer(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        Profile.create(home, "work")
        Profile.switch(home, "work")
        active = CortexHome.resolve(root=tmp_path)
        Profile.delete(active, "work", allow_active=True)
        assert not (tmp_path / "profiles" / "work").exists()
        assert not (tmp_path / "current_profile").exists()


# ---------------------------------------------------------------------------
# env_loader
# ---------------------------------------------------------------------------


class TestEnvLoader:
    def test_missing_file_is_noop(self, tmp_path):
        assert load_env_file(tmp_path / "no.env") == []

    def test_load_basic(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CORTEX_TEST_FOO", raising=False)
        f = tmp_path / ".env"
        f.write_text("CORTEX_TEST_FOO=bar\n", encoding="utf-8")
        loaded = load_env_file(f)
        assert loaded == ["CORTEX_TEST_FOO"]
        assert os.environ["CORTEX_TEST_FOO"] == "bar"

    def test_load_ignores_existing_unless_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CORTEX_TEST_FOO", "shell-value")
        f = tmp_path / ".env"
        f.write_text("CORTEX_TEST_FOO=file-value\n", encoding="utf-8")
        assert load_env_file(f) == []
        assert os.environ["CORTEX_TEST_FOO"] == "shell-value"
        assert load_env_file(f, override=True) == ["CORTEX_TEST_FOO"]
        assert os.environ["CORTEX_TEST_FOO"] == "file-value"

    def test_load_strips_bom_crlf_and_zero_width(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CORTEX_TEST_TOK", raising=False)
        f = tmp_path / ".env"
        f.write_bytes(b"\xef\xbb\xbfCORTEX_TEST_TOK=secret\xe2\x80\x8b\r\n")
        load_env_file(f)
        assert os.environ["CORTEX_TEST_TOK"] == "secret"

    def test_load_skips_comments_and_blank_lines(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CORTEX_TEST_KEY", raising=False)
        f = tmp_path / ".env"
        f.write_text(
            "\n# this is a comment\n\nCORTEX_TEST_KEY=value\nbroken-no-equals\n",
            encoding="utf-8",
        )
        loaded = load_env_file(f)
        assert loaded == ["CORTEX_TEST_KEY"]

    def test_load_handles_export_prefix_and_quoted_values(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CORTEX_TEST_QUOTED", raising=False)
        f = tmp_path / ".env"
        f.write_text('export CORTEX_TEST_QUOTED="hello world"\n', encoding="utf-8")
        load_env_file(f)
        assert os.environ["CORTEX_TEST_QUOTED"] == "hello world"

    def test_skip_keys_guard(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CORTEX_TEST_SKIP", raising=False)
        f = tmp_path / ".env"
        f.write_text("CORTEX_TEST_SKIP=should-not-load\n", encoding="utf-8")
        loaded = load_env_file(f, skip_keys={"CORTEX_TEST_SKIP"})
        assert loaded == []
        assert "CORTEX_TEST_SKIP" not in os.environ

    def test_unreadable_file_returns_empty(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("X=y\n", encoding="utf-8")

        def boom(*_a, **_kw):
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "read_text", boom)
        assert load_env_file(f) == []

    def test_sanitize_value_idempotent(self):
        for raw in ("", "plain", "  spaced  ", '"quoted"', "'single'"):
            sanitized = sanitize_value(raw)
            assert sanitize_value(sanitized) == sanitized

    def test_write_env_file_atomic_and_restricted_perms(self, tmp_path):
        target = tmp_path / ".env"
        write_env_file(target, {"A": "1", "B": "two words"})
        text = target.read_text(encoding="utf-8")
        assert "A=1" in text
        assert 'B="two words"' in text
        if os.name == "posix":
            mode = target.stat().st_mode & 0o777
            assert mode == 0o600


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


class TestConfig:
    def test_template_path_exists_and_loads(self):
        path = template_path()
        assert path.exists()
        data = template_dict()
        assert "general" in data and "model" in data and "memory" in data

    def test_default_config_validates_cleanly(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        seed(home)
        cfg = load(home)
        assert isinstance(cfg, CortexConfig)
        assert cfg.general.name == "atulya-cortex"
        assert cfg.model.provider == "lm_studio"

    def test_seed_creates_then_idempotent(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        assert seed(home) is True
        assert seed(home) is False  # already exists
        assert seed(home, force=True) is True  # force overwrite

    def test_load_without_user_file_returns_template_defaults(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        cfg = load(home)
        assert cfg.dashboard.port == 9120

    def test_user_overrides_merge_deeply(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        home.config_file.parent.mkdir(parents=True, exist_ok=True)
        home.config_file.write_text(
            '[general]\nname = "custom"\n[breathing.per_channel]\ntui = 999\n',
            encoding="utf-8",
        )
        cfg = load(home)
        assert cfg.general.name == "custom"
        # values from the template still come through
        assert cfg.general.peer == "local"
        assert cfg.breathing.per_channel["tui"] == 999
        # other per_channel entries from the template survive the deep merge
        assert cfg.breathing.per_channel["telegram"] == 30

    def test_unknown_key_rejected(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        home.config_file.write_text(
            '[general]\nname = "ok"\nmysteryflag = true\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigError) as exc_info:
            load(home)
        assert "mysteryflag" in str(exc_info.value)

    def test_invalid_log_level_rejected(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        home.config_file.write_text(
            '[general]\nlog_level = "WHATEVER"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigError):
            load(home)

    def test_invalid_recall_kind_rejected(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        home.config_file.write_text(
            '[memory]\nrecall_kinds = ["episodic", "telepathic"]\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigError):
            load(home)

    def test_save_roundtrip(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        cfg = CortexConfig.model_validate(template_dict())
        cfg.general.name = "renamed"
        cfg.dashboard.port = 9999
        save(home, cfg)
        again = load(home)
        assert again.general.name == "renamed"
        assert again.dashboard.port == 9999

    def test_corrupt_user_toml_raises_configerror(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        home.config_file.write_text("not = [valid", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_raw(home)

    def test_env_expansion(self, monkeypatch):
        monkeypatch.setenv("CORTEX_TEST_PORT", "1234")
        merged = expand_env({"model": {"base_url": "http://host:${CORTEX_TEST_PORT}/v1"}})
        assert merged["model"]["base_url"] == "http://host:1234/v1"

    def test_env_expansion_leaves_unknown_literal(self, monkeypatch):
        monkeypatch.delenv("DEFINITELY_UNSET", raising=False)
        merged = expand_env({"x": "${DEFINITELY_UNSET}"})
        assert merged["x"] == "${DEFINITELY_UNSET}"

    def test_deep_merge_replaces_lists_wholesale(self):
        merged = deep_merge({"a": [1, 2, 3], "b": 1}, {"a": [9]})
        assert merged == {"a": [9], "b": 1}

    def test_write_raw_validates_before_disk(self, tmp_path):
        home = CortexHome.resolve(root=tmp_path)
        home.bootstrap()
        seed(home)
        good = template_dict()
        good["general"]["name"] = "via-write-raw"
        write_raw(home, good)
        assert load(home).general.name == "via-write-raw"

        bad = template_dict()
        bad["general"]["log_level"] = "BOGUS"
        with pytest.raises(Exception):
            write_raw(home, bad)


# ---------------------------------------------------------------------------
# Production-hardening regressions for code touched in this batch
# ---------------------------------------------------------------------------


class TestPairingStoreHardening:
    def test_save_is_atomic(self, tmp_path, monkeypatch):
        from brainstem.reflexes import DMPairing

        store = DMPairing(tmp_path / "pairing" / "pairings.json")
        store.approve("telegram:42")
        # Inject failure midway through replace; the partial tmp file must
        # not be left behind and the original file must still be readable.
        original_replace = os.replace

        def boom(src, dst):  # noqa: ANN001
            raise OSError("simulated crash mid-write")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            store.approve("telegram:99")
        # Only the original entry survived; no temp leftovers.
        leftovers = list((tmp_path / "pairing").glob(".pairings-*.json.tmp"))
        assert leftovers == []
        monkeypatch.setattr(os, "replace", original_replace)
        # Re-open from disk: should still parse and only contain the first approval.
        reopened = DMPairing(tmp_path / "pairing" / "pairings.json")
        assert reopened.status("telegram:42") == "approved"
        assert reopened.status("telegram:99") is None

    def test_load_tolerates_garbage_file(self, tmp_path):
        from brainstem.reflexes import DMPairing

        path = tmp_path / "pairing" / "pairings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ this is not json", encoding="utf-8")
        store = DMPairing(path)
        assert store.status("anything") is None
        store.approve("tui:local")
        assert json.loads(path.read_text(encoding="utf-8"))["tui:local"]["status"] == "approved"

    def test_load_tolerates_non_dict_root(self, tmp_path):
        from brainstem.reflexes import DMPairing

        path = tmp_path / "pairing" / "pairings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[1, 2, 3]", encoding="utf-8")
        store = DMPairing(path)
        assert store.status("x") is None

    def test_list_and_pending_helpers(self, tmp_path):
        from brainstem.reflexes import DMPairing

        store = DMPairing(tmp_path / "p" / "pairings.json")
        store.approve("telegram:1")
        store.reject("whatsapp:9")
        # simulate a pending entry by going through evaluate
        import asyncio

        from cortex.bus import Stimulus

        asyncio.run(store.evaluate(Stimulus(channel="telegram:7", sender="7")))
        listed = store.list()
        assert {entry["channel"] for entry in listed} == {
            "telegram:1",
            "whatsapp:9",
            "telegram:7",
        }
        assert store.pending() == ["telegram:7"]


class TestAllowlistHardening:
    def test_invalid_default_decision_rejected(self):
        from brainstem.reflexes import Allowlist

        with pytest.raises(ValueError):
            Allowlist(default_decision="explode")  # type: ignore[arg-type]

    def test_each_valid_default_constructs(self):
        from brainstem.reflexes import Allowlist

        for decision in ("allow", "deny", "pair", "sandbox"):
            Allowlist(default_decision=decision)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Sanity check: the bundled template parses with the strict Pydantic schema.
# ---------------------------------------------------------------------------


def test_bundled_template_parses_against_schema():
    text = template_path().read_text(encoding="utf-8")
    raw = tomllib.loads(text)
    CortexConfig.model_validate(raw)
