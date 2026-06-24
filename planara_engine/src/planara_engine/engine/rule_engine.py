"""RuleEngine: select applicable rules, dispatch to evaluators, aggregate.

One entry point, ``evaluate(snapshot)``, returns a
ValidationResponse ready to send back to the plugin.
"""

from __future__ import annotations

from typing import Any

from planara_engine.core.logging import get_logger
from planara_engine.domain.snapshot import Snapshot
from planara_engine.domain.violation import Severity, ValidationResponse, Violation
from planara_engine.engine import registry
from planara_engine.rules.loader import applicable_rules, get_pack
from planara_engine.rules.schema import Rule

log = get_logger("planara.engine")


def evaluate(snapshot: Snapshot) -> ValidationResponse:
    """Validate a Snapshot against the appropriate rule pack."""

    pack = get_pack(snapshot.project.city)
    matched = applicable_rules(
        pack,
        classification=snapshot.project.classification,
        zone=snapshot.project.zone,
        overlays=snapshot.project.overlays,
    )

    log.info(
        "evaluating",
        snapshot_id=str(snapshot.snapshot_id),
        city=snapshot.project.city,
        classification=snapshot.project.classification,
        zone=snapshot.project.zone,
        overlays=snapshot.project.overlays,
        rule_count=len(matched),
    )

    violations: list[Violation] = []
    metrics: dict[str, Any] = {}

    for rule in matched:
        evaluator = registry.get(rule.evaluator)
        result = evaluator(snapshot, rule)

        # Always merge computed into metrics so the plugin can render
        # values even for rules that PASSED (the user wants to see
        # their actual FSI, not just whether it's over the limit).
        # Skip info-severity rules as they often contain dummy limits (like max_fsi 999.0)
        if rule.severity != Severity.info:
            metrics.update(result.computed)

        if result.passed:
            continue

        severity = result.severity_override or rule.severity
        violations.append(
            Violation(
                rule_id=rule.id,
                category=rule.category,
                severity=severity,
                message=_render_message(rule, result.computed),
                hint=_render_hint(rule, result.computed),
                computed=result.computed,
            )
        )

    metrics.setdefault("rule_pack_version", pack.version)
    metrics.setdefault("rule_count", len(matched))

    ok = not any(v.severity == Severity.error for v in violations)
    return ValidationResponse(
        snapshot_id=snapshot.snapshot_id,
        ok=ok,
        violations=violations,
        metrics=metrics,
    )


def _render_message(rule: Rule, computed: dict[str, Any]) -> str:
    """Render the rule's message_template against computed + params.

    Uses str.format_map with a fallback that returns the literal
    placeholder for missing keys. This is safer than .format()
    which would raise KeyError and crash the whole evaluate call
    because one rule template references a typo'd field.
    """

    if not rule.message_template:
        return f"violation: {rule.id}"

    context = _SafeDict({**rule.params, **computed})
    try:
        return rule.message_template.format_map(context)
    except (ValueError, IndexError):
        # Bad format spec inside the template itself — still
        # return SOMETHING the plugin can show.
        return f"violation: {rule.id}"


def _render_hint(rule: Rule, computed: dict[str, Any]) -> str | None:
    """Render the rule's hint_template, or return None if unset."""

    if not rule.hint_template:
        return None

    context = _SafeDict({**rule.params, **computed})
    try:
        return rule.hint_template.format_map(context)
    except (ValueError, IndexError):
        return None


class _SafeDict(dict[str, Any]):
    """dict that returns ``{key}`` for missing keys, so str.format_map
    doesn't raise when a rule template references a missing field."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
