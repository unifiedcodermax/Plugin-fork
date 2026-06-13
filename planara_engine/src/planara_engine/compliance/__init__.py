"""Compliance evaluators.

Importing this package registers every evaluator with the engine
registry as a side effect. The api/app.py lifespan import is what
triggers registration in production; tests import it directly.
"""

from planara_engine.compliance import (
    coverage,  # noqa: F401 — side-effect import
    fsi,  # noqa: F401 — side-effect import
    height,  # noqa: F401 — side-effect import
    lift_required,  # noqa: F401 — side-effect import
    parking,  # noqa: F401 — side-effect import
    room_height,  # noqa: F401 — side-effect import
    setback,  # noqa: F401 — side-effect import
)

__all__: list[str] = []

