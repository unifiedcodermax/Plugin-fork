"""Unit tests for persistence.reports — save / list / get / count."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from planara_engine.domain import (
    Building,
    Floor,
    Plot,
    Polygon,
    Project,
    Severity,
    Snapshot,
    ValidationResponse,
    Violation,
)
from planara_engine.persistence.models import User, ValidationReport
from planara_engine.persistence.reports import (
    count_reports,
    get_prior_report,
    get_report,
    list_reports,
    save_report,
)
from planara_engine.reporting import render_archive


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


def _square(size: float, ox: float = 0.0, oy: float = 0.0) -> Polygon:
    return Polygon(
        exterior=[[ox, oy], [ox + size, oy], [ox + size, oy + size], [ox, oy + size]]
    )


def _snap(city: str = "Bangalore", classification: str = "CBD", zone: str = "Residential") -> Snapshot:
    return Snapshot(
        project=Project(city=city, classification=classification, zone=zone),
        plot=Plot(polygon=_square(50.0)),
        building=Building(
            floors=[Floor(level=0, polygon=_square(10.0, 20.0, 20.0), height_m=3.0)],
            parking_slots_provided=2,
        ),
    )


def _resp(*violations: Violation, ok: bool | None = None, pack_version: str = "0.3.0") -> ValidationResponse:
    return ValidationResponse(
        snapshot_id=uuid4(),
        ok=ok if ok is not None else not any(v.severity == Severity.error for v in violations),
        violations=list(violations),
        metrics={"rule_pack_version": pack_version, "rule_count": 5},
    )


def _archive(snap: Snapshot | None = None, resp: ValidationResponse | None = None, ts: datetime | None = None):
    return render_archive(
        snap or _snap(),
        resp or _resp(),
        generated_at=ts or datetime.now(timezone.utc),
    )


# ---- save_report -------------------------------------------------------------


def test_save_report_denormalizes_summary(engine: Engine, alice_id: int) -> None:
    arch = _archive()
    with Session(engine) as s:
        row = save_report(s, user_id=alice_id, archive=arch)
        s.commit()
        s.refresh(row)

        assert row.report_id == arch.report_id
        assert row.user_id == alice_id
        assert row.snapshot_id == arch.snapshot.snapshot_id
        assert row.city == "Bangalore"
        assert row.classification == "CBD"
        assert row.zone == "Residential"
        assert row.ok is True
        assert row.violation_count == 0
        assert row.error_count == 0
        assert row.warning_count == 0
        assert row.rule_pack_version == "0.3.0"


def test_save_report_counts_by_severity(engine: Engine, alice_id: int) -> None:
    vs = [
        Violation(rule_id="t.a", category="fsi", severity=Severity.error, message="x"),
        Violation(rule_id="t.b", category="fsi", severity=Severity.error, message="x"),
        Violation(rule_id="t.c", category="setback", severity=Severity.warning, message="x"),
    ]
    resp = _resp(*vs, ok=False)
    with Session(engine) as s:
        row = save_report(s, user_id=alice_id, archive=_archive(resp=resp))
        s.commit()
        s.refresh(row)

        assert row.violation_count == 3
        assert row.error_count == 2
        assert row.warning_count == 1
        assert row.ok is False


def test_save_report_payload_round_trips(engine: Engine, alice_id: int) -> None:
    """payload is the source of truth — saving and reading back must
    give us the same archive we passed in."""

    arch = _archive()
    with Session(engine) as s:
        row = save_report(s, user_id=alice_id, archive=arch)
        s.commit()
        s.refresh(row)

        parsed = json.loads(row.payload)
        assert parsed["report_id"] == str(arch.report_id)
        assert parsed["snapshot"]["project"]["city"] == "Bangalore"


# ---- list_reports ------------------------------------------------------------


def _save_n(session: Session, user_id: int, n: int, *, base_ts: datetime, snap_factory=None) -> list[ValidationReport]:
    out = []
    for i in range(n):
        snap = (snap_factory or (lambda i=i: _snap()))(i) if snap_factory else _snap()
        arch = _archive(snap=snap, ts=base_ts + timedelta(hours=i))
        out.append(save_report(session, user_id=user_id, archive=arch))
    session.commit()
    return out


def test_list_returns_user_scoped_only(engine: Engine, alice_id: int, bob_id: int) -> None:
    """Bob's saves must not appear in Alice's list."""

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Session(engine) as s:
        _save_n(s, alice_id, 3, base_ts=base)
        _save_n(s, bob_id, 5, base_ts=base)

    with Session(engine) as s:
        alice_rows = list_reports(s, user_id=alice_id)
        bob_rows = list_reports(s, user_id=bob_id)
        assert len(alice_rows) == 3
        assert len(bob_rows) == 5
        for r in alice_rows:
            assert r.user_id == alice_id


def test_list_orders_recent_first(engine: Engine, alice_id: int) -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Session(engine) as s:
        rows = _save_n(s, alice_id, 4, base_ts=base)
        # Capture timestamps inside the session — SQLAlchemy detaches
        # row instances when the session closes.
        earliest_ts = rows[0].generated_at
        latest_ts = rows[3].generated_at

    with Session(engine) as s:
        got = list_reports(s, user_id=alice_id)
        # rows[3] has the latest timestamp (base + 3h); should be first.
        assert got[0].generated_at == latest_ts
        assert got[-1].generated_at == earliest_ts


def test_list_paginates(engine: Engine, alice_id: int) -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Session(engine) as s:
        _save_n(s, alice_id, 25, base_ts=base)

    with Session(engine) as s:
        page1 = list_reports(s, user_id=alice_id, limit=10, offset=0)
        page2 = list_reports(s, user_id=alice_id, limit=10, offset=10)
        page3 = list_reports(s, user_id=alice_id, limit=10, offset=20)
        assert len(page1) == 10
        assert len(page2) == 10
        assert len(page3) == 5
        # No overlap across pages.
        ids = {r.report_id for r in page1} | {r.report_id for r in page2} | {r.report_id for r in page3}
        assert len(ids) == 25


def test_list_filters_combine_with_and(engine: Engine, alice_id: int) -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def factory(i: int) -> Snapshot:
        if i % 2 == 0:
            return _snap(city="Bangalore", zone="Residential")
        return _snap(city="Mumbai", classification="Island", zone="Commercial")

    with Session(engine) as s:
        _save_n(s, alice_id, 6, base_ts=base, snap_factory=factory)

    with Session(engine) as s:
        mum_only = list_reports(s, user_id=alice_id, city="Mumbai")
        assert len(mum_only) == 3
        for r in mum_only:
            assert r.city == "Mumbai"

        mum_comm = list_reports(s, user_id=alice_id, city="Mumbai", zone="Commercial")
        assert len(mum_comm) == 3

        # No match — Mumbai Residential doesn't exist in this fixture.
        none = list_reports(s, user_id=alice_id, city="Mumbai", zone="Residential")
        assert none == []


def test_list_filters_by_ok(engine: Engine, alice_id: int) -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Session(engine) as s:
        # Two passing, one failing.
        save_report(s, user_id=alice_id, archive=_archive(ts=base))
        save_report(s, user_id=alice_id, archive=_archive(ts=base + timedelta(hours=1)))
        fail = _resp(
            Violation(rule_id="t.x", category="fsi", severity=Severity.error, message="m"),
            ok=False,
        )
        save_report(s, user_id=alice_id, archive=_archive(resp=fail, ts=base + timedelta(hours=2)))
        s.commit()

        passing = list_reports(s, user_id=alice_id, ok=True)
        failing = list_reports(s, user_id=alice_id, ok=False)
        assert len(passing) == 2
        assert len(failing) == 1


# ---- count_reports -----------------------------------------------------------


def test_count_matches_filters(engine: Engine, alice_id: int, bob_id: int) -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Session(engine) as s:
        _save_n(s, alice_id, 7, base_ts=base)
        _save_n(s, bob_id, 3, base_ts=base)

    with Session(engine) as s:
        assert count_reports(s, user_id=alice_id) == 7
        assert count_reports(s, user_id=bob_id) == 3
        assert count_reports(s, user_id=alice_id, city="Mumbai") == 0


# ---- get_report --------------------------------------------------------------


def test_get_report_returns_own_row(engine: Engine, alice_id: int) -> None:
    arch = _archive()
    with Session(engine) as s:
        save_report(s, user_id=alice_id, archive=arch)
        s.commit()

    with Session(engine) as s:
        got = get_report(s, user_id=alice_id, report_id=arch.report_id)
        assert got is not None
        assert got.report_id == arch.report_id


def test_get_report_returns_none_for_other_user(engine: Engine, alice_id: int, bob_id: int) -> None:
    """User-scope isolation: Bob asking for Alice's report must NOT
    see it. The repo returns None so the route can surface a 404 —
    differentiating "exists elsewhere" from "doesn't exist" would
    leak the existence of other users' reports."""

    arch = _archive()
    with Session(engine) as s:
        save_report(s, user_id=alice_id, archive=arch)
        s.commit()

    with Session(engine) as s:
        got = get_report(s, user_id=bob_id, report_id=arch.report_id)
        assert got is None


def test_get_report_returns_none_for_unknown_id(engine: Engine, alice_id: int) -> None:
    with Session(engine) as s:
        got = get_report(s, user_id=alice_id, report_id=UUID(int=0))
        assert got is None


# ---- get_prior_report --------------------------------------------------------


def test_get_prior_returns_most_recent_earlier_match(engine: Engine, alice_id: int) -> None:
    """Same (city, classification, zone), earliest timestamp before
    target. Different contexts must be skipped."""

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Session(engine) as s:
        a = save_report(s, user_id=alice_id, archive=_archive(snap=_snap(city="Bangalore", zone="Residential"), ts=base))
        # Different city — skip when looking for prior of a Bangalore.
        save_report(s, user_id=alice_id, archive=_archive(snap=_snap(city="Mumbai", classification="Island", zone="Residential"), ts=base + timedelta(hours=1)))
        b = save_report(s, user_id=alice_id, archive=_archive(snap=_snap(city="Bangalore", zone="Residential"), ts=base + timedelta(hours=2)))
        c = save_report(s, user_id=alice_id, archive=_archive(snap=_snap(city="Bangalore", zone="Residential"), ts=base + timedelta(hours=3)))
        s.commit()
        # Capture IDs before session close.
        a_id, b_id, c_id = a.report_id, b.report_id, c.report_id

    with Session(engine) as s:
        prior_of_c = get_prior_report(s, user_id=alice_id, report_id=c_id)
        assert prior_of_c is not None
        assert prior_of_c.report_id == b_id

        prior_of_b = get_prior_report(s, user_id=alice_id, report_id=b_id)
        assert prior_of_b is not None
        assert prior_of_b.report_id == a_id

        prior_of_a = get_prior_report(s, user_id=alice_id, report_id=a_id)
        assert prior_of_a is None


def test_get_prior_other_user_returns_none(engine: Engine, alice_id: int, bob_id: int) -> None:
    """Cross-user isolation: Bob's prior reports must not surface
    when Alice asks for prior of Alice's report."""

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Session(engine) as s:
        # Bob has earlier runs in the same context; they MUST NOT
        # be returned as Alice's prior.
        save_report(s, user_id=bob_id, archive=_archive(ts=base))
        save_report(s, user_id=bob_id, archive=_archive(ts=base + timedelta(hours=1)))
        a = save_report(s, user_id=alice_id, archive=_archive(ts=base + timedelta(hours=2)))
        s.commit()
        a_id = a.report_id

    with Session(engine) as s:
        prior = get_prior_report(s, user_id=alice_id, report_id=a_id)
        assert prior is None


def test_get_prior_unknown_id_returns_none(engine: Engine, alice_id: int) -> None:
    with Session(engine) as s:
        prior = get_prior_report(s, user_id=alice_id, report_id=UUID(int=0))
        assert prior is None
