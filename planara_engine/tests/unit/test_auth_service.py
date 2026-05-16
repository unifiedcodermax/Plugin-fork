"""Auth service: register + authenticate + issue_token."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlmodel import Session

from planara_engine.auth.service import authenticate, issue_token, register_user
from planara_engine.auth.tokens import verify_token
from planara_engine.core.errors import AuthenticationFailed, ValidationFailed
from planara_engine.core.settings import Settings
from planara_engine.persistence.database import get_engine, init_db


@pytest.fixture
def settings() -> Settings:
    return Settings(
        jwt_secret="auth-service-test-secret-long-enough-for-hs256",
        jwt_ttl_minutes=60,
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def session(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,  # noqa: ARG001 — needed so jwt verify uses same secret
) -> Iterator[Session]:
    monkeypatch.setenv("PLANARA_DB_URL", "sqlite:///:memory:")
    monkeypatch.setenv("PLANARA_JWT_SECRET", "auth-service-test-secret-long-enough-for-hs256")
    get_engine.cache_clear()
    init_db()
    engine = get_engine()
    with Session(engine) as s:
        yield s
    engine.dispose()
    get_engine.cache_clear()


def test_register_then_authenticate(session: Session) -> None:
    register_user(session, username="alice", password="hunter2pass")
    session.commit()

    user = authenticate(session, username="alice", password="hunter2pass")
    assert user.username == "alice"


def test_register_rejects_empty_username(session: Session) -> None:
    with pytest.raises(ValidationFailed):
        register_user(session, username="   ", password="hunter2pass")


def test_register_rejects_duplicate_username(session: Session) -> None:
    register_user(session, username="bob", password="hunter2pass")
    session.commit()
    with pytest.raises(ValidationFailed, match="already exists"):
        register_user(session, username="bob", password="other")


def test_authenticate_unknown_user_message_matches_wrong_password(session: Session) -> None:
    register_user(session, username="carol", password="hunter2pass")
    session.commit()

    with pytest.raises(AuthenticationFailed) as e_unknown:
        authenticate(session, username="ghost", password="anything")
    with pytest.raises(AuthenticationFailed) as e_wrong:
        authenticate(session, username="carol", password="wrong")

    # Same message in both branches — must not leak which one failed.
    assert e_unknown.value.message == e_wrong.value.message == "invalid credentials"


def test_authenticate_disabled_user(session: Session) -> None:
    user = register_user(session, username="dave", password="hunter2pass")
    user.is_active = False
    session.add(user)
    session.commit()

    with pytest.raises(AuthenticationFailed, match="disabled"):
        authenticate(session, username="dave", password="hunter2pass")


def test_issue_token_returns_verifiable_jwt(session: Session) -> None:
    user = register_user(session, username="eve", password="hunter2pass")
    session.commit()

    token = issue_token(user)
    claims = verify_token(token)
    assert claims.user_id == user.id
