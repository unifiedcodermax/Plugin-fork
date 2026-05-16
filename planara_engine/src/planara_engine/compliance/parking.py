"""Parking evaluator.

Real byelaws express parking demand in several forms:
  - "1 car per 50 sqm of commercial built-up"           (per-area)
  - "1 car per dwelling unit"                            (per-unit)
  - "1 car per 4 hotel rooms / hospital beds"           (per-unit)

The MVP supports the per-area form only. Per-unit forms need a
unit-count field on the snapshot that the extractor cannot
discover automatically; deferring until that input plumbing
exists (post-MVP).

Demand:
    required = ceil(habitable_built_up_m2 / m2_per_slot)

Where habitable_built_up_m2 is the same sum used by the FSI
evaluator (level >= 0, is_habitable=True). Keeping the input
identical between FSI and parking means a single design change
doesn't shift the two evaluators in opposite directions.

Rule params:
    m2_per_slot          (required, float > 0) — square meters of
                          built-up area per required parking slot.
                          Bangalore CMC bylaws (typical):
                            50 for commercial,
                            100 for residential.
    include_basements    (optional bool, default False)
    visitor_pct          (optional float, default 0) — additional
                          slots required as a percentage of the
                          computed primary requirement (rounded
                          up). The legacy rules.json suggests
                          10% for visitor parking.
"""

from __future__ import annotations

import math
from typing import Any

from planara_engine.compliance.params import require_float
from planara_engine.domain import Snapshot
from planara_engine.engine.registry import EvaluationResult, register
from planara_engine.geometry import polygon_area
from planara_engine.rules.schema import Rule

EVALUATOR_NAME = "parking_slots_required"


@register(EVALUATOR_NAME)
def evaluate(snapshot: Snapshot, rule: Rule) -> EvaluationResult:
    m2_per_slot = require_float(rule.params, "m2_per_slot", rule_id=rule.id, gt=0.0)
    include_basements = bool(rule.params.get("include_basements", False))
    visitor_pct = float(rule.params.get("visitor_pct", 0.0))
    if not 0.0 <= visitor_pct <= 100.0:
        from planara_engine.core.errors import ValidationFailed

        raise ValidationFailed(
            f"rule {rule.id}: visitor_pct must be in [0, 100]",
            details={"rule_id": rule.id, "value": visitor_pct},
        )

    built_up_m2 = sum(
        polygon_area(f.polygon)
        for f in snapshot.building.floors
        if f.is_habitable and (include_basements or f.level >= 0)
    )

    primary = math.ceil(built_up_m2 / m2_per_slot)
    visitor = math.ceil(primary * visitor_pct / 100.0)
    required = primary + visitor
    provided = snapshot.building.parking_slots_provided

    computed: dict[str, Any] = {
        "parking_slots_required": required,
        "parking_slots_provided": provided,
        "primary_slots": primary,
        "visitor_slots": visitor,
        "built_up_m2": round(built_up_m2, 2),
        "m2_per_slot": m2_per_slot,
        "visitor_pct": visitor_pct,
    }

    return EvaluationResult(passed=provided >= required, computed=computed)
