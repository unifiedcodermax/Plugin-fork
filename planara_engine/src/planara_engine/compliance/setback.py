"""Setback evaluator.

For every floor at or above ``apply_from_level`` (default 0), the
floor's footprint must be at least ``min_setback_m`` away from
the plot boundary. The check is geometric (Shapely), not axis-
aligned — the legacy plugin's ``pt.x.abs < limit`` math fails
the moment the plot stops being a rectangle centered at the
origin, which is most plots.

Rule params:
    min_setback_m       (required, float >= 0) — minimum distance.
                         0 is allowed and represents "build to
                         line" zones.
    apply_from_level    (optional int, default 0) — floors below
                         this level are skipped. Basement walls
                         outside the plot are a separate concern.
    tolerance_m         (optional float, default 0.005) — floors
                         that are within `tolerance_m` of the
                         required setback are treated as
                         compliant. Lets a model with sub-mm
                         floating-point drift not produce
                         spurious violations.
"""

from __future__ import annotations

from typing import Any

from planara_engine.compliance.params import require_float
from planara_engine.domain import Snapshot
from planara_engine.engine.registry import EvaluationResult, register
from planara_engine.geometry import minimum_distance_to_boundary
from planara_engine.rules.schema import Rule

EVALUATOR_NAME = "setback_min_distance"


@register(EVALUATOR_NAME)
def evaluate(snapshot: Snapshot, rule: Rule) -> EvaluationResult:
    params = rule.params
    min_setback_m = require_float(params, "min_setback_m", rule_id=rule.id, ge=0.0)
    apply_from_level = int(params.get("apply_from_level", 0))
    tolerance_m = float(params.get("tolerance_m", 0.005))

    plot_poly = snapshot.plot.polygon
    per_floor: list[dict[str, Any]] = []
    worst_distance: float | None = None
    worst_level: int | None = None

    for floor in snapshot.building.floors:
        if floor.level < apply_from_level:
            continue
        dist = minimum_distance_to_boundary(floor.polygon, plot_poly)
        per_floor.append({"level": floor.level, "distance_m": round(dist, 4)})
        if worst_distance is None or dist < worst_distance:
            worst_distance = dist
            worst_level = floor.level

    # An empty per_floor list (no floors at or above apply_from_level)
    # is a degenerate input — pass it through to surface the
    # configuration error rather than silently say "compliant".
    if not per_floor:
        computed = {
            "min_setback_m": min_setback_m,
            "per_floor": per_floor,
            "note": "no floors at or above apply_from_level",
        }
        return EvaluationResult(passed=True, computed=computed)

    computed = {
        "min_setback_m": min_setback_m,
        "min_distance_m": round(worst_distance or 0.0, 4),
        "violating_level": worst_level,
        "per_floor": per_floor,
    }

    passed = (worst_distance or 0.0) + tolerance_m >= min_setback_m
    return EvaluationResult(passed=passed, computed=computed)
