"""Unit tests for persistence.reports — save / list / get / count."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from planara_engine.domain import (
    Building,
    Floor,
    Plot,
    Polygon,
    ProjectContext,
    Severity,
    Snapshot,
    ValidationResponse,
    Violation,
)
from planara_engine.persistence.models import Project, User, ValidationReport
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
        project=ProjectContext(city=city, classification=classification, zone=zone),
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
        generated_at=ts or datetime.now(UTC),
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

    base = datetime(2026, 1, 1, tzinfo=UTC)
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
    base = datetime(2026, 1, 1, tzinfo=UTC)
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
    base = datetime(2026, 1, 1, tzinfo=UTC)
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
    base = datetime(2026, 1, 1, tzinfo=UTC)

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
    base = datetime(2026, 1, 1, tzinfo=UTC)
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
    base = datetime(2026, 1, 1, tzinfo=UTC)
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

    base = datetime(2026, 1, 1, tzinfo=UTC)
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

    base = datetime(2026, 1, 1, tzinfo=UTC)
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


# ---- project_id semantics ----------------------------------------------------
#
# A Project is the regression-tracking anchor: two distinct designs
# that share (city, classification, zone) can be kept in separate
# diff lanes by attaching them to different Project rows. Rows from
# older runs (or clients that don't pass one) leave project_id NULL
# and fall back to context-matching — this block exercises both
# lanes and the boundary between them.


def _project(session: Session, *, user_id: int, name: str, city: str = "Bangalore",
             classification: str = "CBD", zone: str = "Residential") -> Project:
    row = Project(
        user_id=user_id, name=name, city=city, classification=classification, zone=zone,
    )
    session.add(row)
    session.flush()
    return row


def test_save_with_project_id_persists_anchor(engine: Engine, alice_id: int) -> None:
    """save_report stores project_id verbatim. Source-of-truth check
    for the new column."""

    with Session(engine) as s:
        p = _project(s, user_id=alice_id, name="5th Main")
        s.commit()
        s.refresh(p)
        pid = p.id
        row = save_report(s, user_id=alice_id, archive=_archive(), project_id=pid)
        s.commit()
        s.refresh(row)
        assert row.project_id == pid


def test_save_without_project_id_leaves_null(engine: Engine, alice_id: int) -> None:
    """Backwards-compatibility: omitting project_id is allowed and
    leaves the legacy NULL lane intact."""

    with Session(engine) as s:
        row = save_report(s, user_id=alice_id, archive=_archive())
        s.commit()
        s.refresh(row)
        assert row.project_id is None


def test_get_prior_anchors_on_project_id_ignoring_context(
    engine: Engine, alice_id: int
) -> None:
    """When the target row has a project_id, prior is found by
    project_id alone — context drift within the same project (e.g.,
    a user changes the zone mid-design) must NOT break the lane."""

    base = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as s:
        p = _project(s, user_id=alice_id, name="downtown")
        s.commit()
        s.refresh(p)
        pid = p.id

        # First save: project_id set, original context.
        a = save_report(
            s,
            user_id=alice_id,
            archive=_archive(snap=_snap(zone="Residential"), ts=base),
            project_id=pid,
        )
        # Second save: same project, DIFFERENT zone — must still
        # be found as prior, because the anchor is project_id, not
        # (city, classification, zone).
        b = save_report(
            s,
            user_id=alice_id,
            archive=_archive(snap=_snap(zone="Commercial"), ts=base + timedelta(hours=1)),
            project_id=pid,
        )
        s.commit()
        a_id, b_id = a.report_id, b.report_id

    with Session(engine) as s:
        prior = get_prior_report(s, user_id=alice_id, report_id=b_id)
        assert prior is not None
        assert prior.report_id == a_id


def test_get_prior_project_anchored_returns_most_recent_in_project(
    engine: Engine, alice_id: int
) -> None:
    """Two different projects with identical context must NOT
    cross-contaminate each other's diff lane."""

    base = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as s:
        p1 = _project(s, user_id=alice_id, name="north plot")
        p2 = _project(s, user_id=alice_id, name="south plot")
        s.commit()
        s.refresh(p1)
        s.refresh(p2)

        # north has two earlier saves; south has one in between —
        # north's prior must NOT be south's row even though context
        # is identical.
        n1 = save_report(s, user_id=alice_id, archive=_archive(ts=base), project_id=p1.id)
        save_report(
            s,
            user_id=alice_id,
            archive=_archive(ts=base + timedelta(hours=1)),
            project_id=p2.id,
        )
        n2 = save_report(
            s,
            user_id=alice_id,
            archive=_archive(ts=base + timedelta(hours=2)),
            project_id=p1.id,
        )
        s.commit()
        n1_id, n2_id = n1.report_id, n2.report_id

    with Session(engine) as s:
        prior = get_prior_report(s, user_id=alice_id, report_id=n2_id)
        assert prior is not None
        assert prior.report_id == n1_id


def test_get_prior_legacy_lane_skips_project_anchored(
    engine: Engine, alice_id: int
) -> None:
    """A NULL-project row must NOT pair with a project-anchored row
    that shares the same context. The legacy lane stays isolated so
    a user adopting projects mid-stream doesn't suddenly see two
    histories collapse together."""

    base = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as s:
        p = _project(s, user_id=alice_id, name="adopted later")
        s.commit()
        s.refresh(p)

        # Old project-anchored save first (earliest).
        save_report(s, user_id=alice_id, archive=_archive(ts=base), project_id=p.id)
        # New legacy save second — same context, NULL project_id.
        legacy = save_report(
            s, user_id=alice_id, archive=_archive(ts=base + timedelta(hours=1))
        )
        s.commit()
        legacy_id = legacy.report_id

    with Session(engine) as s:
        prior = get_prior_report(s, user_id=alice_id, report_id=legacy_id)
        # The project-anchored row would otherwise match context;
        # restricting the legacy fallback to NULL keeps lanes apart.
        assert prior is None


def test_get_prior_project_anchored_skips_legacy_rows(
    engine: Engine, alice_id: int
) -> None:
    """Symmetric to the previous: a project-anchored row must NOT
    pair against legacy NULL rows even when context matches."""

    base = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as s:
        p = _project(s, user_id=alice_id, name="strict project")
        s.commit()
        s.refresh(p)

        # Two legacy saves first.
        save_report(s, user_id=alice_id, archive=_archive(ts=base))
        save_report(s, user_id=alice_id, archive=_archive(ts=base + timedelta(hours=1)))
        # Then the project-anchored save.
        anchored = save_report(
            s,
            user_id=alice_id,
            archive=_archive(ts=base + timedelta(hours=2)),
            project_id=p.id,
        )
        s.commit()
        anchored_id = anchored.report_id

    with Session(engine) as s:
        prior = get_prior_report(s, user_id=alice_id, report_id=anchored_id)
        assert prior is None


def test_list_and_count_filter_by_project_id(
    engine: Engine, alice_id: int
) -> None:
    """list_reports / count_reports narrow to one project's history
    when project_id is supplied."""

    base = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as s:
        p1 = _project(s, user_id=alice_id, name="p1")
        p2 = _project(s, user_id=alice_id, name="p2")
        s.commit()
        s.refresh(p1)
        s.refresh(p2)
        # Capture ids before the session closes — ORM instances
        # detach on session exit.
        p1_id, p2_id = p1.id, p2.id

        # 3 under p1, 2 under p2, 1 legacy.
        for i in range(3):
            save_report(
                s,
                user_id=alice_id,
                archive=_archive(ts=base + timedelta(hours=i)),
                project_id=p1_id,
            )
        for i in range(2):
            save_report(
                s,
                user_id=alice_id,
                archive=_archive(ts=base + timedelta(hours=10 + i)),
                project_id=p2_id,
            )
        save_report(s, user_id=alice_id, archive=_archive(ts=base + timedelta(hours=20)))
        s.commit()

    with Session(engine) as s:
        all_rows = list_reports(s, user_id=alice_id)
        assert len(all_rows) == 6
        assert count_reports(s, user_id=alice_id) == 6

        p1_rows = list_reports(s, user_id=alice_id, project_id=p1_id)
        assert len(p1_rows) == 3
        assert {r.project_id for r in p1_rows} == {p1_id}
        assert count_reports(s, user_id=alice_id, project_id=p1_id) == 3

        p2_rows = list_reports(s, user_id=alice_id, project_id=p2_id)
        assert len(p2_rows) == 2
        assert count_reports(s, user_id=alice_id, project_id=p2_id) == 2


def test_list_filter_combines_project_id_with_other_filters(
    engine: Engine, alice_id: int
) -> None:
    """project_id AND-combines with city/zone/ok like the existing
    filters — no special-casing."""

    base = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as s:
        p = _project(s, user_id=alice_id, name="multi-city")
        s.commit()
        s.refresh(p)

        save_report(
            s,
            user_id=alice_id,
            archive=_archive(snap=_snap(city="Bangalore"), ts=base),
            project_id=p.id,
        )
        save_report(
            s,
            user_id=alice_id,
            archive=_archive(
                snap=_snap(city="Mumbai", classification="Island"),
                ts=base + timedelta(hours=1),
            ),
            project_id=p.id,
        )
        s.commit()
        pid = p.id

    with Session(engine) as s:
        mum = list_reports(s, user_id=alice_id, project_id=pid, city="Mumbai")
        assert len(mum) == 1
        assert mum[0].city == "Mumbai"
        assert count_reports(s, user_id=alice_id, project_id=pid, city="Mumbai") == 1
