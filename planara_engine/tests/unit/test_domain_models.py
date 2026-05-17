"""Domain model validation: shape rules, edge cases."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from planara_engine.domain import (
    Building,
    Floor,
    Plot,
    Polygon,
    Project,
    Severity,
    Snapshot,
    ValidationResponse,
    Violation,
)

# ---- Polygon -----------------------------------------------------------------


def test_polygon_minimum_valid() -> None:
    p = Polygon(exterior=[[0, 0], [10, 0], [10, 10]])
    assert len(p.exterior) == 3


def test_polygon_accepts_closed_ring_form() -> None:
    Polygon(exterior=[[0, 0], [10, 0], [10, 10], [0, 0]])


def test_polygon_rejects_too_few_points() -> None:
    with pytest.raises(ValidationError):
        Polygon(exterior=[[0, 0], [1, 0]])


def test_polygon_rejects_consecutive_duplicates() -> None:
    with pytest.raises(ValidationError, match="consecutive duplicate"):
        Polygon(exterior=[[0, 0], [0, 0], [10, 10]])


def test_polygon_with_hole() -> None:
    p = Polygon(
        exterior=[[0, 0], [10, 0], [10, 10], [0, 10]],
        holes=[[[2, 2], [4, 2], [4, 4]]],
    )
    assert len(p.holes) == 1


# ---- Project / Plot ----------------------------------------------------------


def test_project_minimal() -> None:
    Project(city="Bangalore", classification="CBD", zone="Residential")


def test_project_overlays_default_empty() -> None:
    p = Project(city="Bangalore", classification="CBD", zone="Residential")
    assert p.overlays == []


def test_project_overlays_round_trip() -> None:
    p = Project(
        city="Bangalore",
        classification="CBD",
        zone="Residential",
        overlays=["airport", "heritage_influence"],
    )
    restored = Project.model_validate_json(p.model_dump_json())
    assert restored.overlays == ["airport", "heritage_influence"]


def test_plot_with_optional_area() -> None:
    poly = Polygon(exterior=[[0, 0], [10, 0], [10, 10]])
    Plot(polygon=poly, area_m2=50.0)
    Plot(polygon=poly)  # area_m2 optional


def test_plot_rejects_non_positive_area() -> None:
    poly = Polygon(exterior=[[0, 0], [10, 0], [10, 10]])
    with pytest.raises(ValidationError):
        Plot(polygon=poly, area_m2=0.0)


# ---- Building / Floor --------------------------------------------------------


def _square(size: float = 10.0) -> Polygon:
    return Polygon(exterior=[[0, 0], [size, 0], [size, size], [0, size]])


def test_building_with_one_floor() -> None:
    b = Building(floors=[Floor(level=0, polygon=_square(), height_m=3.0)])
    assert len(b.floors) == 1


def test_floor_height_bounded() -> None:
    with pytest.raises(ValidationError):
        Floor(level=0, polygon=_square(), height_m=0)
    with pytest.raises(ValidationError):
        Floor(level=0, polygon=_square(), height_m=31)


def test_building_rejects_duplicate_levels() -> None:
    with pytest.raises(ValidationError, match="duplicate floor levels"):
        Building(
            floors=[
                Floor(level=0, polygon=_square(), height_m=3.0),
                Floor(level=0, polygon=_square(), height_m=3.0),
            ]
        )


def test_building_requires_at_least_one_floor() -> None:
    with pytest.raises(ValidationError):
        Building(floors=[])


def test_building_parking_slots_default_zero() -> None:
    b = Building(floors=[Floor(level=0, polygon=_square(), height_m=3.0)])
    assert b.parking_slots_provided == 0


def test_building_parking_slots_must_be_non_negative() -> None:
    with pytest.raises(ValidationError):
        Building(
            floors=[Floor(level=0, polygon=_square(), height_m=3.0)],
            parking_slots_provided=-1,
        )


def test_building_parking_slots_round_trips_through_json() -> None:
    b = Building(
        floors=[Floor(level=0, polygon=_square(), height_m=3.0)],
        parking_slots_provided=12,
    )
    restored = Building.model_validate_json(b.model_dump_json())
    assert restored.parking_slots_provided == 12


# ---- Snapshot ----------------------------------------------------------------


def test_snapshot_assigns_uuid_when_missing() -> None:
    snap = Snapshot(
        project=Project(city="Bangalore", classification="CBD", zone="Residential"),
        plot=Plot(polygon=_square(20)),
        building=Building(floors=[Floor(level=0, polygon=_square(15), height_m=3.0)]),
    )
    assert snap.snapshot_id is not None


def test_snapshot_round_trip_through_json() -> None:
    snap = Snapshot(
        project=Project(city="Bangalore", classification="CBD", zone="Residential"),
        plot=Plot(polygon=_square(20), area_m2=400.0),
        building=Building(
            floors=[
                Floor(level=0, polygon=_square(15), height_m=3.0),
                Floor(level=1, polygon=_square(15), height_m=3.0),
            ]
        ),
    )
    payload = snap.model_dump_json()
    restored = Snapshot.model_validate_json(payload)
    assert restored.snapshot_id == snap.snapshot_id
    assert len(restored.building.floors) == 2


def test_snapshot_schema_version_defaults() -> None:
    """A snapshot built without schema_version assumes the current
    wire version. The plugin always emits it; old recorded JSON
    fixtures captured before Sprint 6 can still round-trip."""

    from planara_engine.domain.snapshot import CURRENT_SCHEMA_VERSION

    snap = Snapshot(
        project=Project(city="Bangalore", classification="CBD", zone="Residential"),
        plot=Plot(polygon=_square(20)),
        building=Building(floors=[Floor(level=0, polygon=_square(15), height_m=3.0)]),
    )
    assert snap.schema_version == CURRENT_SCHEMA_VERSION


def test_snapshot_accepts_older_schema_version() -> None:
    """Older clients must not be rejected for declaring an old
    schema_version — the engine logs and continues. The plugin
    ships ahead of the engine in some deploys."""

    snap = Snapshot(
        schema_version="0.9",
        project=Project(city="Bangalore", classification="CBD", zone="Residential"),
        plot=Plot(polygon=_square(20)),
        building=Building(floors=[Floor(level=0, polygon=_square(15), height_m=3.0)]),
    )
    assert snap.schema_version == "0.9"


# ---- Violation / ValidationResponse -----------------------------------------


def test_validation_response_ok_with_no_errors() -> None:
    resp = ValidationResponse(snapshot_id=Snapshot.model_construct().snapshot_id, ok=True)
    assert resp.violations == []
    assert resp.metrics == {}


def test_violation_severity_enum() -> None:
    v = Violation(rule_id="x", category="fsi", severity=Severity.error, message="m")
    assert v.severity == "error"
    # String compatible: JSON serialization keeps the enum value as a string.
    dumped = v.model_dump(mode="json")
    assert dumped["severity"] == "error"
