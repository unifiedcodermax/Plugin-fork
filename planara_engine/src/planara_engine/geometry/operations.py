"""Higher-level geometry ops used by evaluators.

All inputs are domain Polygons (or lists of them). All outputs are
plain floats / ShapelyPolygon objects. The seam between domain and
Shapely runs through ``normalize.to_shapely`` — no direct Shapely
imports in evaluator code.
"""

from __future__ import annotations

from shapely.geometry import Polygon as ShapelyPolygon
from shapely.ops import unary_union

from planara_engine.domain.geometry import Polygon
from planara_engine.geometry.normalize import to_shapely


def polygon_area(poly: Polygon) -> float:
    """Signed-positive area in square meters."""

    return float(to_shapely(poly).area)


def polygons_union_area(polys: list[Polygon]) -> float:
    """Area of the union of all input polygons in m^2.

    Used by coverage and FSI when multiple disjoint footprints
    need to be combined without double-counting their overlaps.
    """

    if not polys:
        return 0.0
    shapes = [to_shapely(p) for p in polys]
    return float(unary_union(shapes).area)


def inset(poly: Polygon, distance_m: float) -> ShapelyPolygon | None:
    """Erode a polygon by ``distance_m``. Returns None if the result is empty.

    Used by setback evaluators: the building must lie within
    ``plot.inset(setback_m)``.
    """

    if distance_m < 0:
        raise ValueError("inset distance must be non-negative")

    shrunk = to_shapely(poly).buffer(-distance_m, join_style="mitre")
    if shrunk.is_empty:
        return None
    if isinstance(shrunk, ShapelyPolygon):
        return shrunk
    # buffer can return MultiPolygon for awkward shapes; pick the
    # largest connected piece (almost always what the caller
    # wants for "permissible build envelope").
    largest = max(shrunk.geoms, key=lambda g: g.area)
    return largest


def polygon_within(inner: Polygon, outer: Polygon) -> bool:
    """True iff ``inner`` is contained within ``outer`` (boundary allowed)."""

    inner_shp = to_shapely(inner)
    outer_shp = to_shapely(outer)
    return bool(inner_shp.within(outer_shp) or inner_shp.equals(outer_shp))


def minimum_distance_to_boundary(inner: Polygon, outer: Polygon) -> float:
    """Shortest distance from ``inner`` to the boundary of ``outer``.

    Returns 0.0 when inner touches the boundary. Negative result
    is not possible — Shapely returns the signed distance only via
    a different API; this helper is the "how close are we?" check
    for setback evaluation.
    """

    inner_shp = to_shapely(inner)
    outer_boundary = to_shapely(outer).boundary
    return float(inner_shp.distance(outer_boundary))
