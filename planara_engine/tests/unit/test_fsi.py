"""FSI evaluator: pass/fail thresholds, exclusions, warn-near-limit."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from planara_engine.compliance import fsi as fsi_module  # noqa: F401 — register
from planara_engine.core.errors import ValidationFailed
from planara_engine.domain import (
    Building,
    Floor,
    Plot,
    Polygon,
    Project,
    Severity,
    Snapshot,
)
from planara_engine.engine import registry
from planara_engine.engine.registry import EvaluationResult
from planara_engine.rules.schema import Rule


@pytest.fixture(autouse=True)
def keep_fsi_registered() -> Iterator[None]:
    # The fsi module registered itself on first import. Other
    # tests reset the registry; we re-import here to put it back.
    registry._reset_for_tests()
    import importlib

    import planara_engine.compliance.fsi as m

    importlib.reload(m)
    yield
    registry._reset_for_tests()


def _square(size: float) -> Polygon:
    return Polygon(exterior=[[0, 0], [size, 0], [size, size], [0, size]])


def _snap(floors: list[tuple[int, float, float, bool]], plot_size: float = 20.0) -> Snapshot:
    """floors = [(level, footprint_size, height, is_habitable)]"""

    return Snapshot(
        project=Project(city="Testopolis", classification="CBD", zone="Residential"),
        plot=Plot(polygon=_square(plot_size)),
        building=Building(
            floors=[
                Floor(level=lvl, polygon=_square(size), height_m=h, is_habitable=hab)
                for lvl, size, h, hab in floors
            ]
        ),
    )


def _rule(**params: object) -> Rule:
    return Rule(
        id="t.fsi",
        category="fsi",
        evaluator="fsi_limit",
        params=params,
        message_template="FSI {fsi} > {max_fsi}",
    )


def test_fsi_passes_under_limit() -> None:
    # 20m x 20m plot = 400m2.
    # One 10m x 10m floor = 100m2. FSI = 0.25.
    snap = _snap([(0, 10, 3.0, True)])
    result = registry.get("fsi_limit")(snap, _rule(max_fsi=1.0))
    assert isinstance(result, EvaluationResult)
    assert result.passed is True
    assert result.computed["fsi"] == 0.25
    assert result.computed["max_fsi"] == 1.0
    assert result.computed["built_up_m2"] == 100.0
    assert result.computed["plot_area_m2"] == 400.0


def test_fsi_fails_over_limit() -> None:
    # Three 15m squares on a 20m plot. Built-up = 675, plot = 400, FSI = 1.6875.
    snap = _snap([(0, 15, 3.0, True), (1, 15, 3.0, True), (2, 15, 3.0, True)])
    result = registry.get("fsi_limit")(snap, _rule(max_fsi=1.0))
    assert result.passed is False
    assert result.computed["fsi"] == 1.6875


def test_fsi_excludes_non_habitable() -> None:
    # Level 0 stilt (non-habitable) + level 1 habitable.
    snap = _snap([(0, 15, 3.0, False), (1, 15, 3.0, True)])
    result = registry.get("fsi_limit")(snap, _rule(max_fsi=1.0))
    assert result.computed["counted_levels"] == [1]
    assert result.computed["built_up_m2"] == 225.0


def test_fsi_includes_basement_when_opted_in() -> None:
    # Basement (level -1) excluded by default, included when asked.
    snap = _snap([(-1, 10, 3.0, True), (0, 10, 3.0, True)])

    default = registry.get("fsi_limit")(snap, _rule(max_fsi=1.0))
    assert default.computed["counted_levels"] == [0]

    incl = registry.get("fsi_limit")(snap, _rule(max_fsi=1.0, include_basements=True))
    assert sorted(incl.computed["counted_levels"]) == [-1, 0]


def test_fsi_excludes_ground_when_opted_out() -> None:
    snap = _snap([(0, 10, 3.0, True), (1, 10, 3.0, True)])
    result = registry.get("fsi_limit")(
        snap, _rule(max_fsi=1.0, include_ground=False)
    )
    assert result.computed["counted_levels"] == [1]


def test_fsi_warn_within_pct_triggers_warning() -> None:
    # FSI = 0.9, limit = 1.0, warn within 20% -> warning when fsi >= 0.8.
    snap = _snap([(0, 6, 3.0, True), (1, 6, 3.0, True)])  # 36+36 = 72, /400 = 0.18
    # Adjust to land in the warn band: two 13x13 = 169+169=338, /400 = 0.845
    snap = _snap([(0, 13, 3.0, True), (1, 13, 3.0, True)])
    result = registry.get("fsi_limit")(
        snap, _rule(max_fsi=1.0, warn_within_pct=0.2)
    )
    assert result.passed is False
    assert result.severity_override is Severity.warning
    assert result.computed["fsi"] == 0.845


def test_fsi_warn_within_pct_doesnt_fire_when_far_under() -> None:
    snap = _snap([(0, 5, 3.0, True)])  # 25 / 400 = 0.0625
    result = registry.get("fsi_limit")(
        snap, _rule(max_fsi=1.0, warn_within_pct=0.2)
    )
    assert result.passed is True
    assert result.severity_override is None


def test_fsi_missing_max_fsi_raises_validation() -> None:
    snap = _snap([(0, 10, 3.0, True)])
    with pytest.raises(ValidationFailed, match="missing required param"):
        registry.get("fsi_limit")(snap, _rule())


def test_fsi_max_fsi_must_be_positive() -> None:
    snap = _snap([(0, 10, 3.0, True)])
    with pytest.raises(ValidationFailed, match="must be > 0"):
        registry.get("fsi_limit")(snap, _rule(max_fsi=0.0))


def test_fsi_warn_within_pct_must_be_between_0_and_1() -> None:
    snap = _snap([(0, 10, 3.0, True)])
    with pytest.raises(ValidationFailed, match="warn_within_pct"):
        registry.get("fsi_limit")(snap, _rule(max_fsi=1.0, warn_within_pct=1.5))
