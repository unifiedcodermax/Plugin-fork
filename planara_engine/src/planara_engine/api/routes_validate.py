"""POST /validate — the main compliance endpoint.

Auth required. Plugin posts a Snapshot, gets a ValidationResponse
back. The route is a thin shim over engine.evaluate; all the
business logic is in the engine layer.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from planara_engine.auth.deps import CurrentUser
from planara_engine.core.logging import get_logger
from planara_engine.domain import Snapshot, ValidationResponse
from planara_engine.domain.snapshot import CURRENT_SCHEMA_VERSION
from planara_engine.engine import evaluate

router = APIRouter(tags=["validate"])
log = get_logger("planara.api.validate")


@router.post(
    "/validate",
    response_model=ValidationResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate a building snapshot against the relevant rule pack",
)
def validate(snapshot: Snapshot, user: CurrentUser) -> ValidationResponse:
    if snapshot.schema_version != CURRENT_SCHEMA_VERSION:
        log.warning(
            "snapshot_schema_version_mismatch",
            client_version=snapshot.schema_version,
            server_version=CURRENT_SCHEMA_VERSION,
            snapshot_id=str(snapshot.snapshot_id),
        )

    log.info(
        "validate_called",
        user=user.username,
        snapshot_id=str(snapshot.snapshot_id),
        schema_version=snapshot.schema_version,
        city=snapshot.project.city,
    )
    return evaluate(snapshot)
