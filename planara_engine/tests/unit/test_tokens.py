"""JWT mint/verify round-trips and failure modes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from planara_engine.auth.tokens import mint_token, verify_token
from planara_engine.core.errors import AuthenticationFailed
from planara_engine.core.settings import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        jwt_secret="unit-test-secret-of-sufficient-length-for-hs256",
        jwt_ttl_minutes=60,
        _env_file=None,  # type: ignore[call-arg]
    )


def test_mint_then_verify_roundtrip(settings: Settings) -> None:
    token = mint_token(42, settings=settings)
    claims = verify_token(token, settings=settings)

    assert claims.user_id == 42
    assert claims.expires_at > claims.issued_at
    delta = claims.expires_at - claims.issued_at
    # Should be within a second of the configured TTL.
    assert abs(delta - timedelta(minutes=60)) < timedelta(seconds=1)


def test_verify_rejects_garbage(settings: Settings) -> None:
    with pytest.raises(AuthenticationFailed, match="invalid token"):
        verify_token("not.a.jwt", settings=settings)


def test_verify_rejects_wrong_signature(settings: Settings) -> None:
    token = mint_token(1, settings=settings)
    other_settings = Settings(
        jwt_secret="entirely-different-secret-also-long-enough",
        _env_file=None,  # type: ignore[call-arg]
    )
    with pytest.raises(AuthenticationFailed, match="invalid token"):
        verify_token(token, settings=other_settings)


def test_verify_rejects_expired_token(settings: Settings) -> None:
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    expired = jwt.encode(
        {"sub": "1", "iat": int(past.timestamp()), "exp": int(past.timestamp()) + 1},
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(AuthenticationFailed, match="token expired"):
        verify_token(expired, settings=settings)


def test_verify_rejects_missing_sub(settings: Settings) -> None:
    now = datetime.now(timezone.utc)
    bad = jwt.encode(
        {"iat": int(now.timestamp()), "exp": int((now + timedelta(hours=1)).timestamp())},
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(AuthenticationFailed, match="malformed token claims"):
        verify_token(bad, settings=settings)


def test_verify_rejects_non_integer_sub(settings: Settings) -> None:
    now = datetime.now(timezone.utc)
    bad = jwt.encode(
        {
            "sub": "not-an-int",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(AuthenticationFailed, match="malformed token claims"):
        verify_token(bad, settings=settings)
