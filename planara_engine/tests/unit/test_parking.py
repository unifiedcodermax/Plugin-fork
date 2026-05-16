"""Parking evaluator: demand calc, visitor pct, basement opt-in."""

from __future__ import annotations

import importlib
import math
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
    import planara_engine.compliance.parking as m

    importlib.reload(m)
    yield
    registry._reset_for_tests()


def _sq(size: float) -> Polygon:
    return Polygon(exterior=[[0, 0], [size, 0], [size, size], [0, size]])


def _snap(
    floors: list[tuple[int, float, bool]],
    provided: int = 0,
    plot_size: float = 20.0,
) -> Snapshot:
    """floors = [(level, size, is_habitable)]"""

    return Snapshot(
        project=Project(city="X", classification="CBD", zone="Commercial"),
        plot=Plot(polygon=_sq(plot_size)),
        building=Building(
            floors=[
                Floor(level=lvl, polygon=_sq(size), height_m=3.0, is_habitable=hab)
                for lvl, size, hab in floors
            ],
            parking_slots_provided=provided,
        ),
    )


def _rule(**params: object) -> Rule:
    return Rule(
        id="t.parking",
        category="parking",
        evaluator="parking_slots_required",
        params=params,
    )


def test_passes_when_provided_meets_required() -> None:
    # 2 floors of 10x10 = 200 m^2. m2_per_slot=50 -> 4 required.
    snap = _snap([(0, 10.0, True), (1, 10.0, True)], provided=4)
    result = registry.get("parking_slots_required")(snap, _rule(m2_per_slot=50.0))
    assert result.passed is True
    assert result.computed["parking_slots_required"] == 4
    assert result.computed["parking_slots_provided"] == 4
    assert result.computed["built_up_m2"] == 200.0


def test_fails_when_under_provided() -> None:
    snap = _snap([(0, 10.0, True), (1, 10.0, True)], provided=2)
    result = registry.get("parking_slots_required")(snap, _rule(m2_per_slot=50.0))
    assert result.passed is False
    assert result.computed["parking_slots_required"] == 4


def test_demand_rounds_up() -> None:
    # 100 m^2 built-up, 50 m^2 per slot -> 2 required.
    # 110 m^2 built-up, 50 m^2 per slot -> ceil(2.2) = 3 required.
    snap = _snap(
        [(0, 10.0, True), (1, math.sqrt(10.0), True)],  # 100 + ~10 = ~110
        provided=2,
    )
    result = registry.get("parking_slots_required")(snap, _rule(m2_per_slot=50.0))
    assert result.passed is False
    assert result.computed["parking_slots_required"] == 3


def test_non_habitable_excluded() -> None:
    # Stilt floor at level 0 (non-habitable), habitable floor at level 1.
    snap = _snap(
        [(0, 14.142, False), (1, 10.0, True)],  # stilt ignored, 100m^2 used
        provided=2,
    )
    result = registry.get("parking_slots_required")(snap, _rule(m2_per_slot=50.0))
    assert result.passed is True
    assert result.computed["parking_slots_required"] == 2


def test_basements_excluded_by_default() -> None:
    # Habitable basement at -1, habitable level 0. Default: basement
    # not counted.
    snap = _snap(
        [(-1, 10.0, True), (0, 10.0, True)],
        provided=2,
    )
    result = registry.get("parking_slots_required")(snap, _rule(m2_per_slot=50.0))
    assert result.passed is True
    assert result.computed["built_up_m2"] == 100.0  # ground only


def test_basements_included_when_opted_in() -> None:
    snap = _snap(
        [(-1, 10.0, True), (0, 10.0, True)],
        provided=2,
    )
    result = registry.get("parking_slots_required")(
        snap, _rule(m2_per_slot=50.0, include_basements=True)
    )
    assert result.passed is False
    assert result.computed["built_up_m2"] == 200.0
    assert result.computed["parking_slots_required"] == 4


def test_visitor_pct_adds_slots() -> None:
    # 4 primary, 10% visitor -> ceil(0.4) = 1 visitor -> 5 total.
    snap = _snap([(0, 10.0, True), (1, 10.0, True)], provided=4)
    result = registry.get("parking_slots_required")(
        snap, _rule(m2_per_slot=50.0, visitor_pct=10.0)
    )
    assert result.passed is False
    assert result.computed["primary_slots"] == 4
    assert result.computed["visitor_slots"] == 1
    assert result.computed["parking_slots_required"] == 5


def test_visitor_pct_zero_is_default() -> None:
    snap = _snap([(0, 10.0, True)], provided=2)
    result = registry.get("parking_slots_required")(snap, _rule(m2_per_slot=50.0))
    assert result.computed["visitor_slots"] == 0


def test_m2_per_slot_required() -> None:
    snap = _snap([(0, 10.0, True)], provided=2)
    with pytest.raises(ValidationFailed, match="missing required param"):
        registry.get("parking_slots_required")(snap, _rule())


def test_m2_per_slot_must_be_positive() -> None:
    snap = _snap([(0, 10.0, True)], provided=2)
    with pytest.raises(ValidationFailed):
        registry.get("parking_slots_required")(snap, _rule(m2_per_slot=0.0))


def test_visitor_pct_bounds() -> None:
    snap = _snap([(0, 10.0, True)], provided=2)
    with pytest.raises(ValidationFailed, match="visitor_pct"):
        registry.get("parking_slots_required")(
            snap, _rule(m2_per_slot=50.0, visitor_pct=120.0)
        )
    with pytest.raises(ValidationFailed, match="visitor_pct"):
        registry.get("parking_slots_required")(
            snap, _rule(m2_per_slot=50.0, visitor_pct=-1.0)
        )


