from atulya_bridge import cli


def test_init_defaults_to_preview(monkeypatch, capsys):
    monkeypatch.delenv("ATULYA_API_LLM_API_KEY", raising=False)
    monkeypatch.delenv("ATULYA_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    exit_code = cli.main(["init"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Preview only." in output


def test_store_requires_credentials(monkeypatch, capsys):
    monkeypatch.delenv("ATULYA_API_LLM_API_KEY", raising=False)
    monkeypatch.delenv("ATULYA_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    exit_code = cli.main(["init", "--store"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "LLM credentials are not configured" in output
