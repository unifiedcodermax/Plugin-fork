"""Ground coverage + open space evaluators.

These two evaluators consume the same input (ground-floor
footprints + plot polygon) and are duals:

    coverage_pct + open_space_pct = 100  (approximately —
    overlap-resolved via Shapely union, so the equality holds
    exactly for non-degenerate inputs).

They live as two separate evaluators (not one with two outputs)
because byelaws express the two limits independently — e.g.
"max coverage 50%" AND "min open space 40%". A single design can
violate one but not the other when the missing 10% is unused.
"""

from __future__ import annotations

from typing import Any

from planara_engine.compliance.params import require_float
from planara_engine.core.errors import RuleEvaluationError
from planara_engine.domain import Snapshot
from planara_engine.domain.building import Floor
from planara_engine.engine.registry import EvaluationResult, register
from planara_engine.geometry import polygon_area, polygons_union_area
from planara_engine.rules.schema import Rule

COVERAGE_NAME = "ground_coverage_pct"
OPEN_SPACE_NAME = "open_space_pct"


def _ground_floors(snapshot: Snapshot) -> list[Floor]:
    """Return the floors that count as "ground" for coverage math.

    Some buildings have multiple ground-level groups (a main block
    and a detached service room). All level == 0 footprints get
    union'd; the union's area is the coverage area.
    """

    return [f for f in snapshot.building.floors if f.level == 0]


def _coverage_metrics(snapshot: Snapshot) -> tuple[float, float, float]:
    """Return (ground_area_m2, plot_area_m2, coverage_pct)."""

    plot_area_m2 = polygon_area(snapshot.plot.polygon)
    if plot_area_m2 <= 0:
        raise RuleEvaluationError(
            "plot area is zero or negative",
            details={"snapshot_id": str(snapshot.snapshot_id)},
        )

    ground = _ground_floors(snapshot)
    ground_area_m2 = polygons_union_area([f.polygon for f in ground])
    coverage_pct = (ground_area_m2 / plot_area_m2) * 100.0
    return ground_area_m2, plot_area_m2, coverage_pct


@register(COVERAGE_NAME)
def evaluate_coverage(snapshot: Snapshot, rule: Rule) -> EvaluationResult:
    max_pct = require_float(rule.params, "max_coverage_pct", rule_id=rule.id, gt=0.0)

    ground_area_m2, plot_area_m2, coverage_pct = _coverage_metrics(snapshot)

    computed: dict[str, Any] = {
        "coverage_pct": round(coverage_pct, 2),
        "max_coverage_pct": max_pct,
        "ground_area_m2": round(ground_area_m2, 2),
        "plot_area_m2": round(plot_area_m2, 2),
    }

    # A small tolerance protects against float drift in the union
    # area calculation; coverage that comes out to 50.0001% should
    # not fail a 50% rule.
    return EvaluationResult(passed=coverage_pct <= max_pct + 1e-6, computed=computed)


@register(OPEN_SPACE_NAME)
def evaluate_open_space(snapshot: Snapshot, rule: Rule) -> EvaluationResult:
    min_pct = require_float(rule.params, "min_open_space_pct", rule_id=rule.id, gt=0.0)

    ground_area_m2, plot_area_m2, coverage_pct = _coverage_metrics(snapshot)
    open_space_pct = 100.0 - coverage_pct
    open_space_m2 = plot_area_m2 - ground_area_m2

    computed: dict[str, Any] = {
        "open_space_pct": round(open_space_pct, 2),
        "min_open_space_pct": min_pct,
        "open_space_m2": round(open_space_m2, 2),
        "plot_area_m2": round(plot_area_m2, 2),
    }

    return EvaluationResult(passed=open_space_pct + 1e-6 >= min_pct, computed=computed)
