"""FSI / FAR evaluator.

FSI (Floor Space Index), also called FAR (Floor Area Ratio), is
the ratio of total built-up floor area to plot area:

    FSI = sum(floor.area for floor in floors if counts_for_fsi(floor)) / plot.area

Which floors count is byelaw-specific. Bangalore (and most Indian
DCRs):
  - Habitable floors above ground count.
  - Stilt parking, services, basements typically excluded.
  - Mezzanines are tricky and treated separately per case.

This evaluator handles the common path:
  - Includes only floors with ``is_habitable=True``.
  - Optionally excludes basements (level < 0) via the rule param
    ``include_basements`` (default False).
  - Optionally excludes level == 0 stilts via ``include_ground``
    (default True; only set False for stilt-parking schemes).

Rule params:
    max_fsi              (required, float > 0) — the byelaw limit.
    include_basements    (optional bool, default False)
    include_ground       (optional bool, default True)
    warn_within_pct      (optional float, default None) — if set,
                         the evaluator returns severity_override=
                         warning when FSI is over (1 - pct) × limit
                         but at-or-below limit. None disables.
"""

from __future__ import annotations

from typing import Any

from planara_engine.compliance.params import require_float
from planara_engine.core.errors import ValidationFailed
from planara_engine.domain import Snapshot
from planara_engine.domain.violation import Severity
from planara_engine.engine.registry import EvaluationResult, register
from planara_engine.geometry import polygon_area
from planara_engine.rules.schema import Rule

EVALUATOR_NAME = "fsi_limit"


@register(EVALUATOR_NAME)
def evaluate(snapshot: Snapshot, rule: Rule) -> EvaluationResult:
    params = rule.params
    max_fsi = require_float(params, "max_fsi", rule_id=rule.id, gt=0.0)
    include_basements = bool(params.get("include_basements", False))
    include_ground = bool(params.get("include_ground", True))
    warn_within_pct = params.get("warn_within_pct")
    if warn_within_pct is not None:
        warn_within_pct = float(warn_within_pct)
        if not 0.0 < warn_within_pct < 1.0:
            raise ValidationFailed(
                f"rule {rule.id}: warn_within_pct must be between 0 and 1 (exclusive)",
                details={"rule_id": rule.id, "value": warn_within_pct},
            )

    plot_area = _plot_area_m2(snapshot)

    counted: list[tuple[int, float]] = []
    for floor in snapshot.building.floors:
        if not floor.is_habitable:
            continue
        if not include_basements and floor.level < 0:
            continue
        if not include_ground and floor.level == 0:
            continue
        counted.append((floor.level, polygon_area(floor.polygon)))

    built_up_m2 = sum(area for _, area in counted)
    fsi = built_up_m2 / plot_area if plot_area > 0 else 0.0

    computed: dict[str, Any] = {
        "fsi": round(fsi, 4),
        "max_fsi": max_fsi,
        "built_up_m2": round(built_up_m2, 2),
        "plot_area_m2": round(plot_area, 2),
        "counted_levels": [lvl for lvl, _ in counted],
    }

    if fsi <= max_fsi:
        # Optional warn-near-limit branch.
        if (
            warn_within_pct is not None
            and fsi >= (1.0 - warn_within_pct) * max_fsi
        ):
            return EvaluationResult(
                passed=False,
                computed=computed,
                severity_override=Severity.warning,
            )
        return EvaluationResult(passed=True, computed=computed)

    return EvaluationResult(passed=False, computed=computed)


def _plot_area_m2(snapshot: Snapshot) -> float:
    """Trust the polygon as authoritative; warn on extractor mismatch."""

    computed = polygon_area(snapshot.plot.polygon)
    declared = snapshot.plot.area_m2
    if declared is not None and abs(declared - computed) / max(computed, 1e-9) > 0.02:
        # 2% tolerance — covers floating-point drift, flags
        # unit-conversion bugs. Just a log; we don't fail the
        # snapshot over it.
        from planara_engine.core.logging import get_logger

        get_logger("planara.compliance.fsi").warning(
            "plot_area_mismatch",
            declared=declared,
            computed=computed,
            snapshot_id=str(snapshot.snapshot_id),
        )
    return computed
