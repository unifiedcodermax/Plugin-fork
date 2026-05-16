"""Unit tests for the ValidationReport SQLModel table.

Uses an in-memory SQLite per test so the schema work is isolated
from the global engine cache. Asserts the storage shape and the
index existence — index correctness is what makes the "show my
recent runs" query cheap as the table grows.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine, select

from planara_engine.persistence.models import User, ValidationReport


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def user_id(engine: Engine) -> int:
    with Session(engine) as s:
        u = User(username="tester", password_hash="x")
        s.add(u)
        s.commit()
        s.refresh(u)
        assert u.id is not None
        return u.id


def _row(user_id: int, **overrides) -> ValidationReport:
    defaults = dict(
        user_id=user_id,
        snapshot_id=uuid4(),
        city="Bangalore",
        classification="CBD",
        zone="Residential",
        ok=True,
        violation_count=0,
        error_count=0,
        warning_count=0,
        rule_pack_version="0.3.0",
        generated_at=datetime.now(timezone.utc),
        payload="{}",
    )
    defaults.update(overrides)
    return ValidationReport(**defaults)


def test_insert_and_fetch(engine: Engine, user_id: int) -> None:
    with Session(engine) as s:
        r = _row(user_id)
        s.add(r)
        s.commit()
        s.refresh(r)
        assert isinstance(r.report_id, UUID)

    with Session(engine) as s:
        got = s.get(ValidationReport, r.report_id)
        assert got is not None
        assert got.user_id == user_id
        assert got.city == "Bangalore"


def test_report_id_unique_pk(engine: Engine, user_id: int) -> None:
    """Two rows with the same report_id must fail on insert. Pins
    the pk constraint so an accidental schema change can't silently
    break it."""

    rid = uuid4()
    with Session(engine) as s:
        s.add(_row(user_id, report_id=rid))
        s.commit()

    with Session(engine) as s:
        s.add(_row(user_id, report_id=rid))
        with pytest.raises(Exception):
            s.commit()


def test_user_id_required(engine: Engine) -> None:
    """user_id is a FK and must be present — there is no concept of
    'anonymous reports' in the current schema."""

    with Session(engine) as s:
        # Pydantic-level validation catches missing required fields
        # before they reach the DB. Either way: this must raise.
        with pytest.raises(Exception):
            s.add(ValidationReport(
                user_id=None,  # type: ignore[arg-type]
                snapshot_id=uuid4(),
                city="Bangalore",
                classification="CBD",
                zone="Residential",
                ok=True,
                violation_count=0,
                error_count=0,
                warning_count=0,
                rule_pack_version="0.3.0",
                generated_at=datetime.now(timezone.utc),
                payload="{}",
            ))
            s.commit()


def test_payload_round_trips_json_text(engine: Engine, user_id: int) -> None:
    """The payload column is TEXT — Pydantic-encoded JSON in, same
    string out. No DB-side parsing or normalization."""

    payload = '{"report_id":"x","snapshot":{"k":"v\\u00e9"}}'
    with Session(engine) as s:
        s.add(_row(user_id, payload=payload))
        s.commit()

    with Session(engine) as s:
        got = s.exec(select(ValidationReport)).one()
        assert got.payload == payload


def test_indexes_declared(engine: Engine) -> None:
    """Pin that the composite indexes exist. A future field rename
    that loses an index would tank list-history queries — this test
    catches that before the table grows."""

    inspector = inspect(engine)
    index_names = {idx["name"] for idx in inspector.get_indexes("validation_reports")}
    assert "ix_history_user_generated" in index_names
    assert "ix_history_city_zone" in index_names


def test_negative_counts_accepted_at_db_layer(engine: Engine, user_id: int) -> None:
    """SQLModel table classes skip Pydantic validators on construction —
    the ge=0 field constraint is annotation-only. Documenting this so
    a future reader doesn't trust the DB to police it. The repository
    layer (S9.2) and the route handler must validate non-negativity
    before save."""

    with Session(engine) as s:
        s.add(_row(user_id, violation_count=-1))
        s.commit()  # SQLite has no CHECK constraint here.
