"""Console entry point: ``planara-engine``.

Thin wrapper around uvicorn so the supervisor (and humans) can
start the service with one command, picking up Settings from env /
.env.
"""

from __future__ import annotations

import uvicorn

from planara_engine.core.settings import get_settings


def main() -> None:
    """Boot the FastAPI app under uvicorn.

    Uses ``host``/``port`` from Settings. Reload is enabled only in
    the dev environment so production deploys are stable.
    """

    settings = get_settings()
    uvicorn.run(
        "planara_engine.api.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.env.value == "dev",
        log_config=None,  # we configure logging ourselves
        access_log=False,  # RequestContextMiddleware emits structured access logs
    )


if __name__ == "__main__":
    main()
