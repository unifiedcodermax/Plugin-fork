"""Domain models — the wire contract between Ruby and Python.

Convenience re-exports so callers can do
``from planara_engine.domain import Snapshot`` instead of digging
into the submodule layout.
"""

from planara_engine.domain.building import Building, Floor
from planara_engine.domain.geometry import Polygon
from planara_engine.domain.plot import Plot
from planara_engine.domain.project_context import ProjectContext
from planara_engine.domain.snapshot import Snapshot
from planara_engine.domain.violation import Severity, ValidationResponse, Violation

__all__ = [
    "Building",
    "Floor",
    "Plot",
    "Polygon",
    "ProjectContext",
    "Severity",
    "Snapshot",
    "ValidationResponse",
    "Violation",
]
