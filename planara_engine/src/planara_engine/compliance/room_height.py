"""Minimum room-height evaluator.

Bangalore Building Byelaws 2003, Bye-law 20.1(2):
    "The minimum height of all rooms used for human habitation
     shall be 2.75 m measured from the surface of the floor to
     the lowest point of the ceiling (bottom slab)."
    "In case of air conditioned rooms, the height of not less
     than 2.4 m measured from the surface of the floor to the
     lowest point of the air conditioning duct or false ceiling
     shall be provided."

This evaluator checks every habitable above-grade floor's
``height_m`` against the byelaw minimum.  It fails on the
first floor that is too short (worst violator) and reports
all per-floor heights in ``computed``.

Rule params:
    min_height_m   (required, float > 0) — the byelaw floor.
    tolerance_m    (optional float, default 0.005) — sub-mm
                   float drift guard.
"""

from __future__ import annotations

from typing import Any

from planara_engine.compliance.params import require_float
from planara_engine.domain import Snapshot
from planara_engine.engine.registry import EvaluationResult, register
from planara_engine.rules.schema import Rule

EVALUATOR_NAME = "min_room_height"


@register(EVALUATOR_NAME)
def evaluate(snapshot: Snapshot, rule: Rule) -> EvaluationResult:
    params = rule.params
    min_height_m = require_float(params, "min_height_m", rule_id=rule.id, gt=0.0)
    tolerance_m = float(params.get("tolerance_m", 0.005))

    per_floor: list[dict[str, Any]] = []
    worst_height: float | None = None
    worst_level: int | None = None

    for floor in snapshot.building.floors:
        if not floor.is_habitable:
            continue
        if floor.level < 0:
            continue
        per_floor.append({"level": floor.level, "height_m": round(floor.height_m, 4)})
        if worst_height is None or floor.height_m < worst_height:
            worst_height = floor.height_m
            worst_level = floor.level

    if not per_floor:
        empty_computed = {
            "min_height_m": min_height_m,
            "per_floor": per_floor,
            "note": "no habitable above-grade floors found",
        }
        return EvaluationResult(passed=True, computed=empty_computed)

    computed: dict[str, Any] = {
        "min_height_m": min_height_m,
        "violating_height_m": round(worst_height or 0.0, 4),
        "violating_level": worst_level,
        "per_floor": per_floor,
    }

    passed = (worst_height or 0.0) + tolerance_m >= min_height_m
    return EvaluationResult(passed=passed, computed=computed)
