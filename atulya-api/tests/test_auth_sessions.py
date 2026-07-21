import pytest

from atulya_api.api.auth import LoginRequest, SignupRequest
from atulya_api.auth import SESSION_PEPPER_ENV, generate_session, hash_password, verify_password, verify_secret
from atulya_api.auth_service import load_auth_extensions


def test_password_hash_round_trip():
    password_hash = hash_password("correct horse battery staple")

    assert password_hash != "correct horse battery staple"
    assert verify_password("correct horse battery staple", password_hash) is True
    assert verify_password("wrong horse battery staple", password_hash) is False


def test_generated_session_is_prefixed_and_verifiable():
    session = generate_session()

    assert session.raw_token.startswith("atulya_sess_")
    assert session.raw_token not in session.token_hash
    assert verify_secret(session.raw_token, session.token_hash, pepper_env=SESSION_PEPPER_ENV) is True


def test_login_request_uses_global_identity_without_org_selector():
    request = LoginRequest(email="owner@example.com", password="secret")

    assert request.model_dump() == {"email": "owner@example.com", "password": "secret"}
    assert request.email == "owner@example.com"


def test_signup_request_requires_strong_password():
    with pytest.raises(Exception, match="owner_password"):
        SignupRequest(
            org_slug="atulya",
            org_name="Atulya",
            owner_email="owner@example.com",
            owner_password="short",
        )


def test_production_database_auth_requires_secret_peppers(monkeypatch):
    monkeypatch.setenv("ATULYA_API_AUTH_MODE", "database")
    monkeypatch.setenv("ATULYA_ENVIRONMENT", "production")
    monkeypatch.setenv("ATULYA_AUTH_EMAIL_VERIFICATION", "disabled")
    monkeypatch.delenv("ATULYA_API_KEY_HASH_PEPPER", raising=False)
    monkeypatch.delenv("ATULYA_API_SESSION_HASH_PEPPER", raising=False)

    with pytest.raises(RuntimeError, match="secret peppers"):
        load_auth_extensions()


def test_production_auth_cannot_start_disabled(monkeypatch):
    monkeypatch.setenv("ATULYA_ENVIRONMENT", "production")
    monkeypatch.setenv("ATULYA_API_AUTH_MODE", "disabled")

    with pytest.raises(RuntimeError, match="requires ATULYA_API_AUTH_MODE=database"):
        load_auth_extensions()
