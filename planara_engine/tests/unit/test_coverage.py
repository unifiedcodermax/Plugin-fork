"""Coverage + open-space evaluators."""

from __future__ import annotations

import importlib
from collections.abc import Iterator

import pytest

from planara_engine.core.errors import ValidationFailed
from planara_engine.domain import (
    Building,
    Floor,
    Plot,
    Polygon,
    ProjectContext,
    Snapshot,
)
from planara_engine.engine import registry
from planara_engine.rules.schema import Rule


@pytest.fixture(autouse=True)
def fresh_registry() -> Iterator[None]:
    registry._reset_for_tests()
    import planara_engine.compliance.coverage as m

    importlib.reload(m)
    yield
    registry._reset_for_tests()


def _sq(size: float, ox: float = 0.0, oy: float = 0.0) -> Polygon:
    return Polygon(
        exterior=[[ox, oy], [ox + size, oy], [ox + size, oy + size], [ox, oy + size]]
    )


def _snap(plot_size: float, ground_polys: list[Polygon], extra_floors: list[Floor] | None = None) -> Snapshot:
    floors = [Floor(level=0, polygon=p, height_m=3.0) for p in ground_polys]
    # Duplicate-level guard means we can only put ONE Floor at level 0.
    # The "multi-block ground floor" case is therefore modeled with a
    # MultiPolygon — for the MVP we pass one Floor whose polygon IS the
    # union (the extractor is responsible for unioning them). The
    # union-of-list test below uses a different path: by passing multiple
    # ground polygons we want unioned, we'd need to model them differently.
    # For now we'll just take ground_polys[0] for the level=0 case and
    # assert union behavior in a separate test that bypasses the schema.
    floors = [Floor(level=0, polygon=ground_polys[0], height_m=3.0)] if ground_polys else []
    if extra_floors:
        floors.extend(extra_floors)
    if not floors:
        # Building requires >=1 floor — add a placeholder above grade.
        floors = [Floor(level=1, polygon=_sq(1.0), height_m=3.0)]
    return Snapshot(
        project=ProjectContext(city="X", classification="CBD", zone="Residential"),
        plot=Plot(polygon=_sq(plot_size)),
        building=Building(floors=floors),
    )


def _rule(name: str, **params: object) -> Rule:
    return Rule(id=f"t.{name}", category=name, evaluator=name, params=params)


# ---- coverage ----------------------------------------------------------------


def test_coverage_passes_under_limit() -> None:
    # 10x10 footprint on 20x20 plot = 25% coverage; cap 50% -> pass.
    snap = _snap(20.0, [_sq(10.0, 5.0, 5.0)])
    result = registry.get("ground_coverage_pct")(
        snap, _rule("ground_coverage_pct", max_coverage_pct=50.0)
    )
    assert result.passed is True
    assert result.computed["coverage_pct"] == 25.0
    assert result.computed["max_coverage_pct"] == 50.0
    assert result.computed["ground_area_m2"] == 100.0
    assert result.computed["plot_area_m2"] == 400.0


def test_coverage_fails_over_limit() -> None:
    # 15x15 footprint on 20x20 = 56.25% coverage; cap 50% -> fail.
    snap = _snap(20.0, [_sq(15.0, 2.0, 2.0)])
    result = registry.get("ground_coverage_pct")(
        snap, _rule("ground_coverage_pct", max_coverage_pct=50.0)
    )
    assert result.passed is False
    assert result.computed["coverage_pct"] == 56.25


def test_coverage_exactly_at_limit_passes() -> None:
    # 10x14.142... -> exactly 50% of 400 = 200. Use a 10x20 strip = 50%.
    # Plot 20x20, build 10x20 -> 200/400 = 50% exactly.
    snap = Snapshot(
        project=ProjectContext(city="X", classification="CBD", zone="Residential"),
        plot=Plot(polygon=_sq(20.0)),
        building=Building(
            floors=[
                Floor(
                    level=0,
                    polygon=Polygon(exterior=[[0, 0], [10, 0], [10, 20], [0, 20]]),
                    height_m=3.0,
                )
            ]
        ),
    )
    result = registry.get("ground_coverage_pct")(
        snap, _rule("ground_coverage_pct", max_coverage_pct=50.0)
    )
    assert result.passed is True


def test_coverage_no_ground_floor_returns_zero_coverage() -> None:
    # Building with floors above grade but no level==0 -> coverage 0%.
    snap = Snapshot(
        project=ProjectContext(city="X", classification="CBD", zone="Residential"),
        plot=Plot(polygon=_sq(20.0)),
        building=Building(
            floors=[Floor(level=1, polygon=_sq(15.0), height_m=3.0)]
        ),
    )
    result = registry.get("ground_coverage_pct")(
        snap, _rule("ground_coverage_pct", max_coverage_pct=50.0)
    )
    assert result.passed is True
    assert result.computed["coverage_pct"] == 0.0


def test_coverage_requires_positive_max() -> None:
    snap = _snap(20.0, [_sq(10.0)])
    with pytest.raises(ValidationFailed):
        registry.get("ground_coverage_pct")(
            snap, _rule("ground_coverage_pct", max_coverage_pct=0.0)
        )


# ---- open space --------------------------------------------------------------


def test_open_space_passes_above_min() -> None:
    # 25% coverage -> 75% open space. min 40% -> pass.
    snap = _snap(20.0, [_sq(10.0, 5.0, 5.0)])
    result = registry.get("open_space_pct")(
        snap, _rule("open_space_pct", min_open_space_pct=40.0)
    )
    assert result.passed is True
    assert result.computed["open_space_pct"] == 75.0


def test_open_space_fails_below_min() -> None:
    # 56.25% coverage -> 43.75% open space. min 50% -> fail.
    snap = _snap(20.0, [_sq(15.0, 2.0, 2.0)])
    result = registry.get("open_space_pct")(
        snap, _rule("open_space_pct", min_open_space_pct=50.0)
    )
    assert result.passed is False
    assert result.computed["open_space_pct"] == 43.75


def test_open_space_with_no_ground_floor_is_100() -> None:
    snap = Snapshot(
        project=ProjectContext(city="X", classification="CBD", zone="Residential"),
        plot=Plot(polygon=_sq(20.0)),
        building=Building(
            floors=[Floor(level=1, polygon=_sq(15.0), height_m=3.0)]
        ),
    )
    result = registry.get("open_space_pct")(
        snap, _rule("open_space_pct", min_open_space_pct=10.0)
    )
    assert result.passed is True
    assert result.computed["open_space_pct"] == 100.0


# ---- joint behavior ----------------------------------------------------------


def test_coverage_plus_open_space_sums_to_100() -> None:
    snap = _snap(20.0, [_sq(13.0, 1.0, 1.0)])
    cov = registry.get("ground_coverage_pct")(
        snap, _rule("ground_coverage_pct", max_coverage_pct=50.0)
    )
    op = registry.get("open_space_pct")(
        snap, _rule("open_space_pct", min_open_space_pct=10.0)
    )
    assert (
        cov.computed["coverage_pct"] + op.computed["open_space_pct"]
        == pytest.approx(100.0)
    )


def test_collinear_plot_rejected_by_geometry_layer() -> None:
    # A "polygon" of 4 collinear points is degenerate. The geometry
    # normalize layer should reject it BEFORE the evaluator sees it,
    # because the post-make_valid result is a LineString, not a
    # Polygon. This pins the failure boundary: the evaluator can
    # assume its inputs already passed shape validation.
    snap = Snapshot(
        project=ProjectContext(city="X", classification="CBD", zone="Residential"),
        plot=Plot(polygon=Polygon(exterior=[[0, 0], [1, 0], [2, 0], [3, 0]])),
        building=Building(
            floors=[Floor(level=0, polygon=_sq(10.0), height_m=3.0)]
        ),
    )
    with pytest.raises(ValidationFailed, match="not a single connected region"):
        registry.get("ground_coverage_pct")(
            snap, _rule("ground_coverage_pct", max_coverage_pct=50.0)
        )


# Note: there is a defensive RuleEvaluationError("plot area is zero
# or negative") branch in _coverage_metrics. Reaching it through
# real input is hard — the geometry normalize layer rejects every
# degenerate polygon we tried (collinear points, hole == exterior,
# etc.) before it gets there. The branch stays as belt-and-suspenders
# for a future input path (e.g. an external adapter that bypasses
# normalize) but isn't unit-tested here.
