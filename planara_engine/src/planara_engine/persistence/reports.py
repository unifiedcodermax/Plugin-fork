"""Repository for ValidationReport rows.

Sibling to ``repository.py`` (which deals with User). Each function
takes an explicit ``Session`` so callers control transaction scope.
All queries are scoped by ``user_id`` — a user must never read
another user's history through these helpers.
"""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, col, select

from planara_engine.domain import Severity
from planara_engine.persistence.models import ValidationReport
from planara_engine.reporting import ArchivalReport


def save_report(
    session: Session,
    *,
    user_id: int,
    archive: ArchivalReport,
    project_id: int | None = None,
) -> ValidationReport:
    """Persist an ArchivalReport for ``user_id``. Returns the saved row.

    Denormalizes the summary fields (counts, city, etc.) into indexed
    columns so list queries don't need to JSON-parse every row. The
    archive itself is stored verbatim in ``payload`` — that's the
    source of truth for re-rendering and Sprint 10 diffing.

    ``project_id`` is optional: when present, the row is anchored to a
    user-named project so auto-diff can pair runs across distinct
    designs that share (city, classification, zone). When absent, the
    row stays in the legacy NULL lane and auto-diff falls back to
    context-matching. The caller is responsible for verifying the
    project belongs to ``user_id`` — this repo trusts what it's given.

    Caller is responsible for ``session.commit()``.
    """

    violations = archive.response.violations
    error_count = sum(1 for v in violations if v.severity == Severity.error)
    warning_count = sum(1 for v in violations if v.severity == Severity.warning)

    row = ValidationReport(
        report_id=archive.report_id,
        user_id=user_id,
        project_id=project_id,
        snapshot_id=archive.snapshot.snapshot_id,
        city=archive.snapshot.project.city,
        classification=archive.snapshot.project.classification,
        zone=archive.snapshot.project.zone,
        ok=archive.response.ok,
        violation_count=len(violations),
        error_count=error_count,
        warning_count=warning_count,
        rule_pack_version=str(
            archive.response.metrics.get("rule_pack_version", "")
        ),
        generated_at=archive.generated_at,
        payload=archive.model_dump_json(),
    )
    session.add(row)
    session.flush()
    return row


def list_reports(
    session: Session,
    *,
    user_id: int,
    limit: int = 20,
    offset: int = 0,
    project_id: int | None = None,
    city: str | None = None,
    classification: str | None = None,
    zone: str | None = None,
    ok: bool | None = None,
) -> list[ValidationReport]:
    """Most-recent-first list of a user's reports.

    Filters are AND-combined. ``project_id`` narrows to one project's
    history (the project picker uses this). limit/offset are
    pagination; the route layer enforces bounds (the repo accepts
    whatever it's given).
    """

    stmt = select(ValidationReport).where(ValidationReport.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(ValidationReport.project_id == project_id)
    if city is not None:
        stmt = stmt.where(ValidationReport.city == city)
    if classification is not None:
        stmt = stmt.where(ValidationReport.classification == classification)
    if zone is not None:
        stmt = stmt.where(ValidationReport.zone == zone)
    if ok is not None:
        stmt = stmt.where(ValidationReport.ok == ok)

    stmt = stmt.order_by(col(ValidationReport.generated_at).desc()).limit(limit).offset(offset)
    return list(session.exec(stmt).all())


def count_reports(
    session: Session,
    *,
    user_id: int,
    project_id: int | None = None,
    city: str | None = None,
    classification: str | None = None,
    zone: str | None = None,
    ok: bool | None = None,
) -> int:
    """Count of rows matching the same filters as ``list_reports``.

    Surfaced for paginated list endpoints (total + page). Counting
    via len(list_reports(...)) would force loading every match.
    """

    # SQLModel doesn't expose a clean count() builder; round-trip
    # through a select(...) and len. The dataset stays small for the
    # MVP, so this is fine. Migrate to func.count() when it bites.
    stmt = select(ValidationReport.report_id).where(ValidationReport.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(ValidationReport.project_id == project_id)
    if city is not None:
        stmt = stmt.where(ValidationReport.city == city)
    if classification is not None:
        stmt = stmt.where(ValidationReport.classification == classification)
    if zone is not None:
        stmt = stmt.where(ValidationReport.zone == zone)
    if ok is not None:
        stmt = stmt.where(ValidationReport.ok == ok)
    return len(list(session.exec(stmt).all()))


def get_report(
    session: Session,
    *,
    user_id: int,
    report_id: UUID,
) -> ValidationReport | None:
    """Fetch one report, scoped to ``user_id``.

    Returns None for "doesn't exist" AND for "exists but belongs to
    another user". Routes must surface both as 404; differentiating
    would leak the existence of other users' reports.
    """

    stmt = select(ValidationReport).where(
        ValidationReport.report_id == report_id,
        ValidationReport.user_id == user_id,
    )
    return session.exec(stmt).first()


def get_prior_report(
    session: Session,
    *,
    user_id: int,
    report_id: UUID,
) -> ValidationReport | None:
    """Return the most recent earlier report by the same user that
    shares a regression-tracking anchor with ``report_id``.

    Anchor selection:
      * When the target row has a ``project_id``, prior is the most
        recent earlier row with the SAME ``project_id``. Context
        (city/classification/zone) is ignored here so a user can
        legitimately re-zone a project mid-design without breaking
        the diff lane.
      * When the target row has NO ``project_id`` (legacy / plugin
        not passing one), fall back to the most recent earlier row
        with matching (city, classification, zone) AND a NULL
        ``project_id``. Restricting the fallback to NULL keeps the
        legacy lane from accidentally pairing with project-anchored
        rows once a user starts using projects.

    Returns None when:
      * report_id doesn't exist (or belongs to another user),
      * report_id exists but has no earlier run on its anchor.
    """

    target = get_report(session, user_id=user_id, report_id=report_id)
    if target is None:
        return None

    stmt = (
        select(ValidationReport)
        .where(
            ValidationReport.user_id == user_id,
            ValidationReport.generated_at < target.generated_at,
        )
    )
    if target.project_id is not None:
        stmt = stmt.where(ValidationReport.project_id == target.project_id)
    else:
        stmt = stmt.where(
            ValidationReport.project_id.is_(None),  # type: ignore[union-attr]
            ValidationReport.city == target.city,
            ValidationReport.classification == target.classification,
            ValidationReport.zone == target.zone,
        )

    stmt = stmt.order_by(col(ValidationReport.generated_at).desc()).limit(1)
    return session.exec(stmt).first()
