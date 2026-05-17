"""Unit tests for persistence.projects — create / list / get / get_by_name.

Mirrors test_reports_repository.py: in-memory SQLite per test, every
call user-scoped. The interesting invariants are (1) per-user name
uniqueness raises ProjectNameConflict (not a leaky IntegrityError),
and (2) cross-user isolation — a project owned by Bob must never
appear in any of Alice's queries.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from planara_engine.persistence.models import User
from planara_engine.persistence.projects import (
    ProjectNameConflict,
    create_project,
    get_project,
    get_project_by_name,
    list_projects,
)


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def alice_id(engine: Engine) -> int:
    with Session(engine) as s:
        u = User(username="alice", password_hash="x")
        s.add(u)
        s.commit()
        s.refresh(u)
        assert u.id is not None
        return u.id


@pytest.fixture
def bob_id(engine: Engine) -> int:
    with Session(engine) as s:
        u = User(username="bob", password_hash="x")
        s.add(u)
        s.commit()
        s.refresh(u)
        assert u.id is not None
        return u.id


# ---- create_project ----------------------------------------------------------


def test_create_returns_persisted_row(engine: Engine, alice_id: int) -> None:
    with Session(engine) as s:
        row = create_project(
            s,
            user_id=alice_id,
            name="5th Main",
            city="Bangalore",
            classification="CBD",
            zone="Residential",
        )
        s.commit()
        s.refresh(row)

        assert row.id is not None
        assert row.user_id == alice_id
        assert row.name == "5th Main"
        assert row.city == "Bangalore"
        assert row.classification == "CBD"
        assert row.zone == "Residential"
        assert row.created_at is not None


def test_create_duplicate_name_same_user_raises_conflict(
    engine: Engine, alice_id: int
) -> None:
    """Per-user uniqueness must surface as a domain exception so the
    route can map it to 409 without sniffing IntegrityError shapes."""

    with Session(engine) as s:
        create_project(
            s,
            user_id=alice_id,
            name="downtown",
            city="Bangalore",
            classification="CBD",
            zone="Residential",
        )
        s.commit()

    with Session(engine) as s:
        with pytest.raises(ProjectNameConflict) as excinfo:
            create_project(
                s,
                user_id=alice_id,
                name="downtown",
                city="Mumbai",  # different context — name is what collides
                classification="Island",
                zone="Commercial",
            )
        # The exception carries the conflicting name so the route
        # layer can include it in the 409 detail.
        assert excinfo.value.name == "downtown"


def test_create_same_name_different_users_is_allowed(
    engine: Engine, alice_id: int, bob_id: int
) -> None:
    """Names are unique per user, not globally — two users can each
    have a project called '5th Main'."""

    with Session(engine) as s:
        create_project(
            s,
            user_id=alice_id,
            name="5th Main",
            city="Bangalore",
            classification="CBD",
            zone="Residential",
        )
        create_project(
            s,
            user_id=bob_id,
            name="5th Main",
            city="Bangalore",
            classification="CBD",
            zone="Residential",
        )
        s.commit()


def test_conflict_rolls_back_so_session_is_still_usable(
    engine: Engine, alice_id: int
) -> None:
    """After ProjectNameConflict, the session is in a clean state
    and a subsequent create with a different name succeeds — the
    repo must rollback the failing flush, not leave the session
    in error mode."""

    with Session(engine) as s:
        create_project(
            s,
            user_id=alice_id,
            name="dup",
            city="Bangalore",
            classification="CBD",
            zone="Residential",
        )
        s.commit()

    with Session(engine) as s:
        with pytest.raises(ProjectNameConflict):
            create_project(
                s,
                user_id=alice_id,
                name="dup",
                city="Bangalore",
                classification="CBD",
                zone="Residential",
            )
        # Same session, fresh insert under a new name must succeed.
        ok = create_project(
            s,
            user_id=alice_id,
            name="fresh",
            city="Bangalore",
            classification="CBD",
            zone="Residential",
        )
        s.commit()
        assert ok.id is not None


# ---- list_projects -----------------------------------------------------------


def test_list_returns_only_callers_projects(
    engine: Engine, alice_id: int, bob_id: int
) -> None:
    with Session(engine) as s:
        create_project(s, user_id=alice_id, name="a1", city="x", classification="y", zone="z")
        create_project(s, user_id=alice_id, name="a2", city="x", classification="y", zone="z")
        create_project(s, user_id=bob_id, name="b1", city="x", classification="y", zone="z")
        s.commit()

    with Session(engine) as s:
        alice_rows = list_projects(s, user_id=alice_id)
        bob_rows = list_projects(s, user_id=bob_id)
        assert {r.name for r in alice_rows} == {"a1", "a2"}
        assert {r.name for r in bob_rows} == {"b1"}


def test_list_orders_recent_first(engine: Engine, alice_id: int) -> None:
    """Most-recent-first ordering — the UI shows the newest project
    at the top of the picker."""

    names = ["first", "second", "third"]
    with Session(engine) as s:
        for n in names:
            create_project(s, user_id=alice_id, name=n, city="x", classification="y", zone="z")
        s.commit()

    with Session(engine) as s:
        rows = list_projects(s, user_id=alice_id)
        # Same wall-clock can produce ties on fast machines — assert
        # the most recent (third) is present and ties go to last
        # inserted via natural insertion order.
        listed = [r.name for r in rows]
        assert listed[0] == "third"
        assert set(listed) == set(names)


def test_list_paginates(engine: Engine, alice_id: int) -> None:
    with Session(engine) as s:
        for i in range(5):
            create_project(
                s, user_id=alice_id, name=f"p{i}", city="x", classification="y", zone="z",
            )
        s.commit()

    with Session(engine) as s:
        page1 = list_projects(s, user_id=alice_id, limit=2, offset=0)
        page2 = list_projects(s, user_id=alice_id, limit=2, offset=2)
        page3 = list_projects(s, user_id=alice_id, limit=2, offset=4)
        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1
        ids = {r.id for r in page1 + page2 + page3}
        assert len(ids) == 5


# ---- get_project -------------------------------------------------------------


def test_get_returns_own_row(engine: Engine, alice_id: int) -> None:
    with Session(engine) as s:
        created = create_project(
            s, user_id=alice_id, name="x", city="a", classification="b", zone="c",
        )
        s.commit()
        s.refresh(created)
        pid = created.id

    with Session(engine) as s:
        got = get_project(s, user_id=alice_id, project_id=pid)  # type: ignore[arg-type]
        assert got is not None
        assert got.name == "x"


def test_get_other_users_project_returns_none(
    engine: Engine, alice_id: int, bob_id: int
) -> None:
    """Cross-user isolation: Bob asking for Alice's project_id
    must get None — the route surfaces this as 404 to avoid leaking
    existence."""

    with Session(engine) as s:
        created = create_project(
            s, user_id=alice_id, name="alice-only", city="a", classification="b", zone="c",
        )
        s.commit()
        s.refresh(created)
        pid = created.id

    with Session(engine) as s:
        got = get_project(s, user_id=bob_id, project_id=pid)  # type: ignore[arg-type]
        assert got is None


def test_get_unknown_id_returns_none(engine: Engine, alice_id: int) -> None:
    with Session(engine) as s:
        assert get_project(s, user_id=alice_id, project_id=9999) is None


# ---- get_project_by_name -----------------------------------------------------


def test_get_by_name_returns_matching_row(engine: Engine, alice_id: int) -> None:
    with Session(engine) as s:
        create_project(
            s, user_id=alice_id, name="lookup-me", city="a", classification="b", zone="c",
        )
        s.commit()

    with Session(engine) as s:
        got = get_project_by_name(s, user_id=alice_id, name="lookup-me")
        assert got is not None
        assert got.user_id == alice_id


def test_get_by_name_other_user_returns_none(
    engine: Engine, alice_id: int, bob_id: int
) -> None:
    """get_by_name is the lookup half of the lazy create-or-get path —
    it must respect user-scope so two users with the same project
    name don't collide here."""

    with Session(engine) as s:
        create_project(
            s, user_id=alice_id, name="shared-name", city="a", classification="b", zone="c",
        )
        s.commit()

    with Session(engine) as s:
        bob_view = get_project_by_name(s, user_id=bob_id, name="shared-name")
        assert bob_view is None


def test_get_by_name_unknown_returns_none(engine: Engine, alice_id: int) -> None:
    with Session(engine) as s:
        assert get_project_by_name(s, user_id=alice_id, name="never-created") is None
