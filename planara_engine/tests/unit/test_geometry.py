"""Geometry helpers: areas, unions, insets, containment, distances."""

from __future__ import annotations

import math

import pytest

from planara_engine.core.errors import ValidationFailed
from planara_engine.domain.geometry import Polygon
from planara_engine.geometry import (
    inset,
    minimum_distance_to_boundary,
    polygon_area,
    polygon_within,
    polygons_union_area,
    to_shapely,
)


def _square(size: float = 10.0, offset: tuple[float, float] = (0.0, 0.0)) -> Polygon:
    ox, oy = offset
    return Polygon(
        exterior=[
            [ox, oy],
            [ox + size, oy],
            [ox + size, oy + size],
            [ox, oy + size],
        ]
    )


def test_area_of_unit_square() -> None:
    assert math.isclose(polygon_area(_square(1.0)), 1.0)


def test_area_of_10m_square() -> None:
    assert math.isclose(polygon_area(_square(10.0)), 100.0)


def test_area_subtracts_holes() -> None:
    poly = Polygon(
        exterior=[[0, 0], [10, 0], [10, 10], [0, 10]],
        holes=[[[2, 2], [4, 2], [4, 4], [2, 4]]],
    )
    assert math.isclose(polygon_area(poly), 100.0 - 4.0)


def test_union_of_disjoint_squares() -> None:
    s1 = _square(5.0, (0, 0))
    s2 = _square(5.0, (10, 0))
    assert math.isclose(polygons_union_area([s1, s2]), 50.0)


def test_union_of_overlapping_squares_counts_overlap_once() -> None:
    s1 = _square(5.0, (0, 0))
    s2 = _square(5.0, (3, 0))  # 2m overlap on x
    # Total area: two 5x5 = 50, overlap region 2x5 = 10, union = 40.
    assert math.isclose(polygons_union_area([s1, s2]), 40.0)


def test_union_of_empty_list_is_zero() -> None:
    assert polygons_union_area([]) == 0.0


def test_inset_shrinks_square_uniformly() -> None:
    shrunk = inset(_square(10.0), 1.0)
    assert shrunk is not None
    # 10x10 inset by 1 -> 8x8 = 64
    assert math.isclose(shrunk.area, 64.0)


def test_inset_returns_none_when_distance_eats_polygon() -> None:
    assert inset(_square(2.0), 2.0) is None  # 2m inset on 2m square -> nothing left


def test_inset_rejects_negative_distance() -> None:
    with pytest.raises(ValueError):
        inset(_square(10.0), -1.0)


def test_within_strictly_contained() -> None:
    plot = _square(10.0)
    bldg = _square(5.0, (2, 2))  # fully inside
    assert polygon_within(bldg, plot) is True


def test_within_outside() -> None:
    plot = _square(5.0)
    bldg = _square(5.0, (10, 0))  # disjoint
    assert polygon_within(bldg, plot) is False


def test_within_touching_boundary_is_allowed() -> None:
    plot = _square(10.0)
    bldg = _square(5.0, (0, 0))  # shares the SW corner / two edges
    assert polygon_within(bldg, plot) is True


def test_distance_when_inside_with_clearance() -> None:
    plot = _square(10.0)
    bldg = _square(5.0, (2, 3))  # 2m clearance on x, 3m on y -> min is 2m
    assert math.isclose(minimum_distance_to_boundary(bldg, plot), 2.0)


def test_distance_zero_when_touching() -> None:
    plot = _square(10.0)
    bldg = _square(5.0, (0, 0))
    assert math.isclose(minimum_distance_to_boundary(bldg, plot), 0.0)


def test_to_shapely_repairs_self_touching() -> None:
    # A bowtie / figure-8 — Shapely flags as invalid; make_valid fixes
    # it but only if the result is still a single Polygon. Self-
    # intersecting figure-8s become MultiPolygons and must raise.
    bowtie = Polygon(exterior=[[0, 0], [4, 4], [4, 0], [0, 4]])
    with pytest.raises(ValidationFailed):
        to_shapely(bowtie)
