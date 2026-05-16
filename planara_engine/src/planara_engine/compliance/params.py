"""Param validation helpers shared across evaluators.

Each evaluator declares the params it needs; this module gives
consistent error messages when a rule pack ships malformed values.
"""

from __future__ import annotations

from typing import Any

from planara_engine.core.errors import ValidationFailed


def require_float(
    params: dict[str, Any],
    key: str,
    *,
    rule_id: str,
    gt: float | None = None,
    ge: float | None = None,
) -> float:
    """Read a float param. Validate range. Raise with rule context."""

    if key not in params:
        raise ValidationFailed(
            f"rule {rule_id}: missing required param '{key}'",
            details={"rule_id": rule_id, "param": key},
        )

    try:
        value = float(params[key])
    except (TypeError, ValueError) as exc:
        raise ValidationFailed(
            f"rule {rule_id}: param '{key}' is not a number",
            details={"rule_id": rule_id, "param": key, "value": params[key]},
        ) from exc

    if gt is not None and not value > gt:
        raise ValidationFailed(
            f"rule {rule_id}: param '{key}' must be > {gt}",
            details={"rule_id": rule_id, "param": key, "value": value},
        )
    if ge is not None and not value >= ge:
        raise ValidationFailed(
            f"rule {rule_id}: param '{key}' must be >= {ge}",
            details={"rule_id": rule_id, "param": key, "value": value},
        )

    return value
