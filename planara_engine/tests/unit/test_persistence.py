"""Persistence smoke: schema creates, repository CRUD round-trips."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from planara_engine.persistence.database import get_engine, init_db
from planara_engine.persistence.models import User
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


def test_init_db_seeds_default_user_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    # Use a clean, isolated in-memory DB URL
    monkeypatch.setenv("PLANARA_DB_URL", "sqlite:///:memory:")
    get_engine.cache_clear()

    # On first init_db, it should seed the 'admin' user
    init_db()

    engine = get_engine()
    with Session(engine) as s:
        admin = get_user_by_username(s, "admin")
        assert admin is not None
        assert admin.username == "admin"
        # Verify it has active status
        assert admin.is_active is True

        # Count total users
        users = s.exec(select(User)).all()
        assert len(users) == 1

    # Call init_db again to ensure it is idempotent (does not duplicate 'admin')
    init_db()
    with Session(engine) as s:
        users = s.exec(select(User)).all()
        assert len(users) == 1

    engine.dispose()
    get_engine.cache_clear()


def test_init_db_does_not_seed_if_users_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLANARA_DB_URL", "sqlite:///:memory:")
    get_engine.cache_clear()

    # First initialize the database tables
    init_db()

    engine = get_engine()
    # Now manually delete the 'admin' user and add a custom user
    with Session(engine) as s:
        admin = get_user_by_username(s, "admin")
        if admin:
            s.delete(admin)
        create_user(s, username="custom_user", password_hash="somehash")
        s.commit()

    # Call init_db again - since a user exists (custom_user), it should NOT seed 'admin'
    init_db()

    with Session(engine) as s:
        admin = get_user_by_username(s, "admin")
        assert admin is None

        # There should only be the custom user
        users = s.exec(select(User)).all()
        assert len(users) == 1
        assert users[0].username == "custom_user"

    engine.dispose()
    get_engine.cache_clear()

