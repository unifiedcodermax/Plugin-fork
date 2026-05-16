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
) -> ValidationReport:
    """Persist an ArchivalReport for ``user_id``. Returns the saved row.

    Denormalizes the summary fields (counts, city, etc.) into indexed
    columns so list queries don't need to JSON-parse every row. The
    archive itself is stored verbatim in ``payload`` — that's the
    source of truth for re-rendering and Sprint 10 diffing.

    Caller is responsible for ``session.commit()``.
    """

    violations = archive.response.violations
    error_count = sum(1 for v in violations if v.severity == Severity.error)
    warning_count = sum(1 for v in violations if v.severity == Severity.warning)

    row = ValidationReport(
        report_id=archive.report_id,
        user_id=user_id,
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
    city: str | None = None,
    classification: str | None = None,
    zone: str | None = None,
    ok: bool | None = None,
) -> list[ValidationReport]:
    """Most-recent-first list of a user's reports.

    Filters are AND-combined. limit/offset are pagination; the route
    layer enforces bounds (the repo accepts whatever it's given).
    """

    stmt = select(ValidationReport).where(ValidationReport.user_id == user_id)
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
