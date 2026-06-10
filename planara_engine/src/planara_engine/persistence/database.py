"""SQLite-backed persistence using SQLModel.

One engine per process (cached). Sessions are short-lived and
created per-request via the FastAPI dependency in
``persistence.deps``.

Why SQLite + SQLModel:
  * Zero ops. The engine is a desktop sidecar; running a Postgres
    instance alongside SketchUp would be absurd.
  * SQLModel pairs Pydantic models with SQLAlchemy ORM, so the
    domain/ and persistence/ layers share schema without
    hand-rolled mappers.
  * Same code targets a real RDBMS later by swapping the URL.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from planara_engine.core.logging import get_logger
from planara_engine.core.settings import get_settings

log = get_logger("planara.persistence")


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine.

    Cached so we don't reopen the SQLite file on every request.
    For sqlite:///./planara.db, parent directories are created
    eagerly so first-run doesn't fail with "unable to open
    database file".
    """

    settings = get_settings()
    url = settings.db_url

    if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
        # sqlite:///relative/path or sqlite:////abs/path
        path_part = url.removeprefix("sqlite:///")
        db_path = Path(path_part)
        if not db_path.is_absolute():
            db_path = settings.project_root / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{db_path}"

    # check_same_thread=False is required when sharing the engine
    # across FastAPI's threadpool; SQLAlchemy still serializes
    # connections per Session so this is safe.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}

    log.info("db_engine_created", url=url)
    return create_engine(url, connect_args=connect_args, echo=False)


def init_db() -> None:
    """Create tables that don't yet exist.

    Idempotent. Called at app lifespan startup and from the CLI
    seed command. Lightweight enough that running it on every boot
    is fine for the MVP; migrations (Alembic) come later.
    """

    # Importing the module here registers the models with SQLModel's
    # metadata. We use a function-local import to avoid circulars
    # between database.py and the model modules.
    from planara_engine.persistence import models  # noqa: F401

    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _apply_inline_migrations(engine)
    log.info("db_schema_ready")
    _seed_default_user(engine)


def _seed_default_user(engine: Engine) -> None:
    """Auto-seed a default admin user on first boot if no users exist in the database."""
    from sqlmodel import Session, select

    from planara_engine.auth.service import register_user
    from planara_engine.persistence.models import User

    with Session(engine) as session:
        statement = select(User)
        any_user = session.exec(statement).first()
        if any_user is None:
            log.info("seeding_default_user", username="admin")
            try:
                register_user(session, username="admin", password="password123")
                session.commit()
                log.info("default_user_seeded", username="admin")
            except Exception as exc:
                log.error("default_user_seed_failed", error=str(exc))


def _apply_inline_migrations(engine: Engine) -> None:
    """Apply additive schema tweaks that ``create_all`` can't.

    ``SQLModel.metadata.create_all`` creates missing tables but
    never adds columns to existing ones. Until we adopt Alembic,
    this function is the place to record one-line ALTERs that
    bring a pre-existing DB up to the current schema. Each
    migration checks for its own marker (column existence) and
    short-circuits — so calling init_db on a fresh DB is a no-op.

    Postgres deployment will replace this with Alembic; the
    migrations here are intentionally trivial enough that the
    swap is mechanical.
    """

    inspector = inspect(engine)
    if not inspector.has_table("validation_reports"):
        return

    columns = {col["name"] for col in inspector.get_columns("validation_reports")}
    if "project_id" not in columns:
        # Nullable column; existing rows stay NULL and auto-diff
        # falls back to (city, classification, zone) for them.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE validation_reports "
                    "ADD COLUMN project_id INTEGER REFERENCES projects(id)"
                )
            )
        log.info("db_migration_applied", change="validation_reports.project_id")


def session_scope() -> Iterator[Session]:
    """Yield a Session bound to the cached engine.

    Used as a FastAPI dependency. Commits on success; rolls back
    on exception; always closes.
    """

    session = Session(get_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
