"""/history — persisted validation runs.

POST /history             Evaluate, save, return ArchivalReport JSON.
GET  /history             List my reports (paginated, filterable).
GET  /history/{id}        Fetch one archive (JSON).
GET  /history/{id}/html   Re-render one archive as HTML.

Every read is user-scoped: a JWT user can never see another user's
report. The repository returns None for both "missing" and
"belongs to someone else"; this route translates both to 404 so
the response shape doesn't leak which case it was.
"""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import HTMLResponse, JSONResponse

from planara_engine.auth.deps import CurrentUser, SessionDep
from planara_engine.core.errors import NotFound
from planara_engine.core.logging import get_logger
from planara_engine.domain import Snapshot
from planara_engine.engine import evaluate
from planara_engine.persistence.reports import (
    count_reports,
    get_report,
    list_reports,
    save_report,
)
from planara_engine.reporting import ArchivalReport, render_archive, render_html

router = APIRouter(tags=["history"])
log = get_logger("planara.api.history")

# Cap pagination so a misbehaving client can't request 1M rows in
# one shot. 100 is generous for the live editor; cloud UIs can
# paginate normally.
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 20


@router.post(
    "/history",
    status_code=status.HTTP_201_CREATED,
    summary="Validate a snapshot and persist the resulting archive",
    response_model=None,
)
def save_history(
    snapshot: Snapshot,
    user: CurrentUser,
    session: SessionDep,
) -> JSONResponse:
    """Run /validate's engine internally, archive the result, persist."""

    response = evaluate(snapshot)
    archive = render_archive(snapshot, response)
    row = save_report(session, user_id=user.id, archive=archive)  # type: ignore[arg-type]

    log.info(
        "history_saved",
        user=user.username,
        report_id=str(row.report_id),
        snapshot_id=str(snapshot.snapshot_id),
        ok=response.ok,
        violation_count=len(response.violations),
    )

    return JSONResponse(
        content=archive.model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED,
    )


@router.get(
    "/history",
    summary="List my recent validation runs",
)
def list_history(
    user: CurrentUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = _DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
    city: str | None = None,
    classification: str | None = None,
    zone: str | None = None,
    ok: bool | None = None,
) -> dict[str, Any]:
    """Return a page of summary rows, most-recent-first.

    The list intentionally omits the full payload — that would
    balloon the response. Clients that need the archive fetch by
    report_id.
    """

    rows = list_reports(
        session,
        user_id=user.id,  # type: ignore[arg-type]
        limit=limit,
        offset=offset,
        city=city,
        classification=classification,
        zone=zone,
        ok=ok,
    )
    total = count_reports(
        session,
        user_id=user.id,  # type: ignore[arg-type]
        city=city,
        classification=classification,
        zone=zone,
        ok=ok,
    )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_summary(r) for r in rows],
    }


@router.get(
    "/history/{report_id}",
    summary="Fetch one archived report (JSON)",
    response_model=None,
)
def get_history(
    report_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> JSONResponse:
    row = get_report(session, user_id=user.id, report_id=report_id)  # type: ignore[arg-type]
    if row is None:
        raise NotFound(
            f"no report with id {report_id}",
            details={"report_id": str(report_id)},
        )

    # payload is the source of truth — return what we stored, not
    # a freshly-rendered archive (the engine state may have moved on
    # since the row was written).
    return JSONResponse(content=json.loads(row.payload))


@router.get(
    "/history/{report_id}/html",
    summary="Re-render one archived report as HTML",
    response_model=None,
)
def get_history_html(
    report_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> HTMLResponse:
    row = get_report(session, user_id=user.id, report_id=report_id)  # type: ignore[arg-type]
    if row is None:
        raise NotFound(
            f"no report with id {report_id}",
            details={"report_id": str(report_id)},
        )

    archive = ArchivalReport.model_validate_json(row.payload)
    html = render_html(
        archive.snapshot,
        archive.response,
        generated_at=archive.generated_at,
    )
    return HTMLResponse(content=html, status_code=200)


# ---- helpers -----------------------------------------------------------------


def _summary(row: Any) -> dict[str, Any]:
    """Slim summary for the list view. Omits payload."""

    return {
        "report_id": str(row.report_id),
        "snapshot_id": str(row.snapshot_id),
        "city": row.city,
        "classification": row.classification,
        "zone": row.zone,
        "ok": row.ok,
        "violation_count": row.violation_count,
        "error_count": row.error_count,
        "warning_count": row.warning_count,
        "rule_pack_version": row.rule_pack_version,
        "generated_at": row.generated_at.isoformat(),
    }
