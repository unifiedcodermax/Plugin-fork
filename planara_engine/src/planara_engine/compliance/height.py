"""Absolute building-height evaluator.

Fires for overlays that cap the total above-grade height of a
structure — most commonly an airport approach-surface restriction
or a heritage-influence character zone. Distinct from FSI (which
caps floor-area ratio) and setback (which caps lateral position).

Building height is computed as:
    sum(floor.height_m for floor in floors if floor.level >= 0)
unless ``Building.total_height_m`` is set, in which case the
extractor-provided value wins and the computed sum is logged for
comparison. Basements (level < 0) are excluded — airport approach
surfaces and heritage skylines care about what's visible above
grade, not what's buried.

Rule params:
    max_height_m   (required, float > 0) — the byelaw ceiling.
    tolerance_m    (optional float, default 0.005) — heights
                   within this of the limit are treated as
                   compliant; absorbs sub-mm float drift.
"""

from __future__ import annotations

from typing import Any

from planara_engine.compliance.params import require_float
from planara_engine.domain import Snapshot
from planara_engine.engine.registry import EvaluationResult, register
from planara_engine.rules.schema import Rule

EVALUATOR_NAME = "height_limit"


@register(EVALUATOR_NAME)
def evaluate(snapshot: Snapshot, rule: Rule) -> EvaluationResult:
    params = rule.params
    max_height_m = require_float(params, "max_height_m", rule_id=rule.id, gt=0.0)
    tolerance_m = float(params.get("tolerance_m", 0.005))

    computed_height = sum(
        f.height_m for f in snapshot.building.floors if f.level >= 0
    )
    declared = snapshot.building.total_height_m

    if declared is not None and abs(declared - computed_height) / max(computed_height, 1e-9) > 0.02:
        # 2% tolerance — same threshold as fsi.py's plot_area mismatch.
        from planara_engine.core.logging import get_logger

        get_logger("planara.compliance.height").warning(
            "total_height_mismatch",
            declared=declared,
            computed=computed_height,
            snapshot_id=str(snapshot.snapshot_id),
        )

    height_m = declared if declared is not None else computed_height

    computed: dict[str, Any] = {
        "height_m": round(height_m, 4),
        "max_height_m": max_height_m,
        "above_grade_levels": [
            f.level for f in snapshot.building.floors if f.level >= 0
        ],
        "source": "declared" if declared is not None else "computed",
    }

    passed = height_m <= max_height_m + tolerance_m
    return EvaluationResult(passed=passed, computed=computed)
