from __future__ import annotations

from typer.testing import CliRunner

from atulya_api.admin.cli import app


def _env_lines(output: str) -> dict[str, str]:
    lines: dict[str, str] = {}
    for line in output.splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        lines[key] = value
    return lines


def test_generate_auth_env_outputs_canonical_database_auth_settings():
    result = CliRunner().invoke(app, ["generate-auth-env"])

    assert result.exit_code == 0
    values = _env_lines(result.output)
    assert values["ATULYA_API_AUTH_MODE"] == "database"
    assert values["ATULYA_API_ADMIN_ENABLED"] == "true"
    assert values["ATULYA_API_SUPERUSER_KEY"].startswith("atulya_admin_")
    assert "ATULYA_CP_ADMIN_API_KEY" not in values
    assert values["ATULYA_API_KEY_HASH_PEPPER"].startswith("atulya_key_pepper_")
    assert values["ATULYA_API_SESSION_HASH_PEPPER"].startswith("atulya_session_pepper_")
    assert values["ATULYA_API_KEY_HASH_PEPPER"] != values["ATULYA_API_SUPERUSER_KEY"]
    assert values["ATULYA_API_SESSION_HASH_PEPPER"] != values["ATULYA_API_KEY_HASH_PEPPER"]
    assert values["ATULYA_SIGNUP_MODE"] == "public"
    assert values["ATULYA_AUTH_EMAIL_VERIFICATION"] == "required"
    assert values["ATULYA_CP_DATAPLANE_API_URL"] == "http://localhost:8888"


def test_reset_refuses_to_run_in_production(monkeypatch):
    monkeypatch.setenv("ATULYA_ENVIRONMENT", "production")

    result = CliRunner().invoke(
        app,
        ["reset-development-auth-and-banks", "--confirm", "RESET-ATULYA-AUTH-AND-BANKS"],
    )

    assert result.exit_code == 1
    assert "Refusing to reset" in result.output


def test_generate_auth_env_rejects_unknown_signup_mode():
    result = CliRunner().invoke(app, ["generate-auth-env", "--signup-mode", "open"])

    assert result.exit_code == 1
    assert "--signup-mode must be disabled, bootstrap, or public" in result.output
