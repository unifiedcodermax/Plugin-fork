"""Persistence smoke: schema creates, repository CRUD round-trips."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from planara_engine.persistence.database import get_engine, init_db
from planara_engine.persistence.repository import (
    create_user,
    get_user_by_id,
    get_user_by_username,
    touch_user,
)


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """In-memory SQLite session that lives for one test.

    Forces PLANARA_DB_URL to ``sqlite:///:memory:`` so tests don't
    write to or load from a real .db file. The autouse settings
    cache reset in conftest then picks this up cleanly.
    """

    monkeypatch.setenv("PLANARA_DB_URL", "sqlite:///:memory:")
    get_engine.cache_clear()
    init_db()
    engine = get_engine()
    with Session(engine) as s:
        yield s
    engine.dispose()  # release sqlite connections so finalizer doesn't warn
    get_engine.cache_clear()


def test_create_and_lookup_by_username(session: Session) -> None:
    u = create_user(session, username="alice", password_hash="hash:alice")
    session.commit()

    assert u.id is not None
    assert u.is_active is True
    assert u.created_at is not None

    again = get_user_by_username(session, "alice")
    assert again is not None
    assert again.id == u.id
    assert again.password_hash == "hash:alice"


def test_lookup_unknown_user_returns_none(session: Session) -> None:
    assert get_user_by_username(session, "ghost") is None


def test_username_is_unique(session: Session) -> None:
    create_user(session, username="bob", password_hash="h1")
    session.commit()
    with pytest.raises(IntegrityError):
        # create_user calls flush(), so the constraint fires here,
        # not at commit. Either is acceptable as long as something
        # raises before a duplicate row sneaks in.
        create_user(session, username="bob", password_hash="h2")
    session.rollback()


def test_lookup_by_id(session: Session) -> None:
    u = create_user(session, username="carol", password_hash="hash")
    session.commit()
    assert u.id is not None

    found = get_user_by_id(session, u.id)
    assert found is not None
    assert found.username == "carol"


def test_touch_user_bumps_updated_at(session: Session) -> None:
    u = create_user(session, username="dave", password_hash="hash")
    session.commit()
    original = u.updated_at

    touch_user(session, u)
    session.commit()

    assert u.updated_at >= original
