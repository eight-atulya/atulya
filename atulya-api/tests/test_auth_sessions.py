import pytest

from atulya_api.auth import generate_session, hash_password, verify_password, verify_secret
from atulya_api.api.auth import LoginRequest, SignupRequest


def test_password_hash_round_trip():
    password_hash = hash_password("correct horse battery staple")

    assert password_hash != "correct horse battery staple"
    assert verify_password("correct horse battery staple", password_hash) is True
    assert verify_password("wrong horse battery staple", password_hash) is False


def test_generated_session_is_prefixed_and_verifiable():
    session = generate_session()

    assert session.raw_token.startswith("atulya_sess_")
    assert session.raw_token not in session.token_hash
    assert verify_secret(session.raw_token, session.token_hash) is True


def test_login_request_org_is_optional():
    request = LoginRequest(email="owner@example.com", password="secret")

    assert request.org is None
    assert request.email == "owner@example.com"


def test_signup_request_requires_strong_password():
    with pytest.raises(Exception, match="owner_password"):
        SignupRequest(
            org_slug="atulya",
            org_name="Atulya",
            owner_email="owner@example.com",
            owner_password="short",
        )
