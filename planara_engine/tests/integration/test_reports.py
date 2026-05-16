"""End-to-end /reports flow through the live FastAPI app.

Same baseline shape as tests/integration/test_validate.py — minimal
Bangalore-CBD-Residential snapshot — plus a Mumbai snapshot so we
catch any city-routing leak. Verifies content negotiation, auth,
and that the server re-validates rather than trusting the caller.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

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
        "PLANARA_JWT_SECRET", "reports-test-secret-of-sufficient-length"
    )
    monkeypatch.setenv("PLANARA_JWT_TTL_MINUTES", "60")
    get_engine.cache_clear()
    get_pack.cache_clear()
    return Settings(
        env=Environment.test,
        db_url=db_url,
        jwt_secret="reports-test-secret-of-sufficient-length",
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
    init_db()
    with Session(get_engine()) as s:
        register_user(s, username="rtester", password="hunter2pass")
        s.commit()
    resp = app_client.post(
        "/auth/login", json={"username": "rtester", "password": "hunter2pass"}
    )
    return {"Authorization": f"Bearer {resp.json()['token']}"}


# ---- helpers -----------------------------------------------------------------


def _square(size: float, ox: float = 0.0, oy: float = 0.0) -> list[list[float]]:
    return [[ox, oy], [ox + size, oy], [ox + size, oy + size], [ox, oy + size]]


def _bangalore_baseline() -> dict[str, Any]:
    return {
        "project": {
            "city": "Bangalore",
            "classification": "CBD",
            "zone": "Residential",
        },
        "plot": {"polygon": {"exterior": _square(50.0)}},
        "building": {
            "floors": [
                {
                    "level": 0,
                    "polygon": {"exterior": _square(10.0, 20.0, 20.0)},
                    "height_m": 3.0,
                    "is_habitable": True,
                }
            ],
            "parking_slots_provided": 2,
        },
    }


def _mumbai_baseline() -> dict[str, Any]:
    snap = _bangalore_baseline()
    snap["project"] = {
        "city": "Mumbai",
        "classification": "Island",
        "zone": "Residential",
    }
    snap["building"]["parking_slots_provided"] = 4
    return snap


# ---- auth + content negotiation ---------------------------------------------


def test_reports_requires_auth(app_client: TestClient) -> None:
    resp = app_client.post("/reports", json=_bangalore_baseline())
    assert resp.status_code == 401


def test_reports_default_to_html(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    """No Accept header → HTML (matches what a browser would get)."""

    resp = app_client.post("/reports", json=_bangalore_baseline(), headers=authed_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "<!DOCTYPE html>" in resp.text
    assert "Planara compliance report" in resp.text


def test_reports_html_explicit(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    h = {**authed_headers, "Accept": "text/html"}
    resp = app_client.post("/reports", json=_bangalore_baseline(), headers=h)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")


def test_reports_json_returns_archive(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    h = {**authed_headers, "Accept": "application/json"}
    resp = app_client.post("/reports", json=_bangalore_baseline(), headers=h)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")

    body = resp.json()
    assert "report_id" in body
    assert body["report_schema_version"] == "1.0"
    assert body["engine_version"]  # whatever the current version is
    assert body["generated_at"]
    assert body["snapshot"]["project"]["city"] == "Bangalore"
    assert body["response"]["ok"] is True


def test_reports_rejects_unsupported_accept(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    h = {**authed_headers, "Accept": "application/pdf"}
    resp = app_client.post("/reports", json=_bangalore_baseline(), headers=h)
    # ValidationFailed maps to 422 in the error envelope.
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert "text/html" in err["details"]["supported"]


# ---- content correctness -----------------------------------------------------


def test_reports_html_includes_failing_rule_message(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    """A failing snapshot must produce an HTML report that names the
    violated rule. Catches a renderer drift where violations get
    dropped on the way to HTML."""

    snap = _bangalore_baseline()
    # FSI violation: 8 stacked floors of 35x35 → FSI 3.92 > 2.5 cap.
    snap["building"]["floors"] = [
        {
            "level": i,
            "polygon": {"exterior": _square(35.0, 7.5, 7.5)},
            "height_m": 3.0,
            "is_habitable": True,
        }
        for i in range(8)
    ]
    snap["building"]["parking_slots_provided"] = 200

    resp = app_client.post("/reports", json=snap, headers=authed_headers)
    assert resp.status_code == 200
    assert "FAIL" in resp.text
    assert "blr.fsi.cbd.residential" in resp.text


def test_reports_mumbai_archive_mentions_mumbai_pack(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    """An archival report for a Mumbai snapshot must echo Mumbai
    (not Bangalore) as the city, and carry Mumbai's pack version
    in the embedded response metrics."""

    h = {**authed_headers, "Accept": "application/json"}
    resp = app_client.post("/reports", json=_mumbai_baseline(), headers=h)
    body = resp.json()
    assert body["snapshot"]["project"]["city"] == "Mumbai"
    assert body["response"]["metrics"]["rule_pack_version"] == "0.2.0"


def test_reports_server_revalidates_not_trusts_caller(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    """Reports must reflect what the server actually computes — not
    a ValidationResponse a client could have crafted. The caller
    sends only a Snapshot; the route runs evaluate() itself."""

    snap = _bangalore_baseline()
    # Slip a 'response' key into the body; the route should ignore it
    # (Pydantic parses into Snapshot, which has no such field — extra
    # keys are silently dropped under the default ConfigDict).
    snap["response"] = {
        "ok": False,
        "violations": [{"rule_id": "fake.injected", "category": "fsi", "severity": "error", "message": "forged"}],
        "metrics": {},
    }

    h = {**authed_headers, "Accept": "application/json"}
    resp = app_client.post("/reports", json=snap, headers=h)
    assert resp.status_code == 200
    body = resp.json()
    assert body["response"]["ok"] is True
    assert all(v["rule_id"] != "fake.injected" for v in body["response"]["violations"])


def test_reports_archive_round_trips_through_json(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    """The archival JSON is meant to be saved and read back later.
    Pin that we can parse our own output without losing fidelity."""

    h = {**authed_headers, "Accept": "application/json"}
    resp = app_client.post("/reports", json=_bangalore_baseline(), headers=h)
    raw = resp.content
    parsed = json.loads(raw)
    # Re-serialize and compare structurally (key order doesn't matter).
    re_encoded = json.loads(json.dumps(parsed))
    assert re_encoded == parsed
