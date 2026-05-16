"""FastAPI app factory.

Single ``create_app()`` builds the application so tests can hand
the factory a custom Settings without polluting the singleton, and
production goes through ``app`` for ``uvicorn planara_engine.api.app:app``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from planara_engine import __version__
from planara_engine.api.errors import register_error_handlers
from planara_engine.api.middleware import RequestContextMiddleware
from planara_engine.api.routes_auth import router as auth_router
from planara_engine.api.routes_health import router as health_router
from planara_engine.api.routes_validate import router as validate_router

# Side-effect import: registers every evaluator with the engine
# registry. Must run before any route handler dispatches a rule.
import planara_engine.compliance  # noqa: F401, E402
from planara_engine.core.logging import configure_logging, get_logger
from planara_engine.core.settings import Settings, get_settings
from planara_engine.persistence.database import init_db


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a FastAPI app.

    Accepts an optional ``settings`` override so tests can spin up
    multiple isolated instances. In production this is None and we
    fall back to the cached singleton.
    """

    settings = settings or get_settings()
    configure_logging(settings)
    log = get_logger("planara.boot")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        log.info(
            "engine_starting",
            version=__version__,
            env=settings.env.value,
            host=settings.host,
            port=settings.port,
        )
        init_db()
        yield
        log.info("engine_stopping")

    app = FastAPI(
        title="Planara Compliance Engine",
        version=__version__,
        summary="Validate building designs against municipal byelaws.",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_prod else None,
        redoc_url=None,
    )

    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(validate_router)

    return app


# Module-level app for `uvicorn planara_engine.api.app:app`.
app = create_app()
