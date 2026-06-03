"""Map PlanaraError -> HTTP responses.

Centralizes error translation so router code can raise domain
exceptions without thinking about status codes or JSON envelopes.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from fastapi.exceptions import RequestValidationError
from planara_engine.core.errors import PlanaraError
from planara_engine.core.logging import get_logger



def register_error_handlers(app: FastAPI) -> None:
    """Attach the PlanaraError handler to a FastAPI app."""

    log = get_logger("planara.errors")

    @app.exception_handler(PlanaraError)
    async def _handle_planara_error(_request: Request, exc: PlanaraError) -> JSONResponse:
        # 5xx is a server-side bug; log at error. 4xx is client input; log at info.
        if exc.http_status >= 500:
            log.error(
                "planara_error",
                code=exc.code,
                message=exc.message,
                details=exc.details,
            )
        else:
            log.info(
                "planara_error",
                code=exc.code,
                message=exc.message,
                details=exc.details,
            )

        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        body = await _request.body()
        log.error(
            "validation_error",
            errors=exc.errors(),
            body=body.decode("utf-8", errors="replace"),
        )
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors()}
        )

