"""End-to-end /validate flow through the live FastAPI app.

Uses the real Bangalore rule pack (no test pack substitution) so
a regression in the shipped pack or the FSI evaluator is caught
by this suite, not just unit tests.
"""

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
from planara_engine.rules.loader import get_pack


@pytest.fixture
def settings_with_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    db_url = f"sqlite:///{tmp_path / 'planara.db'}"
    monkeypatch.setenv("PLANARA_DB_URL", db_url)
    monkeypatch.setenv(
        "PLANARA_JWT_SECRET", "validate-test-secret-of-sufficient-length"
    )
    monkeypatch.setenv("PLANARA_JWT_TTL_MINUTES", "60")
    get_engine.cache_clear()
    get_pack.cache_clear()
    return Settings(
        env=Environment.test,
        db_url=db_url,
        jwt_secret="validate-test-secret-of-sufficient-length",
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
    get_pack.cache_clear()


@pytest.fixture
def authed_headers(app_client: TestClient) -> dict[str, str]:
    """Seed a user and return Authorization headers ready to attach."""

    init_db()
    with Session(get_engine()) as s:
        register_user(s, username="vtester", password="hunter2pass")
        s.commit()

    resp = app_client.post(
        "/auth/login", json={"username": "vtester", "password": "hunter2pass"}
    )
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def _snapshot(
    classification: str = "CBD",
    zone: str = "Residential",
    plot_size: float = 20.0,
    floors: list[tuple[int, float, float, bool]] | None = None,
) -> dict:
    """floors = [(level, square_size, height, is_habitable)]"""

    floors = floors if floors is not None else [(0, 10.0, 3.0, True)]
    sq = lambda s: [[0, 0], [s, 0], [s, s], [0, s]]  # noqa: E731

    return {
        "project": {
            "city": "Bangalore",
            "classification": classification,
            "zone": zone,
        },
        "plot": {"polygon": {"exterior": sq(plot_size)}},
        "building": {
            "floors": [
                {
                    "level": lvl,
                    "polygon": {"exterior": sq(size)},
                    "height_m": h,
                    "is_habitable": hab,
                }
                for lvl, size, h, hab in floors
            ]
        },
    }


def test_validate_requires_auth(app_client: TestClient) -> None:
    resp = app_client.post("/validate", json=_snapshot())
    assert resp.status_code == 401


def test_validate_passes_for_compliant_building(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    # 100m^2 on 400m^2 plot -> FSI 0.25, well under CBD/Res 2.5.
    resp = app_client.post("/validate", json=_snapshot(), headers=authed_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert body["ok"] is True
    assert body["violations"] == []
    assert body["metrics"]["fsi"] == 0.25
    assert body["metrics"]["max_fsi"] == 2.5
    assert body["metrics"]["rule_pack_version"] == "0.1.0"


def test_validate_records_fsi_violation(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    # CBD/Residential, FSI cap 2.5. Build 4 x 15x15 floors = 900 / 400 = 2.25.
    # Still under. Push to 6 floors of 15x15 -> 1350/400 = 3.375 -> over.
    floors = [(lvl, 15.0, 3.0, True) for lvl in range(6)]
    resp = app_client.post(
        "/validate", json=_snapshot(floors=floors), headers=authed_headers
    )
    assert resp.status_code == 200

    body = resp.json()
    assert body["ok"] is False
    assert len(body["violations"]) == 1
    v = body["violations"][0]
    assert v["rule_id"] == "blr.fsi.cbd.residential"
    assert v["severity"] == "error"
    assert "exceeds" in v["message"]
    assert v["computed"]["fsi"] == 3.375
    assert v["computed"]["max_fsi"] == 2.5


def test_validate_emits_warning_near_limit(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    # CBD/Residential cap 2.5, warn band starts at 2.25 (10%).
    # 3 x 18x18 floors = 972 / 400 = 2.43. In the warn band.
    floors = [(lvl, 18.0, 3.0, True) for lvl in range(3)]
    resp = app_client.post(
        "/validate", json=_snapshot(floors=floors), headers=authed_headers
    )
    assert resp.status_code == 200

    body = resp.json()
    assert body["ok"] is True  # warnings don't flip ok
    assert len(body["violations"]) == 1
    assert body["violations"][0]["severity"] == "warning"


def test_validate_unknown_city_returns_404_envelope(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    snap = _snapshot()
    snap["project"]["city"] = "Atlantis"

    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_validate_rejects_malformed_polygon(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    snap = _snapshot()
    snap["plot"]["polygon"]["exterior"] = [[0, 0], [1, 0]]  # only 2 points

    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    assert resp.status_code == 422
