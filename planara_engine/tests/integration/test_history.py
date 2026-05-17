"""End-to-end /history flow through the live FastAPI app.

Covers all four routes — POST /history (save), GET /history (list,
filters, pagination), GET /history/{id} (fetch archive), GET
/history/{id}/html (re-render). User-scope isolation: a second user
running in the same DB must not see the first user's reports.
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
        "PLANARA_JWT_SECRET", "history-test-secret-of-sufficient-length"
    )
    monkeypatch.setenv("PLANARA_JWT_TTL_MINUTES", "60")
    get_engine.cache_clear()
    get_pack.cache_clear()
    return Settings(
        env=Environment.test,
        db_url=db_url,
        jwt_secret="history-test-secret-of-sufficient-length",
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


def _login(client: TestClient, username: str, password: str = "hunter2pass") -> dict[str, str]:
    init_db()
    with Session(get_engine()) as s:
        # Idempotent registration — tests may call this twice in one DB.
        from planara_engine.persistence.repository import get_user_by_username
        if get_user_by_username(s, username) is None:
            register_user(s, username=username, password=password)
            s.commit()
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture
def alice(app_client: TestClient) -> dict[str, str]:
    return _login(app_client, "alice")


@pytest.fixture
def bob(app_client: TestClient) -> dict[str, str]:
    return _login(app_client, "bob")


# ---- helpers -----------------------------------------------------------------


def _square(size: float, ox: float = 0.0, oy: float = 0.0) -> list[list[float]]:
    return [[ox, oy], [ox + size, oy], [ox + size, oy + size], [ox, oy + size]]


def _bangalore() -> dict[str, Any]:
    return {
        "project": {"city": "Bangalore", "classification": "CBD", "zone": "Residential"},
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


def _mumbai() -> dict[str, Any]:
    s = _bangalore()
    s["project"] = {"city": "Mumbai", "classification": "Island", "zone": "Residential"}
    s["building"]["parking_slots_provided"] = 4
    return s


# ---- POST /history -----------------------------------------------------------


def test_history_requires_auth(app_client: TestClient) -> None:
    resp = app_client.post("/history", json=_bangalore())
    assert resp.status_code == 401


def test_history_save_returns_201_with_archive(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    resp = app_client.post("/history", json=_bangalore(), headers=alice)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "report_id" in body
    assert body["report_schema_version"] == "1.0"
    assert body["snapshot"]["project"]["city"] == "Bangalore"
    assert body["response"]["ok"] is True


def test_history_save_persists_for_subsequent_fetch(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    save = app_client.post("/history", json=_bangalore(), headers=alice)
    rid = save.json()["report_id"]

    get_resp = app_client.get(f"/history/{rid}", headers=alice)
    assert get_resp.status_code == 200
    fetched = get_resp.json()
    assert fetched["report_id"] == rid
    assert fetched["snapshot"]["project"]["city"] == "Bangalore"


# ---- GET /history (list) -----------------------------------------------------


def test_list_empty_for_new_user(app_client: TestClient, alice: dict[str, str]) -> None:
    resp = app_client.get("/history", headers=alice)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["limit"] == 20
    assert body["offset"] == 0


def test_list_returns_summary_not_full_archive(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    """Summary rows must NOT include the full payload — that would
    explode response size as history grows."""

    app_client.post("/history", json=_bangalore(), headers=alice)
    resp = app_client.get("/history", headers=alice)
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert "report_id" in item
    assert "violation_count" in item
    assert "snapshot" not in item  # full archive deliberately omitted
    assert "response" not in item


def test_list_orders_recent_first(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    """Save three times; the most-recent save appears first."""

    rids = []
    for _ in range(3):
        r = app_client.post("/history", json=_bangalore(), headers=alice)
        rids.append(r.json()["report_id"])

    body = app_client.get("/history", headers=alice).json()
    listed = [it["report_id"] for it in body["items"]]
    assert listed == list(reversed(rids))


def test_list_filters_by_city(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    app_client.post("/history", json=_bangalore(), headers=alice)
    app_client.post("/history", json=_bangalore(), headers=alice)
    app_client.post("/history", json=_mumbai(), headers=alice)

    blr = app_client.get("/history?city=Bangalore", headers=alice).json()
    mum = app_client.get("/history?city=Mumbai", headers=alice).json()
    assert blr["total"] == 2
    assert mum["total"] == 1
    assert {it["city"] for it in blr["items"]} == {"Bangalore"}


def test_list_filters_by_ok(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    # passing snapshot
    app_client.post("/history", json=_bangalore(), headers=alice)
    # failing snapshot — 8 stacked floors at 35x35 → FSI 3.92 > 2.5
    fail = _bangalore()
    fail["building"]["floors"] = [
        {
            "level": i,
            "polygon": {"exterior": _square(35.0, 7.5, 7.5)},
            "height_m": 3.0,
            "is_habitable": True,
        }
        for i in range(8)
    ]
    fail["building"]["parking_slots_provided"] = 200
    app_client.post("/history", json=fail, headers=alice)

    passing = app_client.get("/history?ok=true", headers=alice).json()
    failing = app_client.get("/history?ok=false", headers=alice).json()
    assert passing["total"] == 1
    assert failing["total"] == 1
    assert failing["items"][0]["error_count"] >= 1


def test_list_paginates(app_client: TestClient, alice: dict[str, str]) -> None:
    for _ in range(7):
        app_client.post("/history", json=_bangalore(), headers=alice)

    page1 = app_client.get("/history?limit=3&offset=0", headers=alice).json()
    page2 = app_client.get("/history?limit=3&offset=3", headers=alice).json()
    page3 = app_client.get("/history?limit=3&offset=6", headers=alice).json()

    assert page1["total"] == page2["total"] == page3["total"] == 7
    assert len(page1["items"]) == 3
    assert len(page2["items"]) == 3
    assert len(page3["items"]) == 1
    ids = {it["report_id"] for it in page1["items"] + page2["items"] + page3["items"]}
    assert len(ids) == 7


def test_list_rejects_oversized_limit(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    resp = app_client.get("/history?limit=1000", headers=alice)
    # FastAPI Query(le=100) → 422 on out-of-range.
    assert resp.status_code == 422


# ---- user-scope isolation ----------------------------------------------------


def test_users_cannot_read_each_others_reports(
    app_client: TestClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    """Bob asking for Alice's report by ID gets 404, not 403 — same
    response as a non-existent ID, so the existence of other users'
    reports doesn't leak."""

    save = app_client.post("/history", json=_bangalore(), headers=alice)
    rid = save.json()["report_id"]

    bob_get = app_client.get(f"/history/{rid}", headers=bob)
    assert bob_get.status_code == 404

    # Bob's list is empty even though Alice has a row.
    bob_list = app_client.get("/history", headers=bob).json()
    assert bob_list["total"] == 0


# ---- GET /history/{id} -------------------------------------------------------


def test_get_unknown_id_returns_404(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    resp = app_client.get("/history/00000000-0000-0000-0000-000000000000", headers=alice)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_get_archive_round_trips_payload(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    """The fetched archive must equal what /history returned at save
    time — the persisted payload is the source of truth."""

    save = app_client.post("/history", json=_bangalore(), headers=alice)
    saved = save.json()
    fetched = app_client.get(f"/history/{saved['report_id']}", headers=alice).json()
    assert fetched == saved


# ---- GET /history/{id}/html --------------------------------------------------


def test_get_html_re_renders_from_stored_payload(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    save = app_client.post("/history", json=_bangalore(), headers=alice)
    rid = save.json()["report_id"]

    resp = app_client.get(f"/history/{rid}/html", headers=alice)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "<!DOCTYPE html>" in resp.text
    # The stored archive's city must appear in the rendered HTML.
    assert "Bangalore" in resp.text


def test_get_html_unknown_id_returns_404(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    resp = app_client.get(
        "/history/00000000-0000-0000-0000-000000000000/html", headers=alice
    )
    assert resp.status_code == 404


def test_get_html_user_scoped(
    app_client: TestClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    save = app_client.post("/history", json=_bangalore(), headers=alice)
    rid = save.json()["report_id"]
    bob_resp = app_client.get(f"/history/{rid}/html", headers=bob)
    assert bob_resp.status_code == 404


# ---- diff routes -------------------------------------------------------------


def _save_failing(client: TestClient, headers: dict[str, str]) -> str:
    """Save a snapshot that fails one rule (FSI 3.92 > 2.5)."""

    snap = _bangalore()
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
    resp = client.post("/history", json=snap, headers=headers)
    return resp.json()["report_id"]


def test_diff_explicit_unchanged_when_same_id(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    """Diff a report against itself — overall=unchanged."""

    rid = app_client.post("/history", json=_bangalore(), headers=alice).json()["report_id"]
    resp = app_client.get(f"/history/diff?from={rid}&to={rid}", headers=alice)
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall"] == "unchanged"
    assert body["from_report_id"] == rid
    assert body["to_report_id"] == rid


def test_diff_explicit_regressed_when_curr_introduces_violation(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    """First save passes; second save introduces FSI violation
    → diff verdict 'regressed', added=1."""

    pass_id = app_client.post("/history", json=_bangalore(), headers=alice).json()["report_id"]
    fail_id = _save_failing(app_client, alice)

    resp = app_client.get(f"/history/diff?from={pass_id}&to={fail_id}", headers=alice)
    body = resp.json()
    assert body["overall"] == "regressed"
    assert body["summary"]["added"] == 1
    assert body["summary"]["removed"] == 0
    rule_ids = [v["rule_id"] for v in body["violations"]]
    assert "blr.fsi.cbd.residential" in rule_ids


def test_diff_explicit_improved_when_curr_fixes_violation(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    """Reverse of the previous: diff fail → pass → improved."""

    fail_id = _save_failing(app_client, alice)
    pass_id = app_client.post("/history", json=_bangalore(), headers=alice).json()["report_id"]

    resp = app_client.get(f"/history/diff?from={fail_id}&to={pass_id}", headers=alice)
    body = resp.json()
    assert body["overall"] == "improved"
    assert body["summary"]["removed"] == 1
    assert body["summary"]["added"] == 0


def test_diff_explicit_unknown_id_returns_404(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    rid = app_client.post("/history", json=_bangalore(), headers=alice).json()["report_id"]
    fake = "00000000-0000-0000-0000-000000000000"

    # 'from' missing
    r1 = app_client.get(f"/history/diff?from={fake}&to={rid}", headers=alice)
    assert r1.status_code == 404

    # 'to' missing
    r2 = app_client.get(f"/history/diff?from={rid}&to={fake}", headers=alice)
    assert r2.status_code == 404


def test_diff_explicit_other_users_report_returns_404(
    app_client: TestClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    """Bob can't diff against Alice's report — surfaces as 404,
    same as a nonexistent ID."""

    alice_id = app_client.post("/history", json=_bangalore(), headers=alice).json()["report_id"]
    bob_id = app_client.post("/history", json=_bangalore(), headers=bob).json()["report_id"]
    resp = app_client.get(f"/history/diff?from={alice_id}&to={bob_id}", headers=bob)
    assert resp.status_code == 404


def test_diff_explicit_requires_auth(app_client: TestClient) -> None:
    fake = "00000000-0000-0000-0000-000000000000"
    resp = app_client.get(f"/history/diff?from={fake}&to={fake}")
    assert resp.status_code == 401


# ---- /history/{id}/diff (vs prior) -----------------------------------------


def test_auto_diff_returns_404_when_no_prior_exists(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    """First save has nothing to compare against."""

    rid = app_client.post("/history", json=_bangalore(), headers=alice).json()["report_id"]
    resp = app_client.get(f"/history/{rid}/diff", headers=alice)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_auto_diff_compares_against_most_recent_prior_same_context(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    """Three saves of same project; auto-diff on the third reports
    a clean diff against the second (the most recent prior in the
    same context)."""

    # First passing save.
    app_client.post("/history", json=_bangalore(), headers=alice)
    # Second still passing.
    app_client.post("/history", json=_bangalore(), headers=alice)
    # Third introduces failure.
    fail_id = _save_failing(app_client, alice)

    resp = app_client.get(f"/history/{fail_id}/diff", headers=alice)
    body = resp.json()
    assert body["overall"] == "regressed"
    assert body["to_report_id"] == fail_id


def test_auto_diff_ignores_other_context_runs(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    """Mumbai run in between doesn't count as Bangalore's prior."""

    blr1 = app_client.post("/history", json=_bangalore(), headers=alice).json()["report_id"]
    # Mumbai run in between — different context, must be skipped.
    app_client.post("/history", json=_mumbai(), headers=alice)
    blr2 = app_client.post("/history", json=_bangalore(), headers=alice).json()["report_id"]

    resp = app_client.get(f"/history/{blr2}/diff", headers=alice)
    body = resp.json()
    assert resp.status_code == 200
    assert body["from_report_id"] == blr1
    assert body["to_report_id"] == blr2


def test_auto_diff_user_scoped(
    app_client: TestClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    """Alice's earlier run is NOT bob's prior even when contexts match."""

    app_client.post("/history", json=_bangalore(), headers=alice)
    bob_id = app_client.post("/history", json=_bangalore(), headers=bob).json()["report_id"]
    resp = app_client.get(f"/history/{bob_id}/diff", headers=bob)
    assert resp.status_code == 404


# ---- HTML diff routes --------------------------------------------------------


def test_diff_explicit_html_renders_regression(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    pass_id = app_client.post("/history", json=_bangalore(), headers=alice).json()["report_id"]
    fail_id = _save_failing(app_client, alice)

    resp = app_client.get(
        f"/history/diff/html?from={pass_id}&to={fail_id}", headers=alice
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    assert "<!DOCTYPE html>" in body
    assert "REGRESSED" in body
    assert "blr.fsi.cbd.residential" in body


def test_diff_explicit_html_unknown_id_returns_404(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    rid = app_client.post("/history", json=_bangalore(), headers=alice).json()["report_id"]
    fake = "00000000-0000-0000-0000-000000000000"
    resp = app_client.get(f"/history/diff/html?from={fake}&to={rid}", headers=alice)
    assert resp.status_code == 404


def test_auto_diff_html_renders_for_second_save(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    app_client.post("/history", json=_bangalore(), headers=alice)
    second = _save_failing(app_client, alice)
    resp = app_client.get(f"/history/{second}/diff/html", headers=alice)
    assert resp.status_code == 200
    assert "<!DOCTYPE html>" in resp.text
    assert "REGRESSED" in resp.text


def test_auto_diff_html_returns_404_when_no_prior(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    rid = app_client.post("/history", json=_bangalore(), headers=alice).json()["report_id"]
    resp = app_client.get(f"/history/{rid}/diff/html", headers=alice)
    assert resp.status_code == 404


def test_diff_html_requires_auth(app_client: TestClient) -> None:
    fake = "00000000-0000-0000-0000-000000000000"
    resp = app_client.get(f"/history/diff/html?from={fake}&to={fake}")
    assert resp.status_code == 401
