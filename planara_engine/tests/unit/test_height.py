"""Height-limit evaluator: above-grade sum, declared override, tolerance."""

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
    import planara_engine.compliance.height as m

    importlib.reload(m)
    yield
    registry._reset_for_tests()


def _square(size: float = 10.0) -> Polygon:
    return Polygon(exterior=[[0, 0], [size, 0], [size, size], [0, size]])


def _snap(
    floors: list[tuple[int, float]],
    total_height_m: float | None = None,
) -> Snapshot:
    """floors = [(level, height_m)]"""

    return Snapshot(
        project=ProjectContext(city="X", classification="CBD", zone="Commercial"),
        plot=Plot(polygon=_square(20.0)),
        building=Building(
            floors=[
                Floor(level=lvl, polygon=_square(8.0), height_m=h)
                for lvl, h in floors
            ],
            total_height_m=total_height_m,
        ),
    )


def _rule(**params: object) -> Rule:
    return Rule(
        id="t.height",
        category="height",
        evaluator="height_limit",
        params=params,
    )


def test_height_passes_under_limit() -> None:
    # 4 above-grade floors @ 3m = 12m; cap 15m -> pass.
    snap = _snap([(0, 3.0), (1, 3.0), (2, 3.0), (3, 3.0)])
    result = registry.get("height_limit")(snap, _rule(max_height_m=15.0))
    assert result.passed is True
    assert result.computed["height_m"] == 12.0
    assert result.computed["max_height_m"] == 15.0
    assert result.computed["above_grade_levels"] == [0, 1, 2, 3]
    assert result.computed["source"] == "computed"


def test_height_fails_over_limit() -> None:
    # 5 floors @ 3m = 15m; cap 12m -> fail.
    snap = _snap([(0, 3.0), (1, 3.0), (2, 3.0), (3, 3.0), (4, 3.0)])
    result = registry.get("height_limit")(snap, _rule(max_height_m=12.0))
    assert result.passed is False
    assert result.computed["height_m"] == 15.0


def test_height_basement_excluded() -> None:
    # 2 above-grade floors @ 3m = 6m; basement of 3m doesn't count.
    snap = _snap([(-1, 3.0), (0, 3.0), (1, 3.0)])
    result = registry.get("height_limit")(snap, _rule(max_height_m=7.0))
    assert result.passed is True
    assert result.computed["height_m"] == 6.0
    assert result.computed["above_grade_levels"] == [0, 1]


def test_height_uses_declared_total_when_set() -> None:
    """When the extractor ships total_height_m, that wins over the sum.

    Real models often have non-uniform floor heights, parapets, or
    a rooftop service penthouse the modeler captured as
    total_height_m without breaking it out as a Floor. Trust the
    declared value when present."""

    snap = _snap([(0, 3.0), (1, 3.0)], total_height_m=8.5)
    result = registry.get("height_limit")(snap, _rule(max_height_m=8.0))
    assert result.passed is False
    assert result.computed["height_m"] == 8.5
    assert result.computed["source"] == "declared"


def test_height_within_tolerance_passes() -> None:
    # 12.001m on 12m cap with default 5mm tolerance -> compliant.
    snap = _snap([(0, 3.0), (1, 3.0), (2, 3.0), (3, 3.001)])
    result = registry.get("height_limit")(snap, _rule(max_height_m=12.0))
    assert result.passed is True


def test_height_custom_tolerance() -> None:
    # 13m on 12m cap with 1m tolerance -> compliant.
    snap = _snap([(0, 3.0), (1, 3.0), (2, 3.0), (3, 4.0)])
    result = registry.get("height_limit")(
        snap, _rule(max_height_m=12.0, tolerance_m=1.0)
    )
    assert result.passed is True


def test_height_missing_max_param_raises() -> None:
    snap = _snap([(0, 3.0)])
    with pytest.raises(ValidationFailed, match="max_height_m"):
        registry.get("height_limit")(snap, _rule())


def test_height_zero_max_raises() -> None:
    snap = _snap([(0, 3.0)])
    with pytest.raises(ValidationFailed, match="must be > 0"):
        registry.get("height_limit")(snap, _rule(max_height_m=0.0))
