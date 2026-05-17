"""Integration tests for /auth/login and /auth/me through the live app."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from planara_engine.api.app import create_app
from planara_engine.auth.service import register_user
from planara_engine.core.settings import Environment, Settings
from planara_engine.persistence.database import get_engine, init_db


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    """File-backed SQLite per test.

    ``:memory:`` would not work here because each new connection
    sees its own empty DB; the test seeds via one Session and the
    request handler queries via a different Session — they would
    not see each other.
    """

    return f"sqlite:///{tmp_path / 'planara-test.db'}"


@pytest.fixture
def settings_with_db(monkeypatch: pytest.MonkeyPatch, db_url: str) -> Settings:
    monkeypatch.setenv("PLANARA_DB_URL", db_url)
    monkeypatch.setenv(
        "PLANARA_JWT_SECRET", "integration-test-secret-of-sufficient-length"
    )
    monkeypatch.setenv("PLANARA_JWT_TTL_MINUTES", "60")
    get_engine.cache_clear()
    return Settings(
        env=Environment.test,
        db_url=db_url,
        jwt_secret="integration-test-secret-of-sufficient-length",
        jwt_ttl_minutes=60,
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def app_client(settings_with_db: Settings) -> Iterator[TestClient]:
    app = create_app(settings_with_db)
    with TestClient(app) as c:
        yield c
    get_engine().dispose()
    get_engine.cache_clear()


@pytest.fixture
def seeded_user(app_client: TestClient) -> tuple[str, str]:
    """Seed a known user directly so login tests have something to call against."""

    username, password = "tester", "hunter2pass"
    init_db()  # idempotent — app lifespan already called it, but be defensive
    with Session(get_engine()) as s:
        register_user(s, username=username, password=password)
        s.commit()
    return username, password


def test_login_returns_token(app_client: TestClient, seeded_user: tuple[str, str]) -> None:
    username, password = seeded_user
    resp = app_client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200

    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in_minutes"] == 60
    assert len(body["token"]) > 32


def test_login_wrong_password_is_401(app_client: TestClient, seeded_user: tuple[str, str]) -> None:
    username, _ = seeded_user
    resp = app_client.post("/auth/login", json={"username": username, "password": "wrong"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "authentication_failed"
    assert body["error"]["message"] == "invalid credentials"


def test_login_unknown_user_is_401_with_same_message(
    app_client: TestClient, seeded_user: tuple[str, str]
) -> None:
    resp = app_client.post("/auth/login", json={"username": "ghost", "password": "anything"})
    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "invalid credentials"


def test_login_validates_empty_inputs(app_client: TestClient) -> None:
    # Pydantic catches min_length violations before the handler runs;
    # FastAPI returns its own 422 envelope, not ours. That's fine —
    # the request never reaches business logic.
    resp = app_client.post("/auth/login", json={"username": "", "password": ""})
    assert resp.status_code == 422


def test_me_requires_bearer_token(app_client: TestClient) -> None:
    resp = app_client.get("/auth/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "authentication_failed"


def test_me_rejects_garbage_token(app_client: TestClient) -> None:
    resp = app_client.get("/auth/me", headers={"Authorization": "Bearer not.a.real.jwt"})
    assert resp.status_code == 401


def test_me_rejects_non_bearer_scheme(app_client: TestClient) -> None:
    # HTTPBearer with auto_error=False returns None for non-bearer
    # schemes, and our get_current_user surfaces that as
    # AuthenticationFailed -> 401 through the PlanaraError envelope.
    resp = app_client.get("/auth/me", headers={"Authorization": "Basic Zm9vOmJhcg=="})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "authentication_failed"


def test_login_then_me_roundtrip(app_client: TestClient, seeded_user: tuple[str, str]) -> None:
    username, password = seeded_user
    login = app_client.post(
        "/auth/login", json={"username": username, "password": password}
    ).json()

    me = app_client.get("/auth/me", headers={"Authorization": f"Bearer {login['token']}"})
    assert me.status_code == 200
    body = me.json()
    assert body["username"] == username
    assert body["is_active"] is True
    assert "password_hash" not in body  # critical: never leak
