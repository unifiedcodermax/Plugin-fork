"""Geometry helpers: Shapely-backed polygon ops."""

from planara_engine.geometry.normalize import to_shapely
from planara_engine.geometry.operations import (
    inset,
    minimum_distance_to_boundary,
    polygon_area,
    polygon_within,
    polygons_union_area,
)

__all__ = [
    "inset",
    "minimum_distance_to_boundary",
    "polygon_area",
    "polygon_within",
    "polygons_union_area",
    "to_shapely",
]
