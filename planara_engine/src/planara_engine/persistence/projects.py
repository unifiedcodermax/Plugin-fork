"""Repository for Project rows.

Sibling to ``reports.py``. Every query is user-scoped: a user
must never see or address another user's project through these
helpers. Name uniqueness is enforced per user (a DB index does
the heavy lifting; this layer turns the IntegrityError into a
domain-level signal the route can render as 409 Conflict).
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from planara_engine.persistence.models import Project


class ProjectNameConflict(Exception):
    """Raised when a Project name collides with an existing one for
    the same user. The route layer translates this to 409."""

    def __init__(self, name: str) -> None:
        super().__init__(f"a project named {name!r} already exists")
        self.name = name


def create_project(
    session: Session,
    *,
    user_id: int,
    name: str,
    city: str,
    classification: str,
    zone: str,
) -> Project:
    """Insert a new Project row owned by ``user_id``.

    Raises ProjectNameConflict if the (user_id, name) pair already
    exists. The route handler maps that to HTTP 409 — callers can
    branch on "did the user pick a duplicate name?" without
    sniffing IntegrityError shapes themselves.

    Caller commits.
    """

    row = Project(
        user_id=user_id,
        name=name,
        city=city,
        classification=classification,
        zone=zone,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ProjectNameConflict(name) from exc
    return row


def list_projects(
    session: Session,
    *,
    user_id: int,
    limit: int = 100,
    offset: int = 0,
) -> list[Project]:
    """All of ``user_id``'s projects, most-recent-first.

    Pagination defaults are generous because a user is unlikely
    to have hundreds of projects — but the route still accepts
    limit/offset so a future migration to that scale doesn't need
    a schema change.
    """

    stmt = (
        select(Project)
        .where(Project.user_id == user_id)
        .order_by(col(Project.created_at).desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.exec(stmt).all())


def get_project(
    session: Session,
    *,
    user_id: int,
    project_id: int,
) -> Project | None:
    """Fetch one project, user-scoped.

    Returns None for "doesn't exist" AND "exists but belongs to
    another user" — the route surfaces both as 404 to avoid
    leaking existence.
    """

    stmt = select(Project).where(
        Project.id == project_id,
        Project.user_id == user_id,
    )
    return session.exec(stmt).first()


def get_project_by_name(
    session: Session,
    *,
    user_id: int,
    name: str,
) -> Project | None:
    """Lookup helper for the lazy-create path: returns the existing
    Project with this name, or None.

    Routes that want "create-or-get" semantics call this first,
    then fall back to create_project when the answer is None.
    """

    stmt = select(Project).where(
        Project.user_id == user_id,
        Project.name == name,
    )
    return session.exec(stmt).first()
