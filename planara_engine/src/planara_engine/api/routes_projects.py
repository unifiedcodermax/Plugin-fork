"""/projects — user-named regression-tracking anchors.

A Project is a stable identity that groups many validation runs
together. Without it, the auto-diff endpoint would collapse two
distinct designs that happen to share (city, classification,
zone) into the same bucket; with it, /history/{id}/diff anchors
on project_id and gives every design its own diff lane.

Routes:
  POST /projects        Create. Name must be unique per user.
  GET  /projects        List the caller's projects.
  GET  /projects/{id}   Fetch one (user-scoped; 404 on missing
                        or not-mine).

Like /history, every read is user-scoped — both "doesn't exist"
and "belongs to someone else" surface as 404 so the response
shape doesn't leak existence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from planara_engine.auth.deps import CurrentUser, SessionDep
from planara_engine.core.errors import Conflict, NotFound
from planara_engine.core.logging import get_logger
from planara_engine.persistence.models import Project
from planara_engine.persistence.projects import (
    ProjectNameConflict,
    create_project,
    get_project,
    list_projects,
)

router = APIRouter(prefix="/projects", tags=["projects"])
log = get_logger("planara.api.projects")

_MAX_LIMIT = 200
_DEFAULT_LIMIT = 100


class CreateProjectRequest(BaseModel):
    """Body of POST /projects."""

    name: str = Field(min_length=1, max_length=128)
    city: str = Field(min_length=1, max_length=64)
    classification: str = Field(min_length=1, max_length=64)
    zone: str = Field(min_length=1, max_length=64)


class ProjectResponse(BaseModel):
    """JSON shape the plugin reads. Mirrors the SQL row but is
    decoupled from the ORM so a future schema tweak doesn't leak."""

    id: int
    name: str
    city: str
    classification: str
    zone: str
    created_at: datetime

    @classmethod
    def from_row(cls, row: Project) -> ProjectResponse:
        # id is guaranteed non-None once the row has been flushed —
        # which is always the case for rows that escape the repo.
        assert row.id is not None
        return cls(
            id=row.id,
            name=row.name,
            city=row.city,
            classification=row.classification,
            zone=row.zone,
            created_at=row.created_at,
        )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ProjectResponse,
    summary="Create a new project",
)
def post_project(
    body: CreateProjectRequest,
    user: CurrentUser,
    session: SessionDep,
) -> ProjectResponse:
    """Create a new project owned by the caller.

    Returns 409 Conflict if the user already has a project with
    this name; the plugin's "+ New project" flow can then prompt
    for a different label or offer to select the existing one.
    """

    try:
        row = create_project(
            session,
            user_id=user.id,  # type: ignore[arg-type]
            name=body.name,
            city=body.city,
            classification=body.classification,
            zone=body.zone,
        )
    except ProjectNameConflict as exc:
        raise Conflict(str(exc), details={"name": exc.name}) from exc

    log.info(
        "project_created",
        user=user.username,
        project_id=row.id,
        name=row.name,
        city=row.city,
    )
    return ProjectResponse.from_row(row)


@router.get(
    "",
    response_model=None,
    summary="List my projects",
)
def get_projects(
    user: CurrentUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = _DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """Paginated, most-recent-first."""

    rows = list_projects(
        session,
        user_id=user.id,  # type: ignore[arg-type]
        limit=limit,
        offset=offset,
    )
    return {
        "limit": limit,
        "offset": offset,
        "items": [ProjectResponse.from_row(r).model_dump(mode="json") for r in rows],
    }


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Fetch one project (user-scoped)",
)
def get_project_route(
    project_id: int,
    user: CurrentUser,
    session: SessionDep,
) -> ProjectResponse:
    row = get_project(session, user_id=user.id, project_id=project_id)  # type: ignore[arg-type]
    if row is None:
        raise NotFound(
            f"no project with id {project_id}",
            details={"project_id": project_id},
        )
    return ProjectResponse.from_row(row)
