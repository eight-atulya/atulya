from __future__ import annotations

import json
import types

from cortex import config as config_module
from cortex.cli import main as cli_main
from cortex.home import ENV_HOME, ENV_PROFILE, CortexHome


class _Model:
    def __init__(self, model_id: str, name: str, content: str) -> None:
        self.id = model_id
        self.name = name
        self.content = content


class _ListResult:
    def __init__(self, items):
        self.items = items


class _FakeMentalModels:
    def __init__(self, store):
        self._store = store
        self._counter = 0

    def list(self, bank_id: str):
        return _ListResult(list(self._store.setdefault(bank_id, [])))

    def create(self, bank_id: str, name: str, content: str, tags=None):
        self._counter += 1
        m = _Model(f"m-{self._counter}", name, content)
        self._store.setdefault(bank_id, []).append(m)
        return m

    def update(self, bank_id: str, mental_model_id: str, name=None, content=None, tags=None):
        for m in self._store.setdefault(bank_id, []):
            if m.id == mental_model_id:
                if name is not None:
                    m.name = name
                if content is not None:
                    m.content = content
                return m
        raise KeyError(mental_model_id)


class _FakeBanks:
    def create(self, bank_id: str, name=None, mission=None, disposition=None):
        return {"id": bank_id}


class _FakeEmbedded:
    _store = {}

    def __init__(self, profile="default", **kwargs):
        self.profile = profile
        self.mental_models = _FakeMentalModels(_FakeEmbedded._store)
        self.banks = _FakeBanks()

    def close(self, stop_daemon: bool = False):
        return None


def test_peer_bank_set_get_and_resolve(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(ENV_HOME, str(tmp_path / "home"))
    monkeypatch.delenv(ENV_PROFILE, raising=False)
    home = CortexHome.resolve(root=tmp_path / "home").bootstrap()
    config_module.seed(home)

    fake_mod = types.SimpleNamespace(AtulyaEmbedded=_FakeEmbedded, AtulyaClient=_FakeEmbedded)
    monkeypatch.setitem(__import__("sys").modules, "atulya", fake_mod)

    rc = cli_main(
        [
            "peer-bank",
            "--home",
            str(home.root),
            "set",
            "whatsapp:255@lid",
            "--name",
            "peer_profile",
            "--content",
            "User prefers short bullet answers",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "created peer_profile" in out
    mirror = home.whatsapp_mental_models_dir / "255.json"
    assert mirror.exists()
    first = json.loads(mirror.read_text(encoding="utf-8"))
    assert first["peer_key"] == "255@lid"
    assert first["bank_id"].startswith("cortex_default_")
    assert first["mental_models"][0]["name"] == "peer_profile"
    assert "top_entities" in first
    assert "top_entities_hash" in first
    assert any(d.get("change") == "created" for d in first["delta"])

    rc = cli_main(
        [
            "peer-bank",
            "--home",
            str(home.root),
            "set",
            "whatsapp:255@lid",
            "--name",
            "peer_profile",
            "--content",
            "User now prefers long-form explanations",
        ]
    )
    assert rc == 0
    second = json.loads(mirror.read_text(encoding="utf-8"))
    assert second["mental_models"][0]["content"] == "User now prefers long-form explanations"
    assert any(d.get("change") == "updated" for d in second["delta"])

    rc = cli_main(
        [
            "peer-bank",
            "--home",
            str(home.root),
            "get",
            "whatsapp:255@lid",
            "--name",
            "peer_profile",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "peer_profile" in out
    assert "long-form explanations" in out

    rc = cli_main(["peer-bank", "--home", str(home.root), "resolve", "whatsapp:255@lid"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("cortex_default_")

