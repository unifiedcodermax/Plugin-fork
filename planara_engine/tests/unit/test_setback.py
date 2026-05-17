"""Setback evaluator: distance math, tolerance, level filter."""

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
    Project,
    Snapshot,
)
from planara_engine.engine import registry
from planara_engine.rules.schema import Rule


@pytest.fixture(autouse=True)
def fresh_registry() -> Iterator[None]:
    registry._reset_for_tests()
    # Re-import the evaluator module so @register fires again in
    # this test's fresh registry.
    import planara_engine.compliance.setback as m

    importlib.reload(m)
    yield
    registry._reset_for_tests()


def _square(size: float, ox: float = 0.0, oy: float = 0.0) -> Polygon:
    return Polygon(
        exterior=[[ox, oy], [ox + size, oy], [ox + size, oy + size], [ox, oy + size]]
    )


def _snap(plot_size: float, floors: list[tuple[int, float, float, float]]) -> Snapshot:
    """floors = [(level, building_size, ox, oy)]"""

    return Snapshot(
        project=Project(city="X", classification="CBD", zone="Residential"),
        plot=Plot(polygon=_square(plot_size)),
        building=Building(
            floors=[
                Floor(level=lvl, polygon=_square(size, ox, oy), height_m=3.0)
                for lvl, size, ox, oy in floors
            ]
        ),
    )


def _rule(**params: object) -> Rule:
    return Rule(
        id="t.setback",
        category="setback",
        evaluator="setback_min_distance",
        params=params,
    )


def test_passes_when_centered_with_setback() -> None:
    # 20m plot, 10m building centered at (5,5) -> 5m clearance everywhere.
    snap = _snap(20.0, [(0, 10.0, 5.0, 5.0)])
    result = registry.get("setback_min_distance")(snap, _rule(min_setback_m=3.0))
    assert result.passed is True
    assert result.computed["min_distance_m"] == 5.0


def test_fails_when_too_close() -> None:
    # 20m plot, 10m building offset to (1,1) -> 1m clearance on two sides.
    snap = _snap(20.0, [(0, 10.0, 1.0, 1.0)])
    result = registry.get("setback_min_distance")(snap, _rule(min_setback_m=3.0))
    assert result.passed is False
    assert result.computed["min_distance_m"] == 1.0
    assert result.computed["violating_level"] == 0


def test_passes_when_touching_boundary_and_setback_is_zero() -> None:
    # "Build to line" zone: setback 0 lets the building hug the plot.
    snap = _snap(20.0, [(0, 10.0, 0.0, 0.0)])
    result = registry.get("setback_min_distance")(snap, _rule(min_setback_m=0.0))
    assert result.passed is True


def test_tolerance_lets_near_miss_pass() -> None:
    # 2.999m clearance vs 3.0 required -> default tolerance 0.005 makes
    # this pass.
    snap = _snap(20.0, [(0, 10.0, 2.999, 5.0)])
    result = registry.get("setback_min_distance")(snap, _rule(min_setback_m=3.0))
    assert result.passed is True


def test_tolerance_does_not_help_real_violations() -> None:
    snap = _snap(20.0, [(0, 10.0, 2.0, 5.0)])
    result = registry.get("setback_min_distance")(snap, _rule(min_setback_m=3.0))
    assert result.passed is False


def test_apply_from_level_default_skips_basement() -> None:
    # Basement clear-too-close (touches boundary), ground floor fine.
    # Default apply_from_level=0 means basement (level=-1) is skipped:
    # ground floor passes, overall passes.
    snap = _snap(
        20.0,
        [
            (-1, 18.0, 1.0, 1.0),  # basement, 1m clearance — would fail if checked
            (0, 10.0, 5.0, 5.0),    # ground floor, 5m clearance
        ],
    )
    result = registry.get("setback_min_distance")(snap, _rule(min_setback_m=3.0))
    assert result.passed is True
    # The basement was filtered out — only the ground floor reported.
    assert [f["level"] for f in result.computed["per_floor"]] == [0]


def test_apply_from_level_override_includes_basement() -> None:
    # Same scenario, but the rule pack overrides apply_from_level=-2,
    # so the basement IS checked and fails.
    snap = _snap(
        20.0,
        [
            (-1, 18.0, 1.0, 1.0),  # basement, 1m clearance
            (0, 10.0, 5.0, 5.0),    # ground floor, 5m clearance
        ],
    )
    result = registry.get("setback_min_distance")(
        snap, _rule(min_setback_m=3.0, apply_from_level=-2)
    )
    assert result.passed is False
    assert result.computed["violating_level"] == -1
    assert result.computed["min_distance_m"] == 1.0


def test_no_floors_at_or_above_level_passes_with_note() -> None:
    # Only a basement, apply_from_level=0 default -> nothing to check.
    snap = _snap(20.0, [(-2, 18.0, 0.0, 0.0)])
    result = registry.get("setback_min_distance")(snap, _rule(min_setback_m=3.0))
    assert result.passed is True
    assert "no floors" in result.computed["note"]


def test_min_setback_must_be_non_negative() -> None:
    snap = _snap(20.0, [(0, 10.0, 5.0, 5.0)])
    with pytest.raises(ValidationFailed, match="must be >= 0"):
        registry.get("setback_min_distance")(snap, _rule(min_setback_m=-1.0))


def test_min_setback_required() -> None:
    snap = _snap(20.0, [(0, 10.0, 5.0, 5.0)])
    with pytest.raises(ValidationFailed, match="missing required param"):
        registry.get("setback_min_distance")(snap, _rule())


def test_picks_worst_floor() -> None:
    # Three floors, each at a different offset. The closest-to-edge wins.
    snap = _snap(
        20.0,
        [
            (0, 10.0, 5.0, 5.0),  # 5m clearance
            (1, 10.0, 2.0, 5.0),  # 2m clearance
            (2, 10.0, 4.0, 5.0),  # 4m clearance
        ],
    )
    result = registry.get("setback_min_distance")(snap, _rule(min_setback_m=3.0))
    assert result.passed is False
    assert result.computed["min_distance_m"] == 2.0
    assert result.computed["violating_level"] == 1
