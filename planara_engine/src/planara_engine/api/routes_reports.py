"""POST /reports — human-readable compliance report.

Same Snapshot input as /validate. The server re-runs evaluate
itself rather than accepting a client-supplied response, so the
report can never be fabricated from outside the engine.

Content-Type negotiation via Accept header:
  - text/html (or */*, default)  -> rendered HTML document
  - application/json             -> ArchivalReport JSON

Anything else returns 406.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, status
from fastapi.responses import HTMLResponse, JSONResponse

from planara_engine.auth.deps import CurrentUser
from planara_engine.core.errors import ValidationFailed
from planara_engine.core.logging import get_logger
from planara_engine.domain import Snapshot
from planara_engine.engine import evaluate
from planara_engine.reporting import render_archive, render_html

router = APIRouter(tags=["reports"])
log = get_logger("planara.api.reports")

_HTML = "text/html"
_JSON = "application/json"


@router.post(
    "/reports",
    status_code=status.HTTP_200_OK,
    summary="Render a human-readable compliance report for a snapshot",
    response_model=None,
    responses={
        200: {
            "content": {
                _HTML: {"schema": {"type": "string"}},
                _JSON: {"schema": {"$ref": "#/components/schemas/ArchivalReport"}},
            }
        }
    },
)
def render_report(
    snapshot: Snapshot,
    user: CurrentUser,
    accept: str | None = Header(default=None),
) -> HTMLResponse | JSONResponse:
    response = evaluate(snapshot)
    fmt = _choose_format(accept)

    log.info(
        "report_rendered",
        user=user.username,
        snapshot_id=str(snapshot.snapshot_id),
        format=fmt,
        ok=response.ok,
        violation_count=len(response.violations),
    )

    if fmt == _HTML:
        return HTMLResponse(content=render_html(snapshot, response), status_code=200)
    return JSONResponse(
        content=render_archive(snapshot, response).model_dump(mode="json"),
        status_code=200,
    )


def _choose_format(accept: str | None) -> str:
    """Coarse Accept-header parser.

    HTML is the default — clients that send no header or */* get
    HTML, which matches the user-facing default (a browser will
    show it). JSON is opt-in via an explicit application/json
    preference. Unknown explicit types raise — better to fail
    than to silently fall back to HTML when a script asked for
    application/pdf.
    """

    if not accept:
        return _HTML
    types = [t.strip().split(";", 1)[0] for t in accept.split(",")]
    if any(t == _HTML or t == "*/*" or t == "text/*" for t in types):
        return _HTML
    if any(t == _JSON or t == "application/*" for t in types):
        return _JSON
    raise ValidationFailed(
        f"Accept header {accept!r} not supported; use text/html or application/json",
        details={"accept": accept, "supported": [_HTML, _JSON]},
    )
