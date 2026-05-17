"""SQLModel ORM tables.

Pure data: no business logic. Auth flows (verify password, mint
token) live in ``auth/``; reporting/rendering lives in ``reporting/``.
This module only describes the storage shape.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    return datetime.now(UTC)


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


class ValidationReport(SQLModel, table=True):
    """One persisted validation run.

    The full ArchivalReport is stored verbatim in ``payload`` (JSON
    string) so we never lose information. Denormalized columns —
    city/classification/zone/ok/counts/rule_pack_version — exist for
    filtered queries; ``payload`` remains the source of truth for
    re-rendering or diffing.

    Why TEXT instead of JSONB / JSON column type: SQLite has no
    structured JSON column. Storing as TEXT keeps the schema portable
    to Postgres (a future migration changes the column type to
    JSONB; query code reads it back the same way through Pydantic).

    Indexes:
      - ix_history_user_generated covers "list my recent runs" (the
        most common query), DESC sort handled by ORDER BY at the
        repo layer.
      - ix_history_city_zone covers "filter to Bangalore Commercial"
        style cross-cuts.
    """

    __tablename__ = "validation_reports"
    __table_args__ = (
        Index("ix_history_user_generated", "user_id", "generated_at"),
        Index("ix_history_city_zone", "city", "classification", "zone"),
    )

    report_id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    snapshot_id: UUID = Field(index=True)

    city: str = Field(index=True, max_length=64)
    classification: str = Field(max_length=64)
    zone: str = Field(max_length=64)

    ok: bool = Field(index=True)
    violation_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    rule_pack_version: str = Field(max_length=32)

    generated_at: datetime = Field(nullable=False)

    # Full ArchivalReport, JSON-encoded. Read back with json.loads ->
    # ArchivalReport.model_validate. Never edit by hand — it's a
    # frozen record of what the engine computed at the time.
    payload: str
