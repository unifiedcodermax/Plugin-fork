"""Settings: env loading, defaults, computed properties."""

from __future__ import annotations

import pytest

from planara_engine.core.settings import Environment, Settings, get_settings


def test_defaults_are_dev_safe() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.env is Environment.dev
    assert s.host == "127.0.0.1"
    assert s.port == 8765
    assert s.jwt_ttl_minutes == 480


def test_env_prefix_is_planara(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLANARA_PORT", "9100")
    monkeypatch.setenv("PLANARA_ENV", "prod")
    get_settings.cache_clear()

    s = Settings(_env_file=None)  # type: ignore[call-arg]

    assert s.port == 9100
    assert s.env is Environment.prod
    assert s.is_prod is True


def test_use_json_logs_follows_env_when_unset() -> None:
    dev = Settings(env=Environment.dev, _env_file=None)  # type: ignore[call-arg]
    prod = Settings(env=Environment.prod, _env_file=None)  # type: ignore[call-arg]
    assert dev.use_json_logs is False
    assert prod.use_json_logs is True


def test_use_json_logs_honors_explicit_override() -> None:
    s = Settings(env=Environment.prod, log_json=False, _env_file=None)  # type: ignore[call-arg]
    assert s.use_json_logs is False


def test_port_is_bounded() -> None:
    with pytest.raises(ValueError):
        Settings(port=70_000, _env_file=None)  # type: ignore[call-arg]


def test_jwt_secret_is_not_leaked_in_repr() -> None:
    s = Settings(jwt_secret="super-secret-value", _env_file=None)  # type: ignore[call-arg]
    assert "super-secret-value" not in repr(s)
    assert s.jwt_secret.get_secret_value() == "super-secret-value"
