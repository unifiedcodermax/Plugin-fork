"""/history — persisted validation runs + regression diffs.

POST /history                 Evaluate, save, return ArchivalReport JSON.
GET  /history                 List my reports (paginated, filterable).
GET  /history/diff            Diff two reports by id (?from=X&to=Y).
GET  /history/{id}            Fetch one archive (JSON).
GET  /history/{id}/diff       Diff this report vs the most-recent
                              prior run with the same (city, classification,
                              zone) — "compare with my last save".
GET  /history/{id}/html       Re-render one archive as HTML.

Every read is user-scoped: a JWT user can never see another user's
report. The repository returns None for both "missing" and
"belongs to someone else"; this route translates both to 404 so
the response shape doesn't leak which case it was.

Route declaration order matters: /history/diff is registered BEFORE
/history/{id} so FastAPI doesn't try to parse "diff" as a UUID.
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
    get_prior_report,
    get_report,
    list_reports,
    save_report,
)
from planara_engine.reporting import (
    ArchivalReport,
    diff_reports,
    render_archive,
    render_diff_html,
    render_html,
)

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
    "/history/diff",
    summary="Diff two archived reports (JSON)",
)
def diff_history_explicit(
    user: CurrentUser,
    session: SessionDep,
    from_id: Annotated[UUID, Query(alias="from")],
    to_id: Annotated[UUID, Query(alias="to")],
) -> dict[str, Any]:
    """Diff ``from`` (baseline) against ``to`` (current).

    Both must belong to the calling user; either side missing
    surfaces as 404 — the route can't tell whether the report
    doesn't exist or just belongs to someone else, and shouldn't.
    """

    prev_row, curr_row = _load_diff_pair(session, user.id, from_id, to_id)  # type: ignore[arg-type]
    return _build_diff(prev_row, curr_row)


@router.get(
    "/history/diff/html",
    summary="Diff two archived reports (HTML)",
    response_model=None,
)
def diff_history_explicit_html(
    user: CurrentUser,
    session: SessionDep,
    from_id: Annotated[UUID, Query(alias="from")],
    to_id: Annotated[UUID, Query(alias="to")],
) -> HTMLResponse:
    prev_row, curr_row = _load_diff_pair(session, user.id, from_id, to_id)  # type: ignore[arg-type]
    return HTMLResponse(content=_build_diff_html(prev_row, curr_row), status_code=200)


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
    "/history/{report_id}/diff",
    summary="Diff one report against its most-recent prior (same context)",
)
def diff_history_vs_prior(
    report_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> dict[str, Any]:
    """Auto-diff: this report vs the previous run with matching
    (city, classification, zone) for the same user.

    Returns 404 when the report doesn't exist for this user, OR
    when no prior run exists for the same project context (a first
    save has nothing to compare against — that's the 'no prior'
    case the UI should surface as 'this is your baseline').
    """

    prev_row, curr_row = _load_prior_pair(session, user.id, report_id)  # type: ignore[arg-type]
    return _build_diff(prev_row, curr_row)


@router.get(
    "/history/{report_id}/diff/html",
    summary="Diff one report against its most-recent prior (HTML)",
    response_model=None,
)
def diff_history_vs_prior_html(
    report_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> HTMLResponse:
    prev_row, curr_row = _load_prior_pair(session, user.id, report_id)  # type: ignore[arg-type]
    return HTMLResponse(content=_build_diff_html(prev_row, curr_row), status_code=200)


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


def _build_diff(prev_row: Any, curr_row: Any) -> dict[str, Any]:
    """Load two stored payloads, parse, diff, serialize for JSON."""

    return _diff_pair(prev_row, curr_row).model_dump(mode="json")


def _build_diff_html(prev_row: Any, curr_row: Any) -> str:
    """Load two stored payloads, parse, diff, render to HTML."""

    return render_diff_html(_diff_pair(prev_row, curr_row))


def _diff_pair(prev_row: Any, curr_row: Any):
    prev_archive = ArchivalReport.model_validate_json(prev_row.payload)
    curr_archive = ArchivalReport.model_validate_json(curr_row.payload)
    return diff_reports(prev_archive, curr_archive)


def _load_diff_pair(
    session: Any, user_id: int, from_id: UUID, to_id: UUID
) -> tuple[Any, Any]:
    """Load two reports user-scoped. Either missing -> 404."""

    prev_row = get_report(session, user_id=user_id, report_id=from_id)
    if prev_row is None:
        raise NotFound(
            f"no report with id {from_id}",
            details={"report_id": str(from_id)},
        )
    curr_row = get_report(session, user_id=user_id, report_id=to_id)
    if curr_row is None:
        raise NotFound(
            f"no report with id {to_id}",
            details={"report_id": str(to_id)},
        )
    return prev_row, curr_row


def _load_prior_pair(
    session: Any, user_id: int, report_id: UUID
) -> tuple[Any, Any]:
    """Load (prior, curr) for the auto-diff endpoint."""

    curr_row = get_report(session, user_id=user_id, report_id=report_id)
    if curr_row is None:
        raise NotFound(
            f"no report with id {report_id}",
            details={"report_id": str(report_id)},
        )
    prev_row = get_prior_report(session, user_id=user_id, report_id=report_id)
    if prev_row is None:
        raise NotFound(
            "no prior report exists for this project context",
            details={
                "report_id": str(report_id),
                "city": curr_row.city,
                "classification": curr_row.classification,
                "zone": curr_row.zone,
            },
        )
    return prev_row, curr_row
