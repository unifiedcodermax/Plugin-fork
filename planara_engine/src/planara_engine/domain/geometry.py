"""Geometry primitives shared across the domain models.

Polygon: a closed planar polygon in meters, GeoJSON-style outer
ring with optional holes. All compliance code receives polygons
through this model; raw [[x,y]...] lists never leak past the
domain boundary.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, model_validator

# A 2D point in meters: [x, y].
Point2D = Annotated[list[float], Field(min_length=2, max_length=2)]


class Polygon(BaseModel):
    """Closed 2D polygon in metres.

    - ``exterior``: list of [x, y] pairs. Minimum 3 distinct
      points. The polygon is considered closed; whether the first
      point is repeated as the last is normalized away — both
      forms accepted on input.
    - ``holes``: optional list of inner rings. Each follows the
      same rules as ``exterior``.

    Ring orientation (CCW outer, CW holes) is NOT enforced here;
    ``geometry.normalize.normalize_polygon`` flips orientations
    as needed before any Shapely op runs. Enforcing here would
    reject otherwise-valid input from imperfect extractors.
    """

    exterior: list[Point2D]
    holes: list[list[Point2D]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_rings(self) -> Polygon:
        _check_ring(self.exterior, "exterior")
        for i, hole in enumerate(self.holes):
            _check_ring(hole, f"holes[{i}]")
        return self


def _check_ring(ring: list[list[float]], name: str) -> None:
    # Normalize the "first == last" closed form by dropping the
    # duplicate. After that we need at least 3 distinct vertices
    # to define a polygon.
    pts = ring[:-1] if len(ring) >= 2 and ring[0] == ring[-1] else ring
    if len(pts) < 3:
        raise ValueError(f"{name}: polygon ring needs at least 3 distinct points")
    # Detect degenerate sequential duplicates (a==a==b is a clear
    # extractor bug). Non-sequential duplicates (a==c, with b
    # between) are OK — they happen at touching boundaries.
    for i in range(1, len(pts)):
        if pts[i] == pts[i - 1]:
            raise ValueError(f"{name}: consecutive duplicate vertex at index {i}")
