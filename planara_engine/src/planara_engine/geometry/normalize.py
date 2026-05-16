"""Convert domain Polygon objects into Shapely polygons.

This is the single seam where ring orientation, closure, and
validity are normalized. Every evaluator goes through here, so a
bug in geometry conventions has exactly one place to live.
"""

from __future__ import annotations

from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry.polygon import orient
from shapely.validation import explain_validity, make_valid

from planara_engine.core.errors import ValidationFailed
from planara_engine.domain.geometry import Polygon


def to_shapely(poly: Polygon) -> ShapelyPolygon:
    """Convert a domain Polygon into a normalized Shapely polygon.

    Normalization:
      - Outer ring oriented CCW; holes oriented CW (GeoJSON
        convention; Shapely is forgiving but consistent input
        makes downstream operations predictable).
      - Self-intersections (figure-8s, overlapping segments)
        are repaired via Shapely's ``make_valid``. If the result
        is no longer a single Polygon (i.e. the input was a
        MultiPolygon with disconnected pieces), we raise — the
        compliance rules in this MVP assume single-component
        polygons.
    """

    shp = ShapelyPolygon(_drop_closing_point(poly.exterior),
                         holes=[_drop_closing_point(h) for h in poly.holes])

    if not shp.is_valid:
        reason = explain_validity(shp)
        repaired = make_valid(shp)
        if isinstance(repaired, ShapelyPolygon):
            shp = repaired
        else:
            raise ValidationFailed(
                f"polygon is not a single connected region after repair: {reason}",
                details={"reason": reason, "geom_type": repaired.geom_type},
            )

    return orient(shp, sign=1.0)  # CCW outer, CW holes


def _drop_closing_point(ring: list[list[float]]) -> list[tuple[float, float]]:
    """Strip the closing point if present so Shapely doesn't double up."""

    pts = ring[:-1] if len(ring) >= 2 and ring[0] == ring[-1] else ring
    return [(float(x), float(y)) for x, y in pts]
