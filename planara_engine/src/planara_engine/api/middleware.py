"""ASGI middleware: request-id, access log, structured error mapping."""

from __future__ import annotations

import time
import uuid
from typing import Awaitable, Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from planara_engine.core.logging import get_logger

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id + structured access log line to every request.

    The id is taken from the inbound ``X-Request-ID`` header if the
    Ruby plugin sent one (it should, for correlation), otherwise
    generated server-side. It is bound into structlog's contextvars
    so every log line emitted while handling the request carries
    ``request_id`` automatically.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        log = get_logger("planara.access")
        start = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            log.exception("request_failed", elapsed_ms=round(elapsed_ms, 2))
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        response.headers[REQUEST_ID_HEADER] = request_id
        log.info(
            "request_completed",
            status=response.status_code,
            elapsed_ms=round(elapsed_ms, 2),
        )
        return response
