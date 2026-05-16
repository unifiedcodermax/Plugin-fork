"""End-to-end /validate flow against the Mumbai rule pack.

Mirrors tests/integration/test_validate.py but with Mumbai snapshots:
Island City and Suburbs classifications, CRZ + airport overlays.
Catches a future regression where the engine routes wrong, where
the Mumbai pack drifts in shape, or where shared code accidentally
picks up Bangalore values when Mumbai is targeted.

Baseline:
  - 50m x 50m plot (2500 m^2).
  - One 10m x 10m floor at (20, 20)  (10m clearance everywhere).
  - 4 parking slots provided (Mumbai parking is stricter than Bangalore).
Passes every base rule for (Island, Residential).
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
        register_user(s, username="mtester", password="hunter2pass")
        s.commit()
    resp = app_client.post(
        "/auth/login", json={"username": "mtester", "password": "hunter2pass"}
    )
    return {"Authorization": f"Bearer {resp.json()['token']}"}


# ---- helpers -----------------------------------------------------------------


def _square(size: float, ox: float = 0.0, oy: float = 0.0) -> list[list[float]]:
    return [[ox, oy], [ox + size, oy], [ox + size, oy + size], [ox, oy + size]]


def _baseline() -> dict[str, Any]:
    """Mumbai Island/Residential snapshot that passes every base rule.

    Parking budget: 100 m^2 built-up → ceil(100/75) = 2 primary +
    ceil(2 * 0.1) = 1 visitor = 3 slots required. We provide 4.
    """

    return {
        "project": {
            "city": "Mumbai",
            "classification": "Island",
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
            "parking_slots_provided": 4,
        },
    }


def _violations_by_category(body: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for v in body.get("violations", []):
        out.setdefault(v["category"], []).append(v)
    return out


def _tall(snap: dict[str, Any], n_floors: int, h_per_floor: float = 3.0) -> dict[str, Any]:
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


# ---- baseline ----------------------------------------------------------------


def test_mumbai_baseline_passes_every_rule(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    resp = app_client.post("/validate", json=_baseline(), headers=authed_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True, body["violations"]
    assert body["violations"] == []
    # Mumbai 0.2.0 is the latest at the time of this test. Base rules
    # only — no overlays in the baseline → 5 cells fire.
    assert body["metrics"]["rule_pack_version"] == "0.2.0"
    assert body["metrics"]["rule_count"] == 5


# ---- city routing ------------------------------------------------------------


def test_city_field_selects_pack(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    """Same snapshot body, two different cities → two different packs
    fire. Pins that the engine's city-routing is real, not just
    coincidence from a single registered pack."""

    mum = _baseline()
    resp_mum = app_client.post("/validate", json=mum, headers=authed_headers)
    assert resp_mum.json()["metrics"]["rule_pack_version"].startswith("0.")

    # Same physical model, but tag it Bangalore CBD/Residential. The
    # CBD-residential FSI cap is 2.5 (way more permissive than Mumbai
    # Island 1.33), so the snapshot still passes.
    blr = _baseline()
    blr["project"] = {
        "city": "Bangalore",
        "classification": "CBD",
        "zone": "Residential",
    }
    resp_blr = app_client.post("/validate", json=blr, headers=authed_headers)
    blr_body = resp_blr.json()
    # The metric pinned in test_validate.py's baseline test holds:
    # rule_pack_version starts with "0." for Bangalore too, but the
    # actual version differs from Mumbai's. That's our city-routing
    # signal.
    assert resp_mum.json()["metrics"]["rule_pack_version"] != blr_body["metrics"]["rule_pack_version"] or \
        resp_mum.status_code != resp_blr.status_code
    # Stronger signal: violations (if any) name the right city prefix.
    for v in resp_mum.json()["violations"]:
        assert v["rule_id"].startswith("mum.")
    for v in blr_body["violations"]:
        assert v["rule_id"].startswith("blr.")


# ---- FSI ---------------------------------------------------------------------


def test_mumbai_island_fsi_violation(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    """Mumbai Island/Residential FSI cap is 1.33 — much stricter than
    Bangalore's 2.5. A design that would PASS Bangalore CBD/Residential
    must FAIL Mumbai Island."""

    snap = _baseline()
    # 4 floors of 25x25 = 2500 m^2 / 2500 m^2 plot = FSI 1.0 (passes
    # Mumbai 1.33). 6 floors = 3750 / 2500 = 1.5 (fails).
    snap["building"]["floors"] = [
        {
            "level": i,
            "polygon": {"exterior": _square(25.0, 12.5, 12.5)},
            "height_m": 3.0,
            "is_habitable": True,
        }
        for i in range(6)
    ]
    # Boost parking to a high value — Mumbai parking is strict (1/75 m^2)
    # so 3750 m^2 needs 50 + 5 visitor = 55. Provide 60 to be safe.
    snap["building"]["parking_slots_provided"] = 60

    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    body = resp.json()
    by_cat = _violations_by_category(body)
    assert "fsi" in by_cat, body
    v = by_cat["fsi"][0]
    assert v["rule_id"] == "mum.fsi.island.residential"
    assert v["computed"]["fsi"] == 1.5
    assert v["computed"]["max_fsi"] == 1.33


# ---- CRZ overlay -------------------------------------------------------------


def test_crz_overlay_triggers_stricter_fsi(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    """CRZ caps FSI at 1.0; baseline Mumbai Island is 1.33 with a
    10% warn band (1.197+). Target FSI 1.12: clear of the base
    warn band, over the CRZ cap. CRZ fires as an error; base stays
    silent."""

    snap = _baseline()
    snap["project"]["overlays"] = ["crz"]
    # 7 floors × 20×20 footprint = 7 × 400 m^2 = 2800 m^2 built-up.
    # FSI = 2800 / 2500 = 1.12. Above CRZ 1.0, below base warn floor
    # (0.9 × 1.33 = 1.197). 20×20 at offset (15,15) → 15 m clearance,
    # well above the 3 m Island/Residential setback. Coverage 16%.
    snap["building"]["floors"] = [
        {
            "level": i,
            "polygon": {"exterior": _square(20.0, 15.0, 15.0)},
            "height_m": 3.0,
            "is_habitable": True,
        }
        for i in range(7)
    ]
    # 2800 m^2 / 75 = 38 primary + 4 visitor = 42. Provide 45.
    snap["building"]["parking_slots_provided"] = 45

    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    body = resp.json()
    by_cat = _violations_by_category(body)
    assert "fsi" in by_cat, body
    ids = {v["rule_id"] for v in by_cat["fsi"]}
    assert "mum.overlay.crz.fsi" in ids
    assert "mum.fsi.island.residential" not in ids, (
        f"base FSI rule fired at FSI 1.12 (should be silent below warn floor 1.197): "
        f"{by_cat['fsi']}"
    )


def test_crz_overlay_no_violation_when_compliant(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    """CRZ overlay PRESENT but design at FSI 0.4 < 1.0 → no
    violation, but the CRZ rule still fires (rule_count includes it)."""

    snap = _baseline()
    snap["project"]["overlays"] = ["crz"]
    # 1 floor of 10x10 = 100 / 2500 = FSI 0.04. Well under CRZ 1.0.

    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    body = resp.json()
    assert body["ok"] is True, body["violations"]
    # Base (5) + CRZ overlay = 6 rules fired.
    assert body["metrics"]["rule_count"] == 6


# ---- airport overlay ---------------------------------------------------------


def test_airport_overlay_shared_evaluator_across_cities(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    """The airport overlay uses the same evaluator/overlay key in
    both cities. A tall building under the Mumbai airport overlay
    should produce a violation with the mum.* rule id, not the blr.*
    one — proving the engine selects the right pack's overlay rule."""

    snap = _tall(_baseline(), n_floors=20)  # 60 m, over 45 m cap.
    snap["project"]["overlays"] = ["airport"]
    # 2000 m^2 built-up / 75 = 27 + 3 visitor = 30. Provide 35.
    snap["building"]["parking_slots_provided"] = 35

    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    body = resp.json()
    by_cat = _violations_by_category(body)
    assert "height" in by_cat, body
    height_ids = {v["rule_id"] for v in by_cat["height"]}
    assert "mum.overlay.airport.height" in height_ids
    assert "blr.overlay.airport.height" not in height_ids


# ---- routing edge case -------------------------------------------------------


def test_mumbai_unknown_classification_silently_matches_nothing(
    app_client: TestClient, authed_headers: dict[str, str]
) -> None:
    """A Bangalore-shaped classification ("CBD") sent with city=Mumbai
    must NOT match Mumbai rules (which only know "Island"/"Suburbs").
    This is the user-facing failure mode of accidental cross-city
    config: no rules fire, design passes by default. We log this
    but don't fail-loud — there's no "right" thing to do (other than
    write a guard, which is a future sprint)."""

    snap = _baseline()
    snap["project"]["classification"] = "CBD"  # Bangalore-shaped value

    resp = app_client.post("/validate", json=snap, headers=authed_headers)
    body = resp.json()
    # Only zone-wildcard rules (coverage, open_space, parking) fire.
    # FSI and setback are classification-keyed and skip.
    cats = {v["rule_id"] for v in body["violations"]}
    for cat in cats:
        assert cat.startswith("mum."), cat
    assert body["metrics"]["rule_count"] == 3  # the three zone-wildcards
