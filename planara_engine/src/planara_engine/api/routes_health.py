"""Health and readiness endpoints.

The Ruby plugin polls ``/health`` after spawning the sidecar to
decide when it is safe to send the first request. Keep this
endpoint dependency-free — no DB, no rule loading — so a failing
dependency never makes the engine look dead to the supervisor.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from planara_engine import __version__

router = APIRouter(tags=["meta"])


class HealthResponse(BaseModel):
    """Health probe payload.

    Returned by ``/health``. Shape is deliberately tiny: anything
    more would tempt callers to grow it into a /status dashboard.
    """

    status: str
    version: str
    time: datetime


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    """Return 200 + a small payload as long as the process is alive."""

    return HealthResponse(
        status="ok",
        version=__version__,
        time=datetime.now(timezone.utc),
    )
