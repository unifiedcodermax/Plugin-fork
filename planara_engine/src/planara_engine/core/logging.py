"""Structured logging via structlog.

One configure call at app boot; everywhere else just does
``log = get_logger(__name__)`` and binds context fields.

Production emits JSON (one event per line). Dev emits a colored
key=value rendering for human eyes.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from planara_engine.core.settings import Settings


def _add_log_level_upper(
    _logger: logging.Logger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Render the log level as uppercase ("INFO" not "info").

    structlog defaults to lowercase; uppercase aligns with stdlib
    output and is easier to grep.
    """

    event_dict["level"] = method_name.upper()
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Wire stdlib logging + structlog into a single pipeline.

    Called once during FastAPI lifespan startup. Idempotent: safe
    to call again (e.g. from tests) and it will replace the
    previous configuration.
    """

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        _add_log_level_upper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        timestamper,
    ]

    renderer: Processor
    if settings.use_json_logs:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (uvicorn, sqlalchemy, etc.) through structlog
    # so we get one consistent format.
    handler = logging.StreamHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=renderer,
            foreign_pre_chain=shared_processors,
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Quiet uvicorn's access log noise unless DEBUG is on.
    if log_level > logging.DEBUG:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str | None = None, **initial_context: Any) -> Any:
    """Return a bound structlog logger.

    Typed as ``Any`` because structlog's BoundLogger is dynamic;
    annotating it precisely fights more than it helps.
    """

    log = structlog.get_logger(name)
    return log.bind(**initial_context) if initial_context else log
