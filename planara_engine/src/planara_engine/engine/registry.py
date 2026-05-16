"""Evaluator registry.

Evaluators are pure functions:
    evaluator(snapshot, rule) -> EvaluationResult

They are registered by name; rules reference them by that name.
This decouples the rule pack (data) from the implementation (code).

Registration uses a decorator so a module can be self-contained:
just import it once at boot and the registration runs as a side
effect — see compliance/__init__.py for the ensemble import.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from planara_engine.core.errors import RuleEvaluationError
from planara_engine.domain.snapshot import Snapshot
from planara_engine.domain.violation import Severity
from planara_engine.rules.schema import Rule


@dataclass(frozen=True)
class EvaluationResult:
    """What an evaluator returns.

    passed:    True iff the design satisfies this rule.
    computed:  values that produced the verdict (e.g.
               {"fsi": 3.1, "max_fsi": 2.5}). Used both for
               message rendering and the response's `metrics`
               aggregate.
    severity_override: if the evaluator wants to downgrade (or
               upgrade) the rule's declared severity for this
               specific input (e.g. "warning when within 5% of
               limit, error when over"). None means "use the
               rule's declared severity".
    """

    passed: bool
    computed: dict[str, Any] = field(default_factory=dict)
    severity_override: Severity | None = None


Evaluator = Callable[[Snapshot, Rule], EvaluationResult]

_REGISTRY: dict[str, Evaluator] = {}


def register(name: str) -> Callable[[Evaluator], Evaluator]:
    """Decorator that registers an evaluator under ``name``.

    Re-registering the same name is rejected — silent rebinding
    would hide a typo across two evaluators competing for the
    same key.
    """

    def _wrap(fn: Evaluator) -> Evaluator:
        if name in _REGISTRY:
            raise RuleEvaluationError(
                f"evaluator already registered: {name}",
                details={"evaluator": name},
            )
        _REGISTRY[name] = fn
        return fn

    return _wrap


def get(name: str) -> Evaluator:
    """Look up an evaluator. Raises if the rule references an unknown one."""

    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise RuleEvaluationError(
            f"unknown evaluator: {name}",
            details={"evaluator": name, "known": sorted(_REGISTRY)},
        ) from exc


def known_evaluators() -> list[str]:
    return sorted(_REGISTRY)


def _reset_for_tests() -> None:
    """Clear the registry. ONLY for tests."""

    _REGISTRY.clear()
