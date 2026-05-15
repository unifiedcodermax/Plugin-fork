"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from planara_engine.api.app import create_app
from planara_engine.core.settings import Environment, Settings, get_settings


@pytest.fixture
def test_settings() -> Settings:
    """Settings instance pinned to the test environment.

    Independent of the user's .env so CI is deterministic. The JWT
    secret is a known value so auth tests can mint tokens manually.
    """

    return Settings(
        env=Environment.test,
        host="127.0.0.1",
        log_level="WARNING",
        log_json=False,
        jwt_secret="test-secret-not-for-prod",
        jwt_ttl_minutes=60,
        db_url="sqlite:///:memory:",
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """Bust the get_settings() lru_cache between tests.

    Prevents test ordering effects when a test mutates env vars or
    builds a non-default Settings.
    """

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def app(test_settings: Settings) -> FastAPI:
    """Build a fresh FastAPI app with test-pinned settings."""

    return create_app(test_settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Sync TestClient. Handles lifespan startup/shutdown."""

    with TestClient(app) as c:
        yield c
