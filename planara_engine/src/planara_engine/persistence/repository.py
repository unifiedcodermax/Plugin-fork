"""Thin repository layer over SQLModel.

Keeps SQL out of service code. Each function takes an explicit
``Session`` so callers control transaction scope.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session, select

from planara_engine.persistence.models import User


def get_user_by_username(session: Session, username: str) -> User | None:
    """Look up a user by username (case-sensitive, exact match)."""

    stmt = select(User).where(User.username == username)
    return session.exec(stmt).first()


def get_user_by_id(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def create_user(
    session: Session,
    *,
    username: str,
    password_hash: str,
    is_active: bool = True,
) -> User:
    """Insert a new User. Caller is responsible for commit/rollback."""

    user = User(
        username=username,
        password_hash=password_hash,
        is_active=is_active,
    )
    session.add(user)
    session.flush()  # populate user.id without committing
    return user


def touch_user(session: Session, user: User) -> User:
    """Bump updated_at; used after password changes etc."""

    user.updated_at = datetime.now(UTC)
    session.add(user)
    session.flush()
    return user
