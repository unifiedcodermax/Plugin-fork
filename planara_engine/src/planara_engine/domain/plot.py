"""The plot of land that the building sits on."""

from __future__ import annotations

from pydantic import BaseModel, Field

from planara_engine.domain.geometry import Polygon


class Plot(BaseModel):
    """Site/plot boundary.

    polygon:    closed 2D polygon in meters.
    area_m2:    OPTIONAL extractor-provided area. When omitted,
                the engine recomputes from ``polygon`` (the
                authoritative source). When present and it
                disagrees with the polygon area by more than a
                small tolerance, the engine logs a warning — the
                extractor may have a unit-conversion bug.
    """

    polygon: Polygon
    area_m2: float | None = Field(default=None, gt=0.0)
