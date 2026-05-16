"""End-to-end /validate flow through the live FastAPI app.

Uses the real Bangalore rule pack (no test pack substitution) so a
regression in either the shipped pack or any evaluator is caught
by this suite, not just by isolated unit tests.

Baseline snapshot:
  - 50m x 50m plot (2500 m^2).
  - One 10m x 10m floor at (20, 20)  (10m clearance everywhere).
  - 2 parking slots provided.
That passes every rule. Each test starts from the baseline and
tweaks ONE dimension to drive the target violation.
"""

from __future__ import annotations

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
    init_db()
    with Session(get_engine()) as s:
        register_user(s, username="vtester", password="hunter2pass")
        s.commit()
    resp = app_client.post(
        "/auth/login", json={"username": "vtester", "password": "hunter2pass"}
    )
    return {"Authorization": f"Bearer {resp.json()['token']}"}


# ---- helpers -----------------------------------------------------------------


def _square(size: float, ox: float = 0.0, oy: float = 0.0) -> list[list[float]]:
    return [[ox, oy], [ox + size, oy], [ox + size, oy + size], [ox, oy + size]]


def _baseline() -> dict[str, Any]:
    """A snapshot that passes every Sprint-4 rule for CBD/Residential."""

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


def _violations_by_category(body: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for v in body.get("violations", []):
        out.setdefault(v["category"], []).append(v)
    return out


# ---- baseline ----------------------------------------------------------------


def test_validate_requires_auth(app_client: TestClient) -> None:
    resp = app_client.post("/validate", json=_baseline())
    assert resp.status_code == 401


def test_baseline_passes_every_rule(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    resp = app_client.post("/validate", json=_baseline(), headers=authed_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True, body["violations"]
    assert body["violations"] == []
    assert body["metrics"]["rule_pack_version"] == "0.3.0"
    # No overlays in the baseline snapshot → only the 5 base categories
    # fire (overlay height rules are skipped).
    assert body["metrics"]["rule_count"] == 5  # fsi + setback + coverage + open_space + parking


# ---- FSI ---------------------------------------------------------------------


def test_fsi_violation(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    snap = _baseline()
    # 7 floors of 35x35 = 8575m^2 / 2500m^2 = 3.43 (> CBD/Res cap 2.5).
    # Centered at (7.5, 7.5) -> 7.5m clearance (passes 2m setback).
    snap["building"]["floors"] = [
        {
            "level": i,
            "polygon": {"exterior": _square(35.0, 7.5, 7.5)},
            "height_m": 3.0,
            "is_habitable": True,
        }
        for i in range(7)
    ]
    # Parking: 8575/100 + 10% visitor = 86 + 9 = 95 required.
    snap["building"]["parking_slots_provided"] = 95
    # Coverage: 1225/2500 = 49% (under 60%, ok).
    # Open space: 51% (above 25%, ok).

    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    body = resp.json()
    by_cat = _violations_by_category(body)
    assert "fsi" in by_cat, body
    v = by_cat["fsi"][0]
    assert v["rule_id"] == "blr.fsi.cbd.residential"
    assert v["computed"]["fsi"] == 3.43
    assert v["severity"] == "error"


def test_fsi_warning_near_limit(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    snap = _baseline()
    # 5 floors of 35x35 = 6125 / 2500 = 2.45. In CBD/Res warn band [2.25, 2.5].
    snap["building"]["floors"] = [
        {
            "level": i,
            "polygon": {"exterior": _square(35.0, 7.5, 7.5)},
            "height_m": 3.0,
            "is_habitable": True,
        }
        for i in range(5)
    ]
    # Parking: 6125/100 = 62 primary, ceil(62 * 0.1) = 7 visitor = 69.
    snap["building"]["parking_slots_provided"] = 69

    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    body = resp.json()
    by_cat = _violations_by_category(body)
    assert "fsi" in by_cat
    assert by_cat["fsi"][0]["severity"] == "warning"
    # ok stays True because only the warning fires.
    assert body["ok"] is True


# ---- Setback -----------------------------------------------------------------


def test_setback_violation(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    snap = _baseline()
    # Slide to (1, 20) -> 1m clearance on west. CBD/Res requires 2m.
    snap["building"]["floors"][0]["polygon"]["exterior"] = _square(10.0, 1.0, 20.0)
    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    body = resp.json()
    by_cat = _violations_by_category(body)
    assert "setback" in by_cat, body
    v = by_cat["setback"][0]
    assert v["rule_id"] == "blr.setback.cbd.residential"
    assert v["computed"]["min_distance_m"] == 1.0
    assert v["computed"]["violating_level"] == 0


# ---- Coverage ----------------------------------------------------------------


def test_coverage_violation(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    snap = _baseline()
    # 40x40 = 1600 / 2500 = 64% (> 60% cap). Centered at (5,5) -> 5m clearance.
    snap["building"]["floors"][0]["polygon"]["exterior"] = _square(40.0, 5.0, 5.0)
    # Parking: 1600/100 + 10% visitor = 16 + 2 = 18.
    snap["building"]["parking_slots_provided"] = 18

    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    body = resp.json()
    by_cat = _violations_by_category(body)
    assert "coverage" in by_cat, body
    assert by_cat["coverage"][0]["rule_id"] == "blr.coverage.residential"
    assert by_cat["coverage"][0]["computed"]["coverage_pct"] == 64.0


# ---- Open space --------------------------------------------------------------


def test_open_space_violation(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    snap = _baseline()
    # 45x45 = 2025 / 2500 = 81% (over 60% cap, fails coverage too).
    # Open space = 19% < 25% min.
    # Centered at (2.5, 2.5) -> 2.5m clearance > 2m cap, ok.
    snap["building"]["floors"][0]["polygon"]["exterior"] = _square(45.0, 2.5, 2.5)
    # Parking: 2025/100 + 10% visitor = 21 + 3 = 24.
    snap["building"]["parking_slots_provided"] = 24

    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    body = resp.json()
    by_cat = _violations_by_category(body)
    assert "open_space" in by_cat, body
    assert "coverage" in by_cat  # both fail by construction
    v = by_cat["open_space"][0]
    assert v["rule_id"] == "blr.open_space.residential"
    assert v["computed"]["open_space_pct"] == 19.0


# ---- Parking -----------------------------------------------------------------


def test_parking_violation(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    snap = _baseline()
    # Baseline 100m^2: CBD/Res = 1/100 + 10% visitor = ceil(1) + ceil(0.1) = 2.
    snap["building"]["parking_slots_provided"] = 0
    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    body = resp.json()
    by_cat = _violations_by_category(body)
    assert "parking" in by_cat
    v = by_cat["parking"][0]
    assert v["rule_id"] == "blr.parking.residential"
    assert v["computed"]["parking_slots_required"] == 2
    assert v["computed"]["parking_slots_provided"] == 0


# ---- error paths -------------------------------------------------------------


def test_validate_unknown_city_returns_404_envelope(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    snap = _baseline()
    snap["project"]["city"] = "Atlantis"
    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_validate_rejects_malformed_polygon(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    snap = _baseline()
    snap["plot"]["polygon"]["exterior"] = [[0, 0], [1, 0]]  # only 2 points
    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    assert resp.status_code == 422


def test_baseline_returns_fresh_dict() -> None:
    """Tests mutate _baseline()'s output; pin that the helper returns
    a fresh dict each call so test order doesn't matter."""

    a = _baseline()
    a["project"]["city"] = "MUTATED"
    assert _baseline()["project"]["city"] == "Bangalore"

    b = _baseline()
    b["building"]["floors"][0]["level"] = 99
    assert _baseline()["building"]["floors"][0]["level"] == 0


# ---- overlays ----------------------------------------------------------------


def _tall(snap: dict[str, Any], n_floors: int, h_per_floor: float = 3.0) -> dict[str, Any]:
    """Replace the baseline's single floor with n stacked floors of
    h_per_floor m each. Keeps the 10×10 footprint at (20, 20)."""

    snap["building"]["floors"] = [
        {
            "level": i,
            "polygon": {"exterior": _square(10.0, 20.0, 20.0)},
            "height_m": h_per_floor,
            "is_habitable": True,
        }
        for i in range(n_floors)
    ]
    return snap


def test_no_overlay_skips_height_rules_even_for_tall_building(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    """Tall building with NO overlays must not fire either height rule.
    Overlay rules are opt-in; the absence of an overlay key is the
    user saying 'this site isn't in that zone'."""

    snap = _tall(_baseline(), n_floors=20)  # 60m, well above both overlay caps.
    # Boost parking and stay within FSI limit by keeping footprint small:
    # 20 × 100 = 2000m^2 / 2500 = 0.8 FSI (under 2.5 cap).
    snap["building"]["parking_slots_provided"] = 30  # 2000/100 + 10% = 22.

    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    body = resp.json()
    by_cat = _violations_by_category(body)
    assert "height" not in by_cat, body
    assert body["metrics"]["rule_count"] == 5


def test_airport_overlay_triggers_height_violation(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    """20 × 3m = 60m > 45m airport cap → violation fires."""

    snap = _tall(_baseline(), n_floors=20)
    snap["project"]["overlays"] = ["airport"]
    snap["building"]["parking_slots_provided"] = 30

    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    body = resp.json()
    by_cat = _violations_by_category(body)
    assert "height" in by_cat, body
    v = by_cat["height"][0]
    assert v["rule_id"] == "blr.overlay.airport.height"
    assert v["computed"]["height_m"] == 60.0
    assert v["computed"]["max_height_m"] == 45.0
    assert v["severity"] == "error"
    assert body["ok"] is False


def test_airport_overlay_compliant_height_passes(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    """Same overlay, 10-floor / 30m building → under 45m, no violation,
    but the overlay rule still fired (rule_count = base + 1)."""

    snap = _tall(_baseline(), n_floors=10)
    snap["project"]["overlays"] = ["airport"]
    snap["building"]["parking_slots_provided"] = 15  # 1000/100 + 10% = 11.

    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    body = resp.json()
    by_cat = _violations_by_category(body)
    assert "height" not in by_cat, body
    assert body["metrics"]["rule_count"] == 6
    assert body["metrics"]["height_m"] == 30.0


def test_heritage_influence_overlay_triggers_height_violation(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    """5 × 3m = 15m > 12m heritage skyline → violation fires."""

    snap = _tall(_baseline(), n_floors=5)
    snap["project"]["overlays"] = ["heritage_influence"]
    snap["building"]["parking_slots_provided"] = 10  # 500/100 + 10% = 6.

    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    body = resp.json()
    by_cat = _violations_by_category(body)
    assert "height" in by_cat, body
    assert by_cat["height"][0]["rule_id"] == "blr.overlay.heritage_influence.height"
    assert by_cat["height"][0]["computed"]["max_height_m"] == 12.0


def test_both_overlays_stack_both_violations_fire(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    """50m building under both overlays violates both caps independently.
    Two distinct height violations, distinct rule_ids."""

    snap = _tall(_baseline(), n_floors=17, h_per_floor=3.0)  # 51m.
    snap["project"]["overlays"] = ["airport", "heritage_influence"]
    snap["building"]["parking_slots_provided"] = 25  # 1700/100 + 10% = 19.

    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    body = resp.json()
    by_cat = _violations_by_category(body)
    assert "height" in by_cat
    rule_ids = sorted(v["rule_id"] for v in by_cat["height"])
    assert rule_ids == [
        "blr.overlay.airport.height",
        "blr.overlay.heritage_influence.height",
    ]


def test_unknown_overlay_silently_fires_nothing(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    """An overlay key that no rule references must not error — it just
    doesn't add any rules. Lets the Ruby side ship an overlay name
    before the pack catches up, without breaking validation."""

    snap = _tall(_baseline(), n_floors=20)
    snap["project"]["overlays"] = ["fire_zone"]  # no rule in 0.3.0 yet.
    snap["building"]["parking_slots_provided"] = 30

    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    body = resp.json()
    assert "height" not in _violations_by_category(body)
    assert body["metrics"]["rule_count"] == 5
