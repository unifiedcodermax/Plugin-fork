"""End-to-end /projects flow through the live FastAPI app.

Mirrors test_history.py's fixture style: tmp-path SQLite + bcrypt
auth + per-test isolation. Covers POST/GET /projects (create,
duplicate-name conflict, list, fetch, cross-user isolation).
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
        "PLANARA_JWT_SECRET", "projects-test-secret-of-sufficient-length"
    )
    monkeypatch.setenv("PLANARA_JWT_TTL_MINUTES", "60")
    get_engine.cache_clear()
    get_pack.cache_clear()
    return Settings(
        env=Environment.test,
        db_url=db_url,
        jwt_secret="projects-test-secret-of-sufficient-length",
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


def _make(name: str = "5th Main", city: str = "Bangalore",
          classification: str = "CBD", zone: str = "Residential") -> dict[str, str]:
    return {"name": name, "city": city, "classification": classification, "zone": zone}


# ---- auth gating -------------------------------------------------------------


def test_projects_requires_auth(app_client: TestClient) -> None:
    resp = app_client.post("/projects", json=_make())
    assert resp.status_code == 401


# ---- POST /projects ----------------------------------------------------------


def test_create_returns_201_with_id(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    resp = app_client.post("/projects", json=_make(), headers=alice)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert isinstance(body["id"], int)
    assert body["name"] == "5th Main"
    assert body["city"] == "Bangalore"
    assert body["classification"] == "CBD"
    assert body["zone"] == "Residential"
    assert "created_at" in body


def test_create_duplicate_name_for_same_user_returns_409(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    """Per-user uniqueness — the route maps ProjectNameConflict to
    409 so the plugin's '+ New project' flow can re-prompt without
    sniffing error text."""

    app_client.post("/projects", json=_make(name="dup"), headers=alice)
    second = app_client.post("/projects", json=_make(name="dup"), headers=alice)
    assert second.status_code == 409
    err = second.json()["error"]
    assert err["code"] == "conflict"
    assert err["details"]["name"] == "dup"


def test_create_same_name_different_users_succeeds(
    app_client: TestClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    """Name uniqueness is per-user, not global."""

    a = app_client.post("/projects", json=_make(name="shared"), headers=alice)
    b = app_client.post("/projects", json=_make(name="shared"), headers=bob)
    assert a.status_code == 201
    assert b.status_code == 201
    # Distinct rows, distinct ids.
    assert a.json()["id"] != b.json()["id"]


def test_create_rejects_empty_name(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    resp = app_client.post(
        "/projects", json=_make(name=""), headers=alice
    )
    # FastAPI Pydantic Field(min_length=1) → 422.
    assert resp.status_code == 422


# ---- GET /projects -----------------------------------------------------------


def test_list_empty_for_new_user(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    resp = app_client.get("/projects", headers=alice)
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["limit"] == 100
    assert body["offset"] == 0


def test_list_returns_callers_projects_only(
    app_client: TestClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    """User-scope isolation at the route layer — Bob's projects
    must never appear in Alice's list."""

    app_client.post("/projects", json=_make(name="a1"), headers=alice)
    app_client.post("/projects", json=_make(name="a2"), headers=alice)
    app_client.post("/projects", json=_make(name="b1"), headers=bob)

    alice_list = app_client.get("/projects", headers=alice).json()
    bob_list = app_client.get("/projects", headers=bob).json()
    assert {it["name"] for it in alice_list["items"]} == {"a1", "a2"}
    assert {it["name"] for it in bob_list["items"]} == {"b1"}


def test_list_orders_most_recent_first(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    for n in ("first", "second", "third"):
        app_client.post("/projects", json=_make(name=n), headers=alice)

    body = app_client.get("/projects", headers=alice).json()
    listed = [it["name"] for it in body["items"]]
    # Newest must be at the top of the picker.
    assert listed[0] == "third"
    assert set(listed) == {"first", "second", "third"}


# ---- GET /projects/{id} ------------------------------------------------------


def test_fetch_returns_own_project(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    created = app_client.post("/projects", json=_make(name="mine"), headers=alice).json()
    resp = app_client.get(f"/projects/{created['id']}", headers=alice)
    assert resp.status_code == 200
    assert resp.json()["name"] == "mine"


def test_fetch_other_users_project_returns_404(
    app_client: TestClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    """Existence must NOT leak across users — Bob fetching Alice's
    project_id gets a 404 indistinguishable from a nonexistent id."""

    created = app_client.post(
        "/projects", json=_make(name="alice-only"), headers=alice
    ).json()
    bob_view = app_client.get(f"/projects/{created['id']}", headers=bob)
    assert bob_view.status_code == 404


def test_fetch_unknown_id_returns_404(
    app_client: TestClient, alice: dict[str, str]
) -> None:
    resp = app_client.get("/projects/99999", headers=alice)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
