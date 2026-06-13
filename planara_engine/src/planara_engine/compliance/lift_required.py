"""Lift-requirement evaluator.

Bangalore Building Byelaws 2003, Bye-law 20.7:
    "Provision of lifts shall be made for all buildings with a
     height of 15 mtrs. and above and or having more than ground
     plus three floors in accordance with Part VIII, section 5
     of the National Building Code with regard to planning and
     designing of lifts."

This evaluator checks whether the building exceeds the height
or floor-count threshold that triggers a lift requirement.  It
then compares against ``Building.has_lift`` to determine
compliance.

If the building is below both thresholds, the rule passes
unconditionally (lift is optional).

Rule params:
    height_threshold_m   (required, float > 0) — height at which
                          a lift becomes mandatory (15.0 per the
                          byelaw).
    floor_threshold      (optional int, default 4) — above-grade
                          floor count that triggers the rule.
                          "more than G+3" = 4 above-grade floors
                          (G, 1, 2, 3 = 4 floors; 5th triggers).
    tolerance_m          (optional float, default 0.005) — float
                          drift guard for the height comparison.
"""

from __future__ import annotations

from typing import Any

from planara_engine.compliance.params import require_float
from planara_engine.domain import Snapshot
from planara_engine.engine.registry import EvaluationResult, register
from planara_engine.rules.schema import Rule

EVALUATOR_NAME = "lift_required"


@register(EVALUATOR_NAME)
def evaluate(snapshot: Snapshot, rule: Rule) -> EvaluationResult:
    params = rule.params
    height_threshold_m = require_float(
        params, "height_threshold_m", rule_id=rule.id, gt=0.0,
    )
    floor_threshold = int(params.get("floor_threshold", 4))
    tolerance_m = float(params.get("tolerance_m", 0.005))

    above_grade = [f for f in snapshot.building.floors if f.level >= 0]
    above_grade_count = len(above_grade)

    declared = snapshot.building.total_height_m
    computed_height = sum(f.height_m for f in above_grade)
    height_m = declared if declared is not None else computed_height

    has_lift = snapshot.building.has_lift

    computed: dict[str, Any] = {
        "height_m": round(height_m, 4),
        "height_threshold_m": height_threshold_m,
        "above_grade_floors": above_grade_count,
        "floor_threshold": floor_threshold,
        "has_lift": has_lift,
        "source": "declared" if declared is not None else "computed",
    }

    # Check if lift is required
    height_exceeds = height_m + tolerance_m >= height_threshold_m
    floors_exceed = above_grade_count > floor_threshold
    lift_required = height_exceeds or floors_exceed

    if not lift_required:
        # Building is under both thresholds — lift is optional.
        return EvaluationResult(passed=True, computed=computed)

    # Lift IS required — check if one is provided.
    return EvaluationResult(passed=has_lift, computed=computed)
