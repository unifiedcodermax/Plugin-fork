"""SQLModel ORM tables.

Pure data: no business logic. Auth flows (verify password, mint
token) live in ``auth/``; this module only describes the storage
shape.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    """A local user account.

    The engine ships no user-management UI yet — accounts are
    created via ``planara-engine create-user``. The password is
    stored as a bcrypt hash; the column is named ``password_hash``
    so it is obvious in DB dumps that it is NOT plaintext.

    ``is_active`` lets us disable an account without deleting it
    (which would orphan future audit-log references).
    """

    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, min_length=1, max_length=64)
    password_hash: str = Field(min_length=1, max_length=255)
    is_active: bool = Field(default=True, index=True)

    created_at: datetime = Field(default_factory=_utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=_utc_now, nullable=False)
