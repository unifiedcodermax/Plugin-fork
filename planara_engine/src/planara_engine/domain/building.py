"""Building: a stack of floors, each with its own footprint.

Why per-floor footprints (not just a bounding box):
  - Real FSI = sum(floor_area_i) / plot_area. Setbacks tower with
    floor (a 1st-floor wall is allowed at the boundary; a 5th-
    floor wall is not). Coverage = footprint of the GROUND floor
    only. Each compliance rule wants a different cross-section
    of the stack.
  - The bbox-based legacy code conflated all three and produced
    misleading numbers; this schema makes the right shape the
    only shape.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from planara_engine.domain.geometry import Polygon


class Floor(BaseModel):
    """One floor / storey of the building.

    level:         0 = ground floor, 1 = first floor, etc.
                   Negative levels are basements (excluded from
                   FSI in most byelaws — evaluators decide).
    polygon:       footprint at this level, meters.
    height_m:      finished floor-to-floor height in meters.
                   3.0 is the conventional default for residential
                   floors in India but the extractor should set it
                   from the model.
    is_habitable:  whether this floor counts as habitable area
                   (defaults True). Stilts, service floors, and
                   parking decks set False so FSI evaluators can
                   exclude them per byelaw.
    """

    level: int
    polygon: Polygon
    height_m: float = Field(gt=0.0, le=30.0)
    is_habitable: bool = True


class Building(BaseModel):
    """The full stack.

    floors:           one entry per floor. Order is not assumed;
                      the engine sorts by level.
    total_height_m:   OPTIONAL extractor-provided height. When
                      omitted, the engine computes
                      sum(floor.height_m). When present and
                      inconsistent, the engine logs a warning.
    """

    floors: list[Floor] = Field(min_length=1)
    total_height_m: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def _unique_levels(self) -> Building:
        levels = [f.level for f in self.floors]
        if len(set(levels)) != len(levels):
            raise ValueError("duplicate floor levels are not allowed")
        return self
