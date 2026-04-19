"""Batch E coverage: WhatsApp CLI + runtime helpers + cortex pair handling."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from cortex import config as config_module
from cortex._runtime import (
    build_cortex_from_config,
    build_language_from_config,
    pair_pending_message,
)
from cortex.bus import Action, Reflex, Stimulus
from cortex.cli import main as cli_main
from cortex.cli_commands import whatsapp as wa_module
from cortex.cortex import Cortex
from cortex.home import ENV_HOME, ENV_PROFILE, CortexHome


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_HOME, str(tmp_path / "home"))
    monkeypatch.delenv(ENV_PROFILE, raising=False)
    for key in (
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_VERIFY_TOKEN",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def home(tmp_path) -> CortexHome:
    h = CortexHome.resolve(root=tmp_path / "home").bootstrap()
    config_module.seed(h)
    return h


# ---------------------------------------------------------------------------
# pair_pending_message + cortex pair-decision short-circuit
# ---------------------------------------------------------------------------


class TestPairResponse:
    def test_message_includes_name(self):
        msg = pair_pending_message("whatsapp:1234", name="atulya")
        assert "atulya" in msg.lower()
        assert "operator" in msg.lower()

    def test_cortex_returns_pair_message_without_calling_llm(self):
        cortex = Cortex(name="atulya-test", language=None)
        intent = asyncio.run(
            cortex.reflect(
                Stimulus(channel="whatsapp:99", sender="99", text="hi"),
                reflex=Reflex(decision="pair", reason="new"),
            )
        )
        assert intent.action.kind == "reply"
        assert "atulya-test" in intent.action.payload["text"].lower()
        assert "operator" in intent.action.payload["text"].lower()

    def test_cortex_returns_noop_for_deny(self):
        cortex = Cortex(language=None)
        intent = asyncio.run(
            cortex.reflect(
                Stimulus(channel="whatsapp:99", sender="99", text="hi"),
                reflex=Reflex(decision="deny", reason="banned"),
            )
        )
        assert intent.action.kind == "noop"


# ---------------------------------------------------------------------------
# Build helpers
# ---------------------------------------------------------------------------


class TestBuildHelpers:
    def test_build_language_lm_studio(self, home):
        cfg = config_module.load(home)
        lang = build_language_from_config(cfg)
        try:
            providers = lang.providers
            assert "lm-studio" in providers
        finally:
            asyncio.run(lang.aclose())

    def test_build_language_unknown_provider_falls_back(self, home, monkeypatch):
        cfg = config_module.load(home)
        # Mutate in-memory; we don't touch disk.
        cfg.model.provider = "custom-openai-compat"
        cfg.model.base_url = "http://example.test/v1"
        cfg.model.api_key_env = "TEST_KEY"
        monkeypatch.setenv("TEST_KEY", "abc")
        lang = build_language_from_config(cfg)
        try:
            assert "custom-openai-compat" in lang.providers
        finally:
            asyncio.run(lang.aclose())

    def test_build_cortex_uses_default_personality_when_no_persona_file(self, home):
        cfg = config_module.load(home)
        cortex = build_cortex_from_config(home, cfg, language=None)
        # Echo-mode without language; persona block still renders.
        intent = asyncio.run(cortex.reflect(Stimulus(channel="tui:local", sender="x", text="ping")))
        assert intent.action.kind == "reply"

    def test_build_cortex_loads_persona_file(self, home):
        home.persona_file.write_text(
            "---\nvoice: terse\ntraits: kind, careful\n---\nHello.\n",
            encoding="utf-8",
        )
        cfg = config_module.load(home)
        cortex = build_cortex_from_config(home, cfg, language=None)
        # Personality is reachable through the system prompt builder.
        thought = asyncio.run(cortex.hold(Stimulus(channel="tui:local", sender="x", text="ping")))
        assert "voice: terse" in thought.persona.lower() or "voice: terse" in thought.persona


# ---------------------------------------------------------------------------
# CLI: whatsapp doctor
# ---------------------------------------------------------------------------


class TestWhatsAppDoctor:
    def test_doctor_baileys_reports_missing_creds(self, home, capsys):
        rc = cli_main(["whatsapp", "--home", str(home.root), "doctor"])
        out = capsys.readouterr().out
        # `node` may or may not be installed in CI — the test asserts on the
        # bridge / session / creds rows that we control.
        assert "creds.json" in out
        assert "absent" in out
        # rc depends on whether node is on PATH; both 0 and 1 are valid.
        assert rc in (0, 1)

    def test_doctor_after_creds_seeded(self, home, capsys):
        # Pretend the bridge already paired.
        home.whatsapp_session_dir.mkdir(parents=True, exist_ok=True)
        (home.whatsapp_session_dir / "creds.json").write_text("{}", encoding="utf-8")
        rc = cli_main(["whatsapp", "--home", str(home.root), "doctor"])
        out = capsys.readouterr().out
        assert "present (paired)" in out

    def test_doctor_cloud_backend(self, home, capsys):
        cfg = config_module.load(home)
        cfg.whatsapp.backend = "cloud"
        config_module.save(home, cfg)
        rc = cli_main(["whatsapp", "--home", str(home.root), "doctor"])
        out = capsys.readouterr().out
        assert "WHATSAPP_PHONE_NUMBER_ID" in out
        assert rc == 1  # missing all three env vars


# ---------------------------------------------------------------------------
# CLI: whatsapp send (cloud backend, no Node required)
# ---------------------------------------------------------------------------


class TestWhatsAppSendCloud:
    def test_send_cloud_calls_backend(self, home, monkeypatch):
        cfg = config_module.load(home)
        cfg.whatsapp.backend = "cloud"
        config_module.save(home, cfg)
        monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "tok")
        monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "phone")

        sent: list[tuple[str, str]] = []

        class FakeCloud:
            def __init__(self, *, access_token, phone_number_id, api_version="v18.0"):
                assert access_token == "tok" and phone_number_id == "phone"

            async def send(self, jid, text):
                sent.append((jid, text))

        with patch("sensors.whatsapp.WhatsAppCloudBackend", FakeCloud):
            rc = cli_main(["whatsapp", "--home", str(home.root), "send", "111@s.whatsapp.net", "hello"])
        assert rc == 0
        assert sent == [("111@s.whatsapp.net", "hello")]

    def test_send_cloud_missing_env_returns_2(self, home, capsys):
        cfg = config_module.load(home)
        cfg.whatsapp.backend = "cloud"
        config_module.save(home, cfg)
        rc = cli_main(["whatsapp", "--home", str(home.root), "send", "111", "hi"])
        assert rc == 2
        assert "WHATSAPP_ACCESS_TOKEN" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# CLI: whatsapp send (baileys path) — mock the bridge so no Node required
# ---------------------------------------------------------------------------


class TestWhatsAppSendBaileys:
    def test_send_baileys_routes_through_backend(self, home, monkeypatch):
        sent: list[tuple[str, str]] = []
        started = []

        class FakeBackend:
            def __init__(self, *, bridge_command, bridge_url, cwd=None, env=None, stderr_sink=None):
                started.append((tuple(bridge_command), bridge_url, cwd))
                self._env = env
                self._stderr_sink = stderr_sink

            async def start(self, sink):
                self._sink = sink

            async def stop(self):
                self._sink = None

            async def send(self, jid, text):
                sent.append((jid, text))

        monkeypatch.setattr(wa_module, "_node_available", lambda: True)
        with patch("sensors.whatsapp.BaileysBackend", FakeBackend):
            rc = cli_main(
                [
                    "whatsapp",
                    "--home",
                    str(home.root),
                    "send",
                    "919999999999",
                    "hi",
                    "--bridge-cmd",
                    "node /tmp/fake-bridge.js",
                ]
            )
        assert rc == 0
        assert sent == [("919999999999", "hi")]
        assert started and started[0][0] == ("node", "/tmp/fake-bridge.js")

    def test_send_without_node_returns_2(self, home, monkeypatch, capsys):
        monkeypatch.setattr(wa_module, "_node_available", lambda: False)
        rc = cli_main(["whatsapp", "--home", str(home.root), "send", "111", "hi"])
        assert rc == 2
        assert "node" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# Bridge resolution
# ---------------------------------------------------------------------------


class TestBridgeResolution:
    def test_finds_bundled_bridge(self):
        # The bridge ships in the repo; resolution should find it from the
        # cortex package root regardless of CWD.
        path = wa_module._find_bridge_dir("scripts/whatsapp-bridge")
        assert path is not None
        assert (Path(path) / "whatsapp-bridge.js").exists()

    def test_resolves_explicit_command(self, home):
        cfg = config_module.load(home)
        ns = type("ns", (), {"bridge_cmd": "node /opt/bridge.js", "bridge_dir": None})()
        cmd, cwd = wa_module._resolve_bridge(ns, cfg)
        assert cmd == ["node", "/opt/bridge.js"]
        assert cwd is None

    def test_falls_back_to_default_when_dir_unknown(self, home, monkeypatch):
        cfg = config_module.load(home)
        monkeypatch.setattr(wa_module, "_find_bridge_dir", lambda _: None)
        ns = type("ns", (), {"bridge_cmd": None, "bridge_dir": None})()
        cmd, cwd = wa_module._resolve_bridge(ns, cfg)
        assert cmd == ["node", "whatsapp-bridge.js"]
        assert cwd is None


# ---------------------------------------------------------------------------
# CLI: whatsapp start (mocked end-to-end)
# ---------------------------------------------------------------------------


class TestWhatsAppStart:
    def test_start_wires_router_and_replies_via_egress(self, home, monkeypatch):
        # We swap BaileysBackend with a fake that produces ONE inbound stimulus
        # then disconnects. The reflex chain is set to default-allow so we don't
        # need DMPairing to approve our fake jid.
        delivered: list[tuple[str, str]] = []
        constructor_calls: list[dict] = []

        class FakeBackend:
            def __init__(self, *, bridge_command, bridge_url, cwd=None, env=None, stderr_sink=None):
                constructor_calls.append(
                    {"bridge_command": bridge_command, "bridge_url": bridge_url, "cwd": cwd, "env": env, "stderr_sink": stderr_sink}
                )
                self._sink = None
                self._fed = False
                self._env = env
                self._stderr_sink = stderr_sink

            async def start(self, sink):
                self._sink = sink
                # Push one inbound message right away.

                async def _push():
                    await asyncio.sleep(0)
                    if not self._fed and self._sink:
                        self._fed = True
                        from sensors.whatsapp import WhatsAppEar

                        await self._sink(
                            Stimulus(
                                channel=WhatsAppEar.channel_for_jid("111@s.whatsapp.net"),
                                sender="111@s.whatsapp.net",
                                text="ping",
                                raw={"from": "111@s.whatsapp.net", "body": "ping"},
                            )
                        )

                asyncio.create_task(_push())

            async def stop(self):
                self._sink = None

            async def send(self, jid, text):
                delivered.append((jid, text))

        monkeypatch.setattr(wa_module, "_node_available", lambda: True)
        # Make the loop exit shortly after the first message is processed.
        original_pump = wa_module._pump_stimuli

        async def short_pump(ear, router):
            # Process one stimulus then return to let the outer loop wind down.
            async for stim in ear.perceive():
                await router.route(stim)
                return

        monkeypatch.setattr(wa_module, "_pump_stimuli", short_pump)

        with patch("sensors.whatsapp.BaileysBackend", FakeBackend):
            rc = cli_main(
                [
                    "whatsapp",
                    "--home",
                    str(home.root),
                    "start",
                    "--default-allow",
                    "--echo",
                    "--bridge-cmd",
                    "node /tmp/fake.js",
                ]
            )
        assert rc == 0
        assert delivered, "expected at least one egress send"
        jid, text = delivered[0]
        assert jid == "111@s.whatsapp.net"
        # echo-mode reply prefix from Cortex._echo_intent
        assert "ping" in text
        # Regression guard: BaileysBackend MUST receive the env so the bridge
        # finds the user's paired session. If we forget to pass env again, the
        # bridge will silently boot with `./session` and pair into a different
        # account than the one the user QR-scanned.
        assert constructor_calls, "FakeBackend was never constructed"
        env = constructor_calls[0]["env"]
        assert env is not None
        assert env.get("CORTEX_WA_AUTH_DIR", "").endswith("whatsapp/session")
        assert constructor_calls[0]["stderr_sink"] is not None
